"""Compare iter26_c4_best top sample (316247, $9,890) vs iter27_k5 sample 1 (329290, $9,788)."""
import json
from collections import defaultdict
from pathlib import Path


def parse(log_path):
    raw = json.loads(Path(log_path).read_text())
    lines = raw["activitiesLog"].strip().split("\n")[1:]
    per_prod = defaultdict(dict)
    for ln in lines:
        f = ln.split(";")
        try:
            ts = int(f[1]); prod = f[2]; pnl = float(f[16]) if f[16] else 0.0
            per_prod[prod][ts] = pnl
        except (ValueError, IndexError):
            pass
    return per_prod


# find c4 log
import os
c4_dir = Path("/tmp/prosperity_logs/316247")
if not c4_dir.exists():
    # download it
    os.system(f'python3 "<repo>/TUTORIAL_ROUND_1/tools/prosperity_api.py" logs --id 316247')
    c4_dir = Path("/tmp/prosperity_logs/316247")

c4_log = next(c4_dir.glob("*.log"))
k5_log = "/tmp/prosperity_logs/329290/338324.log"

c4 = parse(c4_log)
k5 = parse(k5_log)

ts_set = sorted(set(t for p in c4.values() for t in p.keys()) &
                 set(t for p in k5.values() for t in p.keys()))


def total(snap, ts):
    return sum(snap[p].get(ts, 0) for p in snap)


print("=== per-product totals ===")
last = max(ts_set)
for prod in ("ASH_COATED_OSMIUM", "INTARIAN_PEPPER_ROOT"):
    c = c4[prod].get(last, 0); k = k5[prod].get(last, 0)
    print(f"  {prod:22s}: c4=${c:>8.2f}  k5=${k:>8.2f}  Δ(c4-k5)={c-k:+7.2f}")
print(f"  TOTAL: c4=${total(c4,last):.2f}  k5=${total(k5,last):.2f}  Δ={total(c4,last)-total(k5,last):+.2f}")

print("\n=== 10K-ts window (c4 gain | k5 gain | c4-k5 Δ) ===")
prev_c = prev_k = 0
for w in range(10):
    lo = w * 10000; hi = (w + 1) * 10000
    # use last ts in window
    ts_in = [t for t in ts_set if lo <= t < hi]
    if not ts_in: continue
    end = max(ts_in)
    gc = total(c4, end) - prev_c; gk = total(k5, end) - prev_k
    print(f"  [{lo:>6},{hi:>6}): c4=${gc:>7.2f}  k5=${gk:>7.2f}  Δ=${gc-gk:>+7.2f}")
    prev_c = total(c4, end); prev_k = total(k5, end)

# named windows
print("\n=== named windows per product ===")
for name, lo, hi in [("w1", 34300, 48100), ("w2", 76100, 90100)]:
    for prod in c4:
        lo_ts = max(t for t in c4[prod] if t <= lo)
        hi_ts = min(t for t in c4[prod] if t >= hi)
        gc = c4[prod].get(hi_ts, 0) - c4[prod].get(lo_ts, 0)
        gk = k5[prod].get(hi_ts, 0) - k5[prod].get(lo_ts, 0)
        print(f"  {name} {prod:22s}: c4=${gc:>7.2f}  k5=${gk:>7.2f}  Δ=${gc-gk:>+7.2f}")
