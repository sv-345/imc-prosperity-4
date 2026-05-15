"""With accurate wall_fv, does a tighter edge help (more fills)?"""
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


base = {"use_wall_fv": True, "wall_fv_ema_alpha": 0.5}
for e in [6, 8, 10, 12, 14, 16, 18, 22, 26, 30]:
    osm = {**base, "quote_edge": e}
    li, tr = score(osm)
    print(f"edge={e:2d}: live={li:.0f}  tr_avg={sum(tr)/3:.0f}  tr={[int(x) for x in tr]}")
