"""Analyze iter30 (sub 332955) own-trades to find what was captured vs missed.

For each of our fills:
- Phase-2 (book take) vs Phase-3 (tape match) classification from book state
- Per-product, per-window distribution
- Fill edge vs mid

Additionally: scan activitiesLog for book states at our quote timestamps to
estimate what the trader saw and what it might have missed.
"""
import json
from collections import defaultdict
from pathlib import Path


raw = json.loads(Path("/tmp/prosperity_logs/332955/342005.log").read_text())

# Parse activities into book-state snapshot per (ts, product)
act = raw["activitiesLog"].strip().split("\n")[1:]
book = defaultdict(dict)  # ts -> product -> {bids, asks, mid}
for ln in act:
    f = ln.split(";")
    try:
        ts = int(f[1]); prod = f[2]
        bids = [(int(f[3]), int(f[4])) if f[3] else None,
                (int(f[5]), int(f[6])) if f[5] else None,
                (int(f[7]), int(f[8])) if f[7] else None]
        asks = [(int(f[9]), int(f[10])) if f[9] else None,
                (int(f[11]), int(f[12])) if f[11] else None,
                (int(f[13]), int(f[14])) if f[13] else None]
        mid = float(f[15]) if f[15] else None
        book[ts][prod] = {
            "bids": [b for b in bids if b is not None],
            "asks": [a for a in asks if a is not None],
            "mid": mid,
        }
    except (ValueError, IndexError):
        continue

# Parse trade history
trades = raw["tradeHistory"]
print(f"Own trades: {len(trades)}")

# Classify each trade
fills = []
for t in trades:
    ts = t["timestamp"]; prod = t["symbol"]; price = int(t["price"])
    qty = t["quantity"]
    side = "BUY" if t["buyer"] == "SUBMISSION" else "SELL"
    b = book.get(ts, {}).get(prod)
    phase = "unknown"
    if b:
        if side == "BUY":
            # Phase 2 = our buy crossed book ask at snapshot
            best_ask_visible = min((a[0] for a in b["asks"]), default=None)
            phase = "P2_BOOK" if (best_ask_visible is not None and price >= best_ask_visible) else "P3_TAPE"
        else:
            best_bid_visible = max((a[0] for a in b["bids"]), default=None)
            phase = "P2_BOOK" if (best_bid_visible is not None and price <= best_bid_visible) else "P3_TAPE"
    fills.append({**t, "phase": phase, "side": side, "mid": b["mid"] if b else None})


# Summarize
print("\n=== Fill phase x product x side ===")
per = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
for f in fills:
    per[f["symbol"]][f["phase"]][f["side"]] += f["quantity"]
for prod in per:
    for phase in per[prod]:
        for side, q in per[prod][phase].items():
            print(f"  {prod:22s} {phase:8s} {side}: {q}")

# Per-window fill distribution
print("\n=== Fills inside named windows (per-product, per-side) ===")
W = [("w1", 34300, 48100), ("w2", 76100, 90100)]
for name, lo, hi in W:
    cnt = defaultdict(lambda: defaultdict(int))
    for f in fills:
        if lo <= f["timestamp"] <= hi:
            cnt[f["symbol"]][f["side"]] += f["quantity"]
    print(f"  {name}: {dict(cnt)}")

# Fill edge: price vs mid
print("\n=== Edge distribution (our_price - mid, for each fill) ===")
edge_hist = defaultdict(lambda: defaultdict(list))  # prod -> side -> [edge]
for f in fills:
    if f["mid"] is None: continue
    edge = f["price"] - f["mid"] if f["side"] == "SELL" else f["mid"] - f["price"]
    edge_hist[f["symbol"]][f["side"]].append(edge)
for prod in edge_hist:
    for side in edge_hist[prod]:
        arr = edge_hist[prod][side]
        if not arr: continue
        avg = sum(arr) / len(arr)
        print(f"  {prod} {side}: n={len(arr)}  avg_edge={avg:+.2f}  "
              f"min={min(arr):+.1f}  max={max(arr):+.1f}")

# Tick-level: which ticks had fills? What's the density?
ts_with_fill = defaultdict(set)
for f in fills:
    ts_with_fill[f["symbol"]].add(f["timestamp"])
for prod in ts_with_fill:
    print(f"  {prod}: fills at {len(ts_with_fill[prod])} unique timestamps out of 1000")

# Look at the steepest window: ts 86000-89000
print("\n=== Steepest region (ts 86K-89K) detail ===")
for f in fills:
    if 86000 <= f["timestamp"] <= 89000:
        b = book.get(f["timestamp"], {}).get(f["symbol"], {})
        print(f"  ts={f['timestamp']} {f['symbol']:22s} {f['side']:4s} "
              f"qty={f['quantity']:>2} px={int(f['price']):>5} mid={b.get('mid')} "
              f"phase={f['phase']}")

# Save full fill log
out = Path(__file__).parent / "iter30_fills.json"
json.dump(fills, open(out, "w"), indent=2, default=str)
