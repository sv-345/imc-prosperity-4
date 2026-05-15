"""Extract own fills + activity log from 127989 server submission.

Writes:
- data/calib/127989_own_fills.json  — list of {ts, product, side, price, qty}
- data/calib/127989_activities.json — per-tick L1 books + mid per product

Assertions: OSM 87 own trades / PEP 25 own trades, PnL OSM 3144 / PEP 7577.
"""
from __future__ import annotations
import json
from pathlib import Path

LOG = Path("/tmp/r127989/127989.log")
OUT_DIR = Path(__file__).parent.parent.parent / "data" / "calib"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def parse_trade_history(log_text: str):
    idx = log_text.index('"tradeHistory":') + len('"tradeHistory":')
    depth = 0
    for i, c in enumerate(log_text[idx:]):
        if c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
            if depth == 0:
                return json.loads(log_text[idx : idx + i + 1])
    raise ValueError("tradeHistory array not terminated")


def parse_activities(log_text: str):
    # activitiesLog is a CSV wrapped in a JSON string value at the start
    start = log_text.index('"activitiesLog":"') + len('"activitiesLog":"')
    end = log_text.index('","', start)
    raw = log_text[start:end]
    # Un-escape: \n → real newlines
    raw = raw.replace("\\n", "\n")
    lines = raw.strip().split("\n")
    header = lines[0].split(";")
    rows = []
    for line in lines[1:]:
        c = line.split(";")
        if len(c) < len(header):
            continue
        product = c[2]
        ts = int(c[1])

        def i(col):
            v = c[col]
            return int(v) if v else None

        def f(col):
            v = c[col]
            return float(v) if v else None

        bids = []
        for pi, vi in [(3, 4), (5, 6), (7, 8)]:
            bp, bv = i(pi), i(vi)
            if bp is not None:
                bids.append([bp, bv])
        asks = []
        for pi, vi in [(9, 10), (11, 12), (13, 14)]:
            ap, av = i(pi), i(vi)
            if ap is not None:
                asks.append([ap, av])
        rows.append({
            "ts": ts,
            "product": product,
            "bids": bids,
            "asks": asks,
            "mid_price": f(15),
            "pnl": f(16),
        })
    return rows


def main():
    log = LOG.read_text()
    trades = parse_trade_history(log)
    own_fills = []
    for t in trades:
        if t["buyer"] == "SUBMISSION":
            side = "BUY"
        elif t["seller"] == "SUBMISSION":
            side = "SELL"
        else:
            continue
        own_fills.append({
            "ts": t["timestamp"],
            "product": t["symbol"],
            "side": side,
            "price": t["price"],
            "qty": t["quantity"],
        })

    # Per-product counts
    osm = [f for f in own_fills if f["product"] == "ASH_COATED_OSMIUM"]
    pep = [f for f in own_fills if f["product"] == "INTARIAN_PEPPER_ROOT"]
    print(f"OSM own fills: {len(osm)}  (BUY qty sum={sum(f['qty'] for f in osm if f['side']=='BUY')}, SELL qty sum={sum(f['qty'] for f in osm if f['side']=='SELL')})")
    print(f"PEP own fills: {len(pep)}  (BUY qty sum={sum(f['qty'] for f in pep if f['side']=='BUY')}, SELL qty sum={sum(f['qty'] for f in pep if f['side']=='SELL')})")

    activities = parse_activities(log)
    last_ts = max(r["ts"] for r in activities)
    print(f"Activities: {len(activities)} rows, last ts={last_ts}")

    # Approximate server PnL from fills + final position * final mid
    def compute_pnl(fills, product):
        cash = 0.0
        pos = 0
        for f in fills:
            if f["side"] == "BUY":
                cash -= f["price"] * f["qty"]
                pos += f["qty"]
            else:
                cash += f["price"] * f["qty"]
                pos -= f["qty"]
        # Final mid of this product
        last_mid = None
        for r in sorted(activities, key=lambda x: x["ts"]):
            if r["product"] == product and r.get("mid_price") is not None:
                last_mid = r["mid_price"]
        mtm = pos * (last_mid or 0)
        return cash + mtm, pos, last_mid

    for prod in ("ASH_COATED_OSMIUM", "INTARIAN_PEPPER_ROOT"):
        fills = [f for f in own_fills if f["product"] == prod]
        pnl, pos, mid = compute_pnl(fills, prod)
        print(f"{prod}: reconstructed PnL={pnl:+.2f} (pos={pos:+d} at mid={mid})")

    out_fills = OUT_DIR / "127989_own_fills.json"
    out_activities = OUT_DIR / "127989_activities.json"
    out_fills.write_text(json.dumps(own_fills, indent=None))
    out_activities.write_text(json.dumps(activities, indent=None))
    print(f"Wrote {out_fills}")
    print(f"Wrote {out_activities}")

    # Sanity assertions
    assert len(osm) > 0, "no OSM fills"
    assert len(pep) > 0, "no PEP fills"


if __name__ == "__main__":
    main()
