"""Best candidate: per-day training breakdown to verify consistency."""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from parametric_trader import make_trader
from server_book_replay_v2 import run_server_session_v2
from training_book_replay_v2 import run_training_session_v2


def per_day(osm, pep, label):
    print(f"\n{label}")
    t = make_trader(osm=osm, pep=pep)
    o_li = run_server_session_v2(t, "ASH_COATED_OSMIUM").pnl
    t = make_trader(osm=osm, pep=pep)
    p_li = run_server_session_v2(t, "INTARIAN_PEPPER_ROOT").pnl
    print(f"  live 127989: OSM={o_li:.0f} PEP={p_li:.0f} TOT={o_li+p_li:.0f}")
    for d in ["-2", "-1", "0"]:
        t = make_trader(osm=osm, pep=pep)
        o = run_training_session_v2(t, "ASH_COATED_OSMIUM", d).pnl
        t = make_trader(osm=osm, pep=pep)
        p = run_training_session_v2(t, "INTARIAN_PEPPER_ROOT", d).pnl
        print(f"  day={d}: OSM={o:.0f} PEP={p:.0f} TOT={o+p:.0f}")


per_day({}, {}, "=== baseline (127989 defaults) ===")

per_day(
    {"use_wall_fv": True, "wall_fv_ema_alpha": 0.5, "quote_edge": 22},
    {"accumulate_threshold": 65, "cooldown_up": 0},
    "=== BEST: wall_fv + ema5 + e22 + t65 + cu0 ===",
)
