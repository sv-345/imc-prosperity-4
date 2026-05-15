"""Test variants of wall_fv: EMA smoothing, mid fallback, last-value fallback."""
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


# Baseline wall_fv (already known: +184 live, +2959 tr/day)
b_li, b_tr = score({"use_wall_fv": True})
print(f"wall_fv (base): live={b_li:.0f}  tr={[int(x) for x in b_tr]}  avg={sum(b_tr)/3:.0f}")
print()

# EMA smoothing
for a in [0.1, 0.3, 0.5, 0.7, 1.0]:
    li, tr = score({"use_wall_fv": True, "wall_fv_ema_alpha": a})
    print(f"ema_alpha={a}: live={li:.0f} (Δ{li-b_li:+5.0f})  "
          f"tr_avg={sum(tr)/3:.0f} (Δ{sum(tr)/3-sum(b_tr)/3:+5.0f})  "
          f"tr={[int(x) for x in tr]}")

print()

# Mid fallback
li, tr = score({"use_wall_fv": True, "mid_fallback_fv": True})
print(f"mid_fallback: live={li:.0f} (Δ{li-b_li:+5.0f})  "
      f"tr_avg={sum(tr)/3:.0f} (Δ{sum(tr)/3-sum(b_tr)/3:+5.0f})")

# Combo with ema
for a in [0.3, 0.5]:
    li, tr = score({"use_wall_fv": True, "mid_fallback_fv": True, "wall_fv_ema_alpha": a})
    print(f"mid_fallback + ema={a}: live={li:.0f} (Δ{li-b_li:+5.0f})  "
          f"tr_avg={sum(tr)/3:.0f} (Δ{sum(tr)/3-sum(b_tr)/3:+5.0f})")
