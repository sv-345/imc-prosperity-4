"""OSM is pinned at pos=+80 for 84% of session. Sell fills rare (28 BUY-takers).
Hypothesis: widening sell_edge captures more per rare sell fill, at cost of fewer fills.
Test asymmetric: keep buy_edge=12 (rarely active when capped), scan sell_edge.
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from parametric_trader import make_trader
from server_book_replay_v2 import run_server_session_v2
from training_book_replay_v2 import run_training_session_v2


def score_osm(osm):
    t = make_trader(osm=osm)
    li = run_server_session_v2(t, "ASH_COATED_OSMIUM").pnl
    tr = []
    for d in ["-2", "-1", "0"]:
        t = make_trader(osm=osm)
        tr.append(run_training_session_v2(t, "ASH_COATED_OSMIUM", d).pnl)
    return li, tr


# Baseline: both edges default (12)
b_li, b_tr = score_osm({})
print(f"baseline (e12): live={b_li:.0f}  tr={[int(x) for x in b_tr]}  avg={sum(b_tr)/3:.0f}")

# Current best: symmetric e22
li, tr = score_osm({"quote_edge": 22})
print(f"symmetric e22:  live={li:.0f} (Δ{li-b_li:+5.0f})  "
      f"tr={[int(x) for x in tr]}  avg={sum(tr)/3:.0f} (Δ{sum(tr)/3-sum(b_tr)/3:+5.0f})")

# Asymmetric: tight buy, wide sell
print("\n# Asymmetric (buy_edge=12, varying sell_edge)")
for se in [18, 22, 26, 30, 35, 40, 50]:
    p = {"buy_edge": 12, "sell_edge": se}
    li, tr = score_osm(p)
    print(f"be=12 se={se:2d}: live={li:5.0f} (Δ{li-b_li:+5.0f})  "
          f"tr_avg={sum(tr)/3:6.0f} (Δ{sum(tr)/3-sum(b_tr)/3:+5.0f})  "
          f"tr={[int(x) for x in tr]}")

# Asymmetric: wider buy too
print("\n# Widening both (buy_edge, sell_edge)")
for be in [12, 16, 22]:
    for se in [22, 30, 40]:
        p = {"buy_edge": be, "sell_edge": se}
        li, tr = score_osm(p)
        print(f"be={be:2d} se={se:2d}: live={li:5.0f} (Δ{li-b_li:+5.0f})  "
              f"tr_avg={sum(tr)/3:6.0f} (Δ{sum(tr)/3-sum(b_tr)/3:+5.0f})")
