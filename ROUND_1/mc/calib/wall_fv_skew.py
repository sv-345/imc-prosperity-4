"""Position-skewed edge with wall_fv."""
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
print(f"base (wall_fv+ema5+e10): live={b_li:.0f} tr_avg={sum(b_tr)/3:.0f}")
print()

print("# skew_per_pos sweep")
for s in [0.05, 0.1, 0.15, 0.2, 0.3, 0.5]:
    osm = {**base, "skew_per_pos": s}
    li, tr = score(osm)
    dli = li - b_li
    dtr = sum(tr)/3 - sum(b_tr)/3
    print(f"  skew={s}: live={li:.0f} (Δ{dli:+4.0f})  tr_avg={sum(tr)/3:.0f} (Δ{dtr:+5.0f})")

print("\n# skew_cap variants (skew=0.1 fixed)")
for c in [2, 4, 6, 8, 12]:
    osm = {**base, "skew_per_pos": 0.1, "skew_cap": c}
    li, tr = score(osm)
    dli = li - b_li
    dtr = sum(tr)/3 - sum(b_tr)/3
    print(f"  cap={c}: live={li:.0f} (Δ{dli:+4.0f})  tr_avg={sum(tr)/3:.0f} (Δ{dtr:+5.0f})")
