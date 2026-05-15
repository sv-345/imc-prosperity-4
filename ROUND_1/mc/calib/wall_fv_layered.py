"""Add extra sell levels deeper than main quote — does it catch big spikes?"""
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
print(f"base (wall_fv+ema5+e10): live={b_li:.0f}  tr_avg={sum(b_tr)/3:.0f}")
print()

print("# Extra sell level (additional qty at deeper price)")
for qty, extra in [(10, 8), (20, 8), (10, 16), (20, 16), (40, 16), (40, 24)]:
    osm = {**base, "extra_sell_levels": [(qty, extra)]}
    li, tr = score(osm)
    dli = li - b_li
    dtr = sum(tr)/3 - sum(b_tr)/3
    print(f"  extra_sell qty={qty} extra={extra}: "
          f"live={li:.0f} (Δ{dli:+4.0f})  tr_avg={sum(tr)/3:.0f} (Δ{dtr:+5.0f})")

print("\n# Extra buy level")
for qty, extra in [(10, 8), (20, 8), (10, 16), (20, 16), (40, 16)]:
    osm = {**base, "extra_buy_levels": [(qty, extra)]}
    li, tr = score(osm)
    dli = li - b_li
    dtr = sum(tr)/3 - sum(b_tr)/3
    print(f"  extra_buy qty={qty} extra={extra}: "
          f"live={li:.0f} (Δ{dli:+4.0f})  tr_avg={sum(tr)/3:.0f} (Δ{dtr:+5.0f})")

print("\n# Symmetric extra levels")
for qty, extra in [(10, 8), (20, 16)]:
    osm = {**base,
           "extra_sell_levels": [(qty, extra)],
           "extra_buy_levels": [(qty, extra)]}
    li, tr = score(osm)
    dli = li - b_li
    dtr = sum(tr)/3 - sum(b_tr)/3
    print(f"  symmetric qty={qty} extra={extra}: "
          f"live={li:.0f} (Δ{dli:+4.0f})  tr_avg={sum(tr)/3:.0f} (Δ{dtr:+5.0f})")
