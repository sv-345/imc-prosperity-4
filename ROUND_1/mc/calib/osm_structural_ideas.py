"""Test structural OSM ideas given what we know:
- Live 127989: all 99 sell qty from CROSSING bot bids > FV. No taker-fill contribution.
- Training: BUY takers go up to 10026. Wider edge captures real gains.

Ideas:
1. Symmetric sweep: also sweep bids AT FV (not just > FV). Captures bid=10000.
2. Larger min_inside_qty: more qty at penny-jump.
3. Asymmetric min_inside: larger for sell side (since we're capped long).
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from parametric_trader import make_trader
from server_book_replay_v2 import run_server_session_v2
from training_book_replay_v2 import run_training_session_v2


def score(osm):
    t = make_trader(osm=osm)
    li = run_server_session_v2(t, "ASH_COATED_OSMIUM").pnl
    tr = []
    for d in ["-2", "-1", "0"]:
        t = make_trader(osm=osm)
        tr.append(run_training_session_v2(t, "ASH_COATED_OSMIUM", d).pnl)
    return li, tr


b_li, b_tr = score({})
print(f"baseline: live={b_li:.0f}  tr={[int(x) for x in b_tr]}  tr_avg={sum(b_tr)/3:.0f}")

def row(name, osm):
    li, tr = score(osm)
    dli = li - b_li
    dtr = sum(tr)/3 - sum(b_tr)/3
    print(f"{name:>32}  live={li:5.0f} (Δ{dli:+5.0f})  tr_avg={sum(tr)/3:6.0f} (Δ{dtr:+6.0f})  "
          f"tr={[int(x) for x in tr]}")

print("\n# min_inside_qty sweep (baseline edge=12)")
for mi in [5, 15, 30, 50, 80]:
    row(f"min_inside={mi}", {"min_inside_qty": mi})

print("\n# Asymmetric min_inside (more depth on sell when long)")
for sm in [15, 30, 50, 80]:
    row(f"buy_mi=15 sell_mi={sm}", {"buy_min_inside": 15, "sell_min_inside": sm})

print("\n# Edge + min_inside combinations")
for e in [12, 22]:
    for mi in [15, 30, 50]:
        row(f"e={e} mi={mi}", {"quote_edge": e, "min_inside_qty": mi})

print("\n# Asymmetric edge: wider sell, same buy")
for se in [22, 30]:
    for mi in [15, 30, 50]:
        row(f"be=12 se={se} mi={mi}", {"buy_edge": 12, "sell_edge": se, "min_inside_qty": mi})
