"""For each of my fills in v82-family submissions, was there a bot-take
on the ADVERSE side in the previous few ticks?

Adverse pattern:
  - My BUY fill while recent bot-bot trades were sell-takers (price falling)
  - My SELL fill while recent bot-bot trades were buy-takers (price rising)

Quantify the $ impact of fills that coincided with signal-adverse take flow.
"""

import csv
import json
import math
from collections import defaultdict
from pathlib import Path

LEDGER = Path("<repo>/chrispyroberts-imc-prosperity-4/scripts/r2_postmortem/ledger_all.csv")
LOGS = {
    "296317": "/tmp/prosperity_logs/296317/305226.log",
    "296379": "/tmp/prosperity_logs/296379/305289.log",
    "296878": "/tmp/prosperity_logs/296878/305790.log",
    "297226": "/tmp/prosperity_logs/297226/306138.log",
}


def classify_trade(t, book):
    buyer = (t.get("buyer") or "")
    seller = (t.get("seller") or "")
    if "SUBMISSION" in buyer or "SUBMISSION" in seller:
        return None
    if not book:
        return None
    price = float(t["price"])
    if price >= book["ap1"]:
        return {"side": "buy", "qty": int(t["quantity"])}
    elif price <= book["bp1"]:
        return {"side": "sell", "qty": int(t["quantity"])}
    return None


def load_books(log_path):
    log = json.load(open(log_path))
    books = {}
    for ln in log["activitiesLog"].strip().split("\n")[1:]:
        c = ln.split(";")
        if len(c) < 17: continue
        try:
            ts = int(c[1]); prod = c[2]
            bp1 = int(c[3]) if c[3] else 0
            ap1 = int(c[9]) if c[9] else 0
            mid = float(c[15])
            if bp1 and ap1 and mid > 0:
                books[(ts, prod)] = {"bp1": bp1, "ap1": ap1, "mid": mid}
        except ValueError:
            pass
    trades = log.get("tradeHistory") or []
    take_map = defaultdict(list)  # (ts, prod) -> list of classified trades
    for t in trades:
        ts = t.get("timestamp", 0)
        prod = t.get("symbol", "")
        book = books.get((ts, prod))
        cls = classify_trade(t, book)
        if cls:
            take_map[(ts, prod)].append(cls)
    return books, take_map


def net_take_in_window(take_map, product, end_ts, lookback_ticks):
    """Sum net takes (buy qty - sell qty) in ticks (end_ts - lookback_ticks*100, end_ts]."""
    net = 0
    for back in range(1, lookback_ticks + 1):
        ts = end_ts - back * 100
        for t in take_map.get((ts, product), []):
            if t["side"] == "buy": net += t["qty"]
            else: net -= t["qty"]
    return net


def main():
    # Load ledger of own fills
    rows = []
    with LEDGER.open() as f:
        for r in csv.DictReader(f):
            for k in ("timestamp", "size"):
                r[k] = int(r[k])
            for k in ("price", "mid_at_fill", "edge_at_fill", "mid_plus_50"):
                try: r[k] = float(r[k])
                except: r[k] = float("nan")
            rows.append(r)

    # Load per-submission take maps
    take_maps = {}
    for sub, path in LOGS.items():
        _, tm = load_books(path)
        take_maps[sub] = tm

    # For each own fill, look at net bot-takes in previous K ticks
    print("=== Adverse-take-signal fill analysis ===")
    print("For each own fill, classify the signal state (net bot-take over prev 3 ticks):")
    print("  BUY fills are adverse when preceded by net sell-takers (signal says mid dropping)")
    print("  SELL fills are adverse when preceded by net buy-takers (signal says mid rising)\n")

    for product in ["ASH_COATED_OSMIUM", "INTARIAN_PEPPER_ROOT"]:
        prows = [r for r in rows if r["product"] == product]
        # Bucket by (side, prev take signal)
        buckets = defaultdict(lambda: {"n": 0, "qty": 0, "mk50_signed": 0.0})
        for r in prows:
            sub = r["sub"]
            tm = take_maps.get(sub, {})
            prev_net = net_take_in_window(tm, product, r["timestamp"], 3)
            side = r["side"]
            if prev_net > 2: sig = "+sig"
            elif prev_net < -2: sig = "-sig"
            else: sig = "0sig"
            # Adverse alignment detection
            if side == "BUY" and sig == "-sig": align = "ADVERSE"
            elif side == "SELL" and sig == "+sig": align = "ADVERSE"
            elif side == "BUY" and sig == "+sig": align = "FAVOR"
            elif side == "SELL" and sig == "-sig": align = "FAVOR"
            else: align = "neutral"
            # pnl50 signed
            mk50 = (r["mid_plus_50"] - r["mid_at_fill"]) if side == "BUY" else (r["mid_at_fill"] - r["mid_plus_50"])
            if math.isnan(mk50): mk50 = 0.0
            b = buckets[(side, sig, align)]
            b["n"] += 1
            b["qty"] += r["size"]
            b["mk50_signed"] += mk50 * r["size"]
        print(f"\n{product}:")
        print(f"  {'side':8s} {'sig':5s} {'align':8s} {'n':>4s} {'qty':>5s} {'Σ pnl50':>10s} {'pnl/unit':>10s}")
        for (side, sig, align), b in sorted(buckets.items()):
            per = b["mk50_signed"] / b["qty"] if b["qty"] else 0
            print(f"  {side:8s} {sig:5s} {align:8s} {b['n']:4d} {b['qty']:5d} {b['mk50_signed']:+10.1f} {per:+10.2f}")

        # "If we skipped all ADVERSE fills"
        adverse_pnl = sum(
            ((r["mid_plus_50"] - r["mid_at_fill"]) if r["side"] == "BUY" else (r["mid_at_fill"] - r["mid_plus_50"])) * r["size"]
            for r in prows
            if (r["side"] == "BUY" and net_take_in_window(take_maps.get(r["sub"], {}), product, r["timestamp"], 3) < -2)
            or (r["side"] == "SELL" and net_take_in_window(take_maps.get(r["sub"], {}), product, r["timestamp"], 3) > 2)
            if not math.isnan(r["mid_plus_50"])
        )
        n_subs = len(set(r["sub"] for r in rows))
        print(f"  Σ adverse fill pnl50: {adverse_pnl:+.0f} ({adverse_pnl/n_subs:+.0f}/slice)")


if __name__ == "__main__":
    main()
