"""Final picking: e22+t65+cu0 vs baseline and close variants.

Aim: confirm robust choice across all available evidence.
"""
from __future__ import annotations
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from parametric_trader import make_trader
from server_book_replay_v2 import run_server_session_v2
from training_book_replay_v2 import run_training_session_v2
from server_book_replay import run_server_session as v1_server


def v2_scores(osm, pep):
    t = make_trader(osm=osm, pep=pep)
    o = run_server_session_v2(t, "ASH_COATED_OSMIUM").pnl
    t = make_trader(osm=osm, pep=pep)
    p = run_server_session_v2(t, "INTARIAN_PEPPER_ROOT").pnl
    tr_osm = []
    tr_pep = []
    for d in ["-2", "-1", "0"]:
        t = make_trader(osm=osm, pep=pep)
        tr_osm.append(run_training_session_v2(t, "ASH_COATED_OSMIUM", d).pnl)
        t = make_trader(osm=osm, pep=pep)
        tr_pep.append(run_training_session_v2(t, "INTARIAN_PEPPER_ROOT", d).pnl)
    return o, p, tr_osm, tr_pep


def v1_stats(osm, pep, base_osm, base_pep, n=50):
    wins = 0
    diffs = []
    for s in range(n):
        t = make_trader(osm=osm, pep=pep)
        a = v1_server(t, "ASH_COATED_OSMIUM", seed=s).pnl
        t = make_trader(osm=osm, pep=pep)
        b = v1_server(t, "INTARIAN_PEPPER_ROOT", seed=s).pnl
        t = make_trader(osm=base_osm, pep=base_pep)
        a0 = v1_server(t, "ASH_COATED_OSMIUM", seed=s).pnl
        t = make_trader(osm=base_osm, pep=base_pep)
        b0 = v1_server(t, "INTARIAN_PEPPER_ROOT", seed=s).pnl
        d = (a + b) - (a0 + b0)
        diffs.append(d)
        if d > 0:
            wins += 1
    return statistics.mean(diffs), statistics.stdev(diffs), wins, n


print("=" * 80)
print("Fixed v2 eval (baseline = 127989 defaults)")
print("=" * 80)

# Baseline v1 stats for ref
b_osm = {}
b_pep = {}
b_v2 = v2_scores(b_osm, b_pep)
print(f"\nbaseline: v2_osm={b_v2[0]:.0f} v2_pep={b_v2[1]:.0f}")
print(f"  tr_osm={[int(x) for x in b_v2[2]]} avg={sum(b_v2[2])/3:.0f}")
print(f"  tr_pep={[int(x) for x in b_v2[3]]} avg={sum(b_v2[3])/3:.0f}")

cands = [
    ("e22",         {"quote_edge": 22}, {}),
    ("t65+cu0",     {},                {"accumulate_threshold": 65, "cooldown_up": 0}),
    ("e22+t65+cu0", {"quote_edge": 22}, {"accumulate_threshold": 65, "cooldown_up": 0}),
    ("e22+t60+cu0", {"quote_edge": 22}, {"accumulate_threshold": 60, "cooldown_up": 0}),
    ("e22+t70+cu0", {"quote_edge": 22}, {"accumulate_threshold": 70, "cooldown_up": 0}),
]

for name, osm, pep in cands:
    o, p, tro, trp = v2_scores(osm, pep)
    d_live = o + p - (b_v2[0] + b_v2[1])
    d_tr = (sum(tro) + sum(trp))/3 - (sum(b_v2[2]) + sum(b_v2[3]))/3
    v1m, v1s, w, n = v1_stats(osm, pep, b_osm, b_pep, n=50)
    print(f"\n{name}:")
    print(f"  v2_live: osm={o:.0f} pep={p:.0f} tot={o+p:.0f}  Δ{d_live:+.0f}")
    print(f"  v2_training_avg/day: osm={sum(tro)/3:.0f} pep={sum(trp)/3:.0f}  Δ{d_tr:+.0f}")
    print(f"  v1 paired: Δ_mean={v1m:+.0f} σ={v1s:.0f} wins={w}/{n}")
