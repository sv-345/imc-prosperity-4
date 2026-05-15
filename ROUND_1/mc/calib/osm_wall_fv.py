"""Test OSM with wall-based FV vs static FV=10000.

OSM mid clusters at 10001 → maybe wall-FV captures this.
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


# Baseline: static FV=10000
b_li, b_tr = score({})
print(f"baseline (static FV=10000): live={b_li:.0f} tr={[int(x) for x in b_tr]} avg={sum(b_tr)/3:.0f}")

# Wall-FV
li, tr = score({"use_wall_fv": True})
print(f"wall_fv only:                live={li:.0f} (Δ{li-b_li:+5.0f}) "
      f"tr_avg={sum(tr)/3:.0f} (Δ{sum(tr)/3-sum(b_tr)/3:+5.0f})")

# Wall-FV + e=22
li, tr = score({"quote_edge": 22, "use_wall_fv": True})
print(f"wall_fv + e22:               live={li:.0f} (Δ{li-b_li:+5.0f}) "
      f"tr_avg={sum(tr)/3:.0f} (Δ{sum(tr)/3-sum(b_tr)/3:+5.0f})")

# Just e=22 (for comparison)
li, tr = score({"quote_edge": 22})
print(f"e22 (ref):                   live={li:.0f} (Δ{li-b_li:+5.0f}) "
      f"tr_avg={sum(tr)/3:.0f} (Δ{sum(tr)/3-sum(b_tr)/3:+5.0f})")

# Mixed: static FV with slight shift — fv=10001
li, tr = score({"fv": 10001})
print(f"fv=10001 (mid-centered):     live={li:.0f} (Δ{li-b_li:+5.0f}) "
      f"tr_avg={sum(tr)/3:.0f} (Δ{sum(tr)/3-sum(b_tr)/3:+5.0f})")

li, tr = score({"fv": 10001, "quote_edge": 22})
print(f"fv=10001 + e22:              live={li:.0f} (Δ{li-b_li:+5.0f}) "
      f"tr_avg={sum(tr)/3:.0f} (Δ{sum(tr)/3-sum(b_tr)/3:+5.0f})")
