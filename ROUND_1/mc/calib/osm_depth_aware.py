"""Test adaptive edge based on book depth/tightness.

Hypothesis: when book spread is tight (ba-bb small), book is competitive → go deeper.
When spread wide, we can stand inside for free → tighter penny-jump.

Check bb/ba distribution first, then test edge adjustments.
"""
from __future__ import annotations
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from server_book_replay import load_ticks


def spread_dist(product, session="127989"):
    ticks = load_ticks(product, session=session)
    spreads = []
    one_sided = 0
    for r in ticks:
        bb = max(int(p) for p, _ in r["bids"]) if r["bids"] else None
        ba = min(int(p) for p, _ in r["asks"]) if r["asks"] else None
        if bb is None or ba is None:
            one_sided += 1
            continue
        spreads.append(ba - bb)
    return spreads, one_sided


print("=== OSM 127989 spread distribution ===")
s, osc = spread_dist("ASH_COATED_OSMIUM")
c = Counter(s)
print(f"  total ticks: {len(s) + osc}, one-sided: {osc}")
for sp in sorted(c):
    print(f"    spread={sp}: {c[sp]} ticks ({100*c[sp]/len(s):.1f}%)")

print("\n=== PEP 127989 spread distribution ===")
s, osc = spread_dist("INTARIAN_PEPPER_ROOT")
c = Counter(s)
print(f"  total ticks: {len(s) + osc}, one-sided: {osc}")
hi = sorted(c.items())
for sp, cnt in hi[:5]:
    print(f"    spread={sp}: {cnt} ticks ({100*cnt/len(s):.1f}%)")
print("  ...")
for sp, cnt in hi[-5:]:
    print(f"    spread={sp}: {cnt} ticks ({100*cnt/len(s):.1f}%)")
