"""Wall-FV for OSM combined with PEP best (t65+cu0)."""
from __future__ import annotations
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from parametric_trader import make_trader
from server_book_replay_v2 import run_server_session_v2
from training_book_replay_v2 import run_training_session_v2
from server_book_replay import run_server_session as v1_server


def v2_tot(osm, pep):
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
    return o_li + p_li, tr


def v1_stats(osm, pep, base_osm, base_pep, n=40):
    diffs = []
    wins = 0
    for s in range(n):
        t = make_trader(osm=osm, pep=pep)
        a = v1_server(t, "ASH_COATED_OSMIUM", seed=s).pnl
        t = make_trader(osm=osm, pep=pep)
        b = v1_server(t, "INTARIAN_PEPPER_ROOT", seed=s).pnl
        t = make_trader(osm=base_osm, pep=base_pep)
        a0 = v1_server(t, "ASH_COATED_OSMIUM", seed=s).pnl
        t = make_trader(osm=base_osm, pep=base_pep)
        b0 = v1_server(t, "INTARIAN_PEPPER_ROOT", seed=s).pnl
        d = (a+b) - (a0+b0)
        diffs.append(d)
        if d > 0:
            wins += 1
    return statistics.mean(diffs), statistics.stdev(diffs), wins, n


b_osm = {}
b_pep = {}
b_v2_li, b_v2_tr = v2_tot(b_osm, b_pep)
print(f"baseline: v2_live={b_v2_li} tr_avg={sum(b_v2_tr)/3:.0f}")

cands = [
    ("wall_fv",                      {"use_wall_fv": True}, {}),
    ("wall_fv+e22",                  {"use_wall_fv": True, "quote_edge": 22}, {}),
    ("wall_fv+t65+cu0",              {"use_wall_fv": True}, {"accumulate_threshold": 65, "cooldown_up": 0}),
    ("wall_fv+e22+t65+cu0",          {"use_wall_fv": True, "quote_edge": 22},
                                      {"accumulate_threshold": 65, "cooldown_up": 0}),
    ("wall_fv+e22+t60+cu0",          {"use_wall_fv": True, "quote_edge": 22},
                                      {"accumulate_threshold": 60, "cooldown_up": 0}),
    ("wall_fv+e22+t70+cu0",          {"use_wall_fv": True, "quote_edge": 22},
                                      {"accumulate_threshold": 70, "cooldown_up": 0}),
    ("e22+t65+cu0 (prev-best)",      {"quote_edge": 22},
                                      {"accumulate_threshold": 65, "cooldown_up": 0}),
]

print(f"\n{'name':>30}  {'v2_live':>7} {'Δ':>5}  {'tr_avg':>7} {'Δ':>6}  "
      f"{'v1_Δ':>5} {'v1_σ':>5} {'wins':>5}")
for name, osm, pep in cands:
    li, tr = v2_tot(osm, pep)
    dli = li - b_v2_li
    dtr = sum(tr)/3 - sum(b_v2_tr)/3
    v1m, v1s, w, n = v1_stats(osm, pep, b_osm, b_pep, n=40)
    print(f"{name:>30}  {li:7.0f} {dli:+5.0f}  {sum(tr)/3:7.0f} {dtr:+6.0f}  "
          f"{v1m:+5.0f} {v1s:5.0f} {w:2d}/{n}")
