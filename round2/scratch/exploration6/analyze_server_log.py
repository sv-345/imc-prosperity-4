"""Extract per-tick PnL trajectory from server log, find steep segments.

Sub 329290 (iter27_k5 sample 1, total $9,788.25).
"""
import json, re
from pathlib import Path
from collections import defaultdict

LOG = Path("/tmp/prosperity_logs/329290/338324.log")
raw = json.loads(LOG.read_text())
act = raw["activitiesLog"]

# parse activities — semicolon CSV
lines = act.strip().split("\n")[1:]  # skip header
rows = []
for ln in lines:
    f = ln.split(";")
    try:
        ts = int(f[1])
        product = f[2]
        mid = float(f[15]) if f[15] else None
        pnl = float(f[16]) if f[16] else 0.0
        rows.append((ts, product, mid, pnl))
    except (ValueError, IndexError):
        continue

# Build per-product PnL trajectory
per_prod = defaultdict(list)  # product -> [(ts, mid, pnl)]
for ts, prod, mid, pnl in rows:
    per_prod[prod].append((ts, mid, pnl))

# Total PnL per tick
ts_sorted = sorted(set(r[0] for r in rows))
total_pnl = []
for ts in ts_sorted:
    p = 0.0
    for prod in per_prod:
        # find entry with this ts
        for t, m, pn in per_prod[prod]:
            if t == ts:
                p += pn
                break
    total_pnl.append((ts, p))

# Per-tick PnL delta (derivative)
deltas = []
for i in range(1, len(total_pnl)):
    ts1, p1 = total_pnl[i]
    ts0, p0 = total_pnl[i-1]
    deltas.append((ts1, p1 - p0))

# Moving average for smoothing
WIN = 50
smooth = []
for i in range(len(deltas)):
    lo = max(0, i - WIN); hi = min(len(deltas), i + WIN)
    avg = sum(d[1] for d in deltas[lo:hi]) / (hi - lo)
    smooth.append((deltas[i][0], avg))

# Top 20 steepest (by smoothed rate)
smooth_sorted = sorted(smooth, key=lambda x: -x[1])
print("=== Top 20 steepest smoothed PnL-rate ticks ===")
for ts, r in smooth_sorted[:20]:
    print(f"  ts={ts:>6} rate={r:>6.2f}/tick")

# Binned by 10K-ts window
print("\n=== PnL delta by 10K-ts window ===")
windows = defaultdict(float)
for ts, d in deltas:
    w = ts // 10000
    windows[w] += d
total = sum(windows.values())
for w in sorted(windows):
    lo = w * 10000; hi = (w + 1) * 10000
    frac = windows[w] / total if total else 0
    print(f"  [{lo:>6},{hi:>6}): ${windows[w]:>7.2f}  ({frac:.1%})")

# Flag: known windows 34.3K-48.1K and 76.1K-90.1K
print("\n=== Named windows ===")
ws = [("w1", 34300, 48100), ("w2", 76100, 90100)]
other_total = total
for name, lo, hi in ws:
    s = sum(d for ts, d in deltas if lo <= ts < hi)
    width_share = (hi - lo) / 100000
    expected = total * width_share
    print(f"  {name} ts[{lo},{hi}): ${s:.2f}   ({s/total:.1%} of total; expected {width_share:.1%}; concentration {s/expected:.2f}x)")
    other_total -= s
other_width = (100000 - (48100-34300) - (90100-76100)) / 100000
print(f"  outside both: ${other_total:.2f}  ({other_total/total:.1%}; expected {other_width:.1%}; concentration {other_total/(total*other_width):.2f}x)")

# Per-product contribution per named window
print("\n=== Per-product contribution in named windows (from activities PnL field) ===")
for name, lo, hi in ws:
    for prod in per_prod:
        seq = per_prod[prod]
        # find pnl at hi and at lo
        pnl_lo = pnl_hi = None
        for t, m, p in seq:
            if t == lo: pnl_lo = p
            if t == hi: pnl_hi = p
        if pnl_lo is not None and pnl_hi is not None:
            print(f"  {name} {prod}: ${pnl_hi - pnl_lo:.2f}  (from ${pnl_lo:.2f} to ${pnl_hi:.2f})")

# Save trajectory csv
out = Path(__file__).parent / "sub329290_trajectory.csv"
with open(out, "w") as f:
    f.write("ts,total_pnl\n")
    for ts, p in total_pnl:
        f.write(f"{ts},{p:.4f}\n")
print(f"\nSaved trajectory → {out}")
