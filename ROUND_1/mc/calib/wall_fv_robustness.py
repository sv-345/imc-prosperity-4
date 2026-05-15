"""Is wall_fv overfit or robust? Test against multi-session ground truth."""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from parametric_trader import make_trader
from server_book_replay_v2 import run_server_session_v2
from training_book_replay_v2 import run_training_session_v2


# 1. Per-day breakdown on training (show each day, not just avg)
print("=== Per-day training breakdown ===")
for day in ["-2", "-1", "0"]:
    for label, osm in [("baseline", {}), ("wall_fv", {"use_wall_fv": True}),
                       ("e22", {"quote_edge": 22}), ("wall_fv+e22", {"use_wall_fv": True, "quote_edge": 22})]:
        t = make_trader(osm=osm)
        o = run_training_session_v2(t, "ASH_COATED_OSMIUM", day).pnl
        print(f"  day={day} {label:>14}: OSM={o:.0f}")
    print()

# 2. Test other training sessions (if any exist by session id)
print("\n=== Live session (127989) ===")
for label, osm in [("baseline", {}), ("wall_fv", {"use_wall_fv": True}),
                   ("e22", {"quote_edge": 22}), ("wall_fv+e22", {"use_wall_fv": True, "quote_edge": 22})]:
    t = make_trader(osm=osm)
    o = run_server_session_v2(t, "ASH_COATED_OSMIUM").pnl
    print(f"  127989 {label:>14}: OSM={o:.0f}")
