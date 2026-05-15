"""Build per-fill ledger across R2 v82-family submissions.

Mirrors the methodology of docs/round1_postmortem/ledger.md but on R2 data.
For each own fill: timestamp, product, side, size, price, edge at fill,
mid±10/±50/±200 tick markouts, adverse flag, inventory before/after,
realized PnL (FIFO).

Input: /tmp/prosperity_logs/<subid>/<logid>.log
Output: scripts/r2_postmortem/ledger_<subid>.csv plus consolidated ledger.csv
"""

from __future__ import annotations

import json
from collections import deque
from pathlib import Path

LOGS = {
    "296317": "/tmp/prosperity_logs/296317/305226.log",   # iter12 run 1
    "296379": "/tmp/prosperity_logs/296379/305289.log",   # iter12 run 2
    "296878": "/tmp/prosperity_logs/296878/305790.log",   # iter13 (CF3)
    "297226": "/tmp/prosperity_logs/297226/306138.log",   # iter14
}

OUT = Path("/Users/svelaga/Documents/IMC Prosperity/chrispyroberts-imc-prosperity-4/scripts/r2_postmortem")


def parse_mids(log: dict) -> dict[tuple[int, str], float]:
    """Map (timestamp, product) -> mid_price from activitiesLog."""
    out = {}
    for ln in log["activitiesLog"].strip().split("\n")[1:]:
        c = ln.split(";")
        if len(c) < 17:
            continue
        try:
            ts = int(c[1])
            prod = c[2]
            mid = float(c[15])
            if mid > 0:
                out[(ts, prod)] = mid
        except ValueError:
            continue
    return out


def markout(mids: dict, product: str, ts: int, n_ticks: int) -> float:
    """Return mid at ts + n_ticks*100 for the given product, or NaN."""
    target_ts = ts + n_ticks * 100
    while target_ts <= 999900:
        if (target_ts, product) in mids:
            return mids[(target_ts, product)]
        target_ts += 100
    return float("nan")


def build_ledger(sub_id: str, log_path: str) -> list[dict]:
    log = json.load(open(log_path))
    mids = parse_mids(log)
    trades = log.get("tradeHistory") or []
    own = [t for t in trades if "SUBMISSION" in (t.get("buyer", ""), t.get("seller", ""))]
    own.sort(key=lambda t: t["timestamp"])

    # FIFO ledgers per product
    fifo = {"ASH_COATED_OSMIUM": deque(), "INTARIAN_PEPPER_ROOT": deque()}
    position = {"ASH_COATED_OSMIUM": 0, "INTARIAN_PEPPER_ROOT": 0}

    rows = []
    for t in own:
        ts = t["timestamp"]
        prod = t["symbol"]
        price = float(t["price"])
        size = int(t["quantity"])
        is_buy = t.get("buyer") == "SUBMISSION"
        side = "BUY" if is_buy else "SELL"
        mid_now = mids.get((ts, prod))
        if mid_now is None:
            mid_now = float("nan")
        edge = (mid_now - price) if is_buy else (price - mid_now)

        # Markouts
        m_plus_10 = markout(mids, prod, ts, 10)
        m_plus_50 = markout(mids, prod, ts, 50)
        m_plus_200 = markout(mids, prod, ts, 200)

        # Adverse: price moved against us within 50 ticks
        adverse_N2_M10 = 0
        if not (m_plus_10 != m_plus_10):
            move = (m_plus_10 - mid_now) if is_buy else (mid_now - m_plus_10)
            # Adverse: the market moved AGAINST our direction
            if is_buy and m_plus_10 < mid_now - 2:
                adverse_N2_M10 = 1
            elif not is_buy and m_plus_10 > mid_now + 2:
                adverse_N2_M10 = 1
        adverse_N4_M50 = 0
        if not (m_plus_50 != m_plus_50):
            if is_buy and m_plus_50 < mid_now - 4:
                adverse_N4_M50 = 1
            elif not is_buy and m_plus_50 > mid_now + 4:
                adverse_N4_M50 = 1

        # FIFO realized PnL
        inv_before = position[prod]
        realized = 0.0
        remaining = size
        q = fifo[prod]
        if is_buy:
            # Closing against earlier sells (negative lots)
            while remaining > 0 and q and q[0][0] < 0:
                lot_sz, lot_px = q[0]
                take = min(remaining, -lot_sz)
                realized += (lot_px - price) * take  # sold at lot_px, bought back at price
                remaining -= take
                lot_sz += take
                if lot_sz == 0:
                    q.popleft()
                else:
                    q[0] = (lot_sz, lot_px)
            if remaining > 0:
                q.append((remaining, price))
            position[prod] += size
        else:
            # Closing against earlier buys (positive lots)
            while remaining > 0 and q and q[0][0] > 0:
                lot_sz, lot_px = q[0]
                take = min(remaining, lot_sz)
                realized += (price - lot_px) * take  # bought at lot_px, sold at price
                remaining -= take
                lot_sz -= take
                if lot_sz == 0:
                    q.popleft()
                else:
                    q[0] = (lot_sz, lot_px)
            if remaining > 0:
                q.append((-remaining, price))
            position[prod] -= size

        rows.append({
            "sub": sub_id,
            "timestamp": ts,
            "product": prod,
            "side": side,
            "size": size,
            "price": price,
            "mid_at_fill": mid_now,
            "edge_at_fill": edge,
            "mid_plus_10": m_plus_10,
            "mid_plus_50": m_plus_50,
            "mid_plus_200": m_plus_200,
            "adverse_N2_M10": adverse_N2_M10,
            "adverse_N4_M50": adverse_N4_M50,
            "realized_pnl_fifo": realized,
            "inv_before": inv_before,
            "inv_after": position[prod],
        })
    return rows


