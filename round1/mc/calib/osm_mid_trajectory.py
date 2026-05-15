"""Check OSM mid-price trajectory for mean-reversion alpha.

If mid deviates from FV=10000 consistently, we could lean into the trade.
"""
from __future__ import annotations
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from server_book_replay import load_ticks


def mid_stats(product, session="127989"):
    ticks = load_ticks(product, session=session)
    mids = []
    for r in ticks:
        bb = max(int(p) for p, _ in r["bids"]) if r["bids"] else None
        ba = min(int(p) for p, _ in r["asks"]) if r["asks"] else None
        if bb and ba:
            mids.append((r["ts"], (bb + ba) / 2))
    return mids


print("=== OSM 127989 mid trajectory ===")
mids = mid_stats("ASH_COATED_OSMIUM")
print(f"  samples: {len(mids)}")
vals = [m for _, m in mids]
print(f"  mid min={min(vals):.1f} max={max(vals):.1f}")
c = Counter(int(v) for v in vals)
for p in sorted(c):
    print(f"    mid={p}: {c[p]}")

# Deviation distribution
devs = [v - 10000 for v in vals]
print(f"  deviation from 10000: mean={sum(devs)/len(devs):+.2f}  min={min(devs):+.1f}  max={max(devs):+.1f}")

# Walk the mid: does it trend or mean-revert?
from collections import Counter
transitions = Counter()
prev = vals[0]
for v in vals[1:]:
    if v > prev:
        transitions["up"] += 1
    elif v < prev:
        transitions["down"] += 1
    else:
        transitions["flat"] += 1
    prev = v
print(f"  transitions: up={transitions['up']} down={transitions['down']} flat={transitions['flat']}")
