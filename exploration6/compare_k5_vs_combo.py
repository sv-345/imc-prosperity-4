"""Compare trajectories of sub 329290 (k5 sample 1) vs 332767 (iter28_combo).

For each 10K-ts window and each named window, show:
  - k5 PnL
  - combo PnL
  - delta
This identifies where combo gains or loses vs k5.
"""
import json
from collections import defaultdict
from pathlib import Path


def parse(log_path):
    raw = json.loads(Path(log_path).read_text())
    lines = raw["activitiesLog"].strip().split("\n")[1:]
    per_prod = defaultdict(dict)  # prod -> ts -> pnl
    for ln in lines:
        f = ln.split(";")
        try:
            ts = int(f[1]); prod = f[2]; pnl = float(f[16]) if f[16] else 0.0
            per_prod[prod][ts] = pnl
        except (ValueError, IndexError):
            pass
    return per_prod


k5 = parse("/tmp/prosperity_logs/329290/338324.log")
cb = parse("/tmp/prosperity_logs/332767/341816.log")

ts_set = sorted(set(t for p in k5.values() for t in p.keys()) |
                 set(t for p in cb.values() for t in p.keys()))


def total_at(snap, ts):
    return sum(snap[p].get(ts, 0) for p in snap)


print("=== 10K-ts window: k5 gain | combo gain | Δ ===")
w_k5 = defaultdict(float); w_cb = defaultdict(float)
prev_k = prev_c = 0
for ts in ts_set:
    tk = total_at(k5, ts); tc = total_at(cb, ts)
    w = ts // 10000
    w_k5[w] = tk; w_cb[w] = tc
# Compute per-window delta (gain during the window)
prev_k = prev_c = 0
for w in sorted(w_k5):
    gk = w_k5[w] - prev_k; gc = w_cb[w] - prev_c
    print(f"  [{w*10000:>6},{(w+1)*10000:>6}): k5=${gk:>7.2f}  combo=${gc:>7.2f}  Δ=${gc-gk:>+7.2f}")
    prev_k = w_k5[w]; prev_c = w_cb[w]

# Named windows
print("\n=== Named windows (per-product) ===")
for name, lo, hi in [("w1", 34300, 48100), ("w2", 76100, 90100)]:
    for prod in ("ASH_COATED_OSMIUM", "INTARIAN_PEPPER_ROOT"):
        # find pnl at lo and hi (nearest existing ts)
        k5_seq = k5[prod]; cb_seq = cb[prod]
        lo_ts = max(t for t in k5_seq if t <= lo)
        hi_ts = min(t for t in k5_seq if t >= hi)
        gk = k5_seq.get(hi_ts, 0) - k5_seq.get(lo_ts, 0)
        gc = cb_seq.get(hi_ts, 0) - cb_seq.get(lo_ts, 0)
        print(f"  {name} {prod:22s}: k5=${gk:>7.2f}  combo=${gc:>7.2f}  Δ=${gc-gk:>+7.2f}")

# overall delta
tk = total_at(k5, max(ts_set)); tc = total_at(cb, max(ts_set))
print(f"\nOverall: k5=${tk:.2f}  combo=${tc:.2f}  Δ=${tc-tk:+.2f}")