def main():
    all_rows = []
    for sub, path in LOGS.items():
        rows = build_ledger(sub, path)
        all_rows.extend(rows)
        # Per-submission CSV
        csv_path = OUT / f"ledger_{sub}.csv"
        if rows:
            cols = list(rows[0].keys())
            with csv_path.open("w") as f:
                f.write(",".join(cols) + "\n")
                for r in rows:
                    f.write(",".join(str(r[c]) for c in cols) + "\n")
            print(f"{sub}: {len(rows)} fills -> {csv_path}")

    # Consolidated
    cat_path = OUT / "ledger_all.csv"
    if all_rows:
        cols = list(all_rows[0].keys())
        with cat_path.open("w") as f:
            f.write(",".join(cols) + "\n")
            for r in all_rows:
                f.write(",".join(str(r[c]) for c in cols) + "\n")
        print(f"All: {len(all_rows)} fills -> {cat_path}")

    # Summary statistics
    import collections
    print("\n=== Summary ===")
    by_sub_prod = collections.defaultdict(lambda: {"n": 0, "buy": 0, "sell": 0, "qty_buy": 0, "qty_sell": 0, "realized": 0.0, "adverse_N2_M10": 0, "adverse_N4_M50": 0})
    for r in all_rows:
        key = (r["sub"], r["product"])
        b = by_sub_prod[key]
        b["n"] += 1
        if r["side"] == "BUY":
            b["buy"] += 1
            b["qty_buy"] += r["size"]
        else:
            b["sell"] += 1
            b["qty_sell"] += r["size"]
        b["realized"] += r["realized_pnl_fifo"]
        b["adverse_N2_M10"] += r["adverse_N2_M10"]
        b["adverse_N4_M50"] += r["adverse_N4_M50"]
    for (sub, prod), b in sorted(by_sub_prod.items()):
        print(f"{sub} {prod:22s}: n={b['n']:3d} b/s={b['buy']}/{b['sell']}  qty_b/s={b['qty_buy']}/{b['qty_sell']}  realized={b['realized']:+.2f}  adv10={b['adverse_N2_M10']:3d}  adv50={b['adverse_N4_M50']:3d}")


if __name__ == "__main__":
    main()
