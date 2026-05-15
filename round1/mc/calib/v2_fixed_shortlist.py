"""Shortlist comparison with fixed v2 (trade-price cap).

With the fill-price fix, v2 shows no edge-gain on live 127989 for OSM. All gains
now come from training (multi-day) and PEP. Goal: find candidates whose training
advantage is robust AND doesn't risk PEP structural errors.
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from parametric_trader import make_trader
from server_book_replay_v2 import run_server_session_v2
from training_book_replay_v2 import run_training_session_v2


def score(osm, pep):
    t = make_trader(osm=osm, pep=pep)
    o_li = run_server_session_v2(t, "ASH_COATED_OSMIUM").pnl
    t = make_trader(osm=osm, pep=pep)
    p_li = run_server_session_v2(t, "INTARIAN_PEPPER_ROOT").pnl
    tr = []
    for d in ["-2", "-1", "0"]:
        t = make_trader(osm=osm, pep=pep)
        o = run_training_session_v2(t, "ASH_COATED_OSMIUM", d).pnl
        t = make_trader(osm=osm, pep=pep)
        p = run_training_session_v2(t, "INTARIAN_PEPPER_ROOT", d).pnl
        tr.append(o + p)
    return o_li, p_li, tr


b_oli, b_pli, b_tr = score({}, {})
print(f"baseline: live_osm={b_oli} live_pep={b_pli} live_tot={b_oli+b_pli}  "
      f"tr={[int(x) for x in b_tr]}  tr_avg={sum(b_tr)/3:.0f}")
print()

cands = [
    ("e16+t65+cu0", {"quote_edge": 16}, {"accumulate_threshold": 65, "cooldown_up": 0}),
    ("e18+t65+cu0", {"quote_edge": 18}, {"accumulate_threshold": 65, "cooldown_up": 0}),
    ("e22+t65+cu0", {"quote_edge": 22}, {"accumulate_threshold": 65, "cooldown_up": 0}),
    ("e22+t60+cu0", {"quote_edge": 22}, {"accumulate_threshold": 60, "cooldown_up": 0}),
    ("e22+t70+cu0", {"quote_edge": 22}, {"accumulate_threshold": 70, "cooldown_up": 0}),
    ("e22+t75+cu0", {"quote_edge": 22}, {"accumulate_threshold": 75, "cooldown_up": 0}),
    ("e30+t65+cu0", {"quote_edge": 30}, {"accumulate_threshold": 65, "cooldown_up": 0}),
    ("e22+t65",     {"quote_edge": 22}, {"accumulate_threshold": 65}),
    ("t65+cu0",     {},                {"accumulate_threshold": 65, "cooldown_up": 0}),
]

print(f"{'name':>18}  {'oli':>5} {'pli':>5} {'tot':>5}  {'Δtot':>6}  "
      f"{'tr_avg':>7}  {'Δtr':>5}")
for name, o, p in cands:
    oli, pli, tr = score(o, p)
    dtot = oli + pli - (b_oli + b_pli)
    dtr = sum(tr)/3 - sum(b_tr)/3
    print(f"{name:>18}  {oli:5.0f} {pli:5.0f} {oli+pli:5.0f}  {dtot:+6.0f}  "
          f"{sum(tr)/3:7.0f}  {dtr:+5.0f}")
