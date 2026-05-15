"""Tune wall detection range."""
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


base = {"use_wall_fv": True, "wall_fv_ema_alpha": 0.5, "quote_edge": 10}
b_li, b_tr = score(base)
print(f"base (10-30): live={b_li}  tr={[int(x) for x in b_tr]}  avg={sum(b_tr)/3:.0f}")

for lo, hi in [(5, 50), (5, 30), (8, 30), (10, 40), (12, 30), (10, 20), (6, 60), (0, 100)]:
    osm = {**base, "wall_spread_lo": lo, "wall_spread_hi": hi}
    li, tr = score(osm)
    dli = li - b_li
    dtr = sum(tr)/3 - sum(b_tr)/3
    print(f"  ({lo},{hi}): live={li:.0f} (Δ{dli:+4.0f})  tr_avg={sum(tr)/3:.0f} (Δ{dtr:+5.0f})")
