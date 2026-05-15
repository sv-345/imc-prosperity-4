"""Test sweeping asks/bids AT FV=10000 in addition to strictly mispriced."""
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


for osm in [{}, {"sweep_at_fv": True}]:
    li, tr = score(osm)
    print(f"{str(osm):>30}: live={li:.0f} tr={[int(x) for x in tr]} avg={sum(tr)/3:.0f}")

# Combined with best candidates
for osm in [{"quote_edge": 22}, {"quote_edge": 22, "sweep_at_fv": True}]:
    li, tr = score(osm)
    print(f"{str(osm):>50}: live={li:.0f} tr={[int(x) for x in tr]} avg={sum(tr)/3:.0f}")
