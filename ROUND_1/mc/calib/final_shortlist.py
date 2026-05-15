"""Final shortlist comparison across v1 (50-seed MC) + v2 (deterministic) + training v2.

Goal: pick the candidate with best risk/reward for server submission.
"""
from __future__ import annotations
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from parametric_trader import make_trader
from server_book_replay import run_server_session as v1_server
from server_book_replay_v2 import run_server_session_v2
from training_book_replay_v2 import run_training_session_v2


def v1_mean_wins(osm, pep, base_osm, base_pep, n=60):
    tots = []
    bases = []
    for s in range(n):
        t = make_trader(osm=osm, pep=pep)
        a = v1_server(t, "ASH_COATED_OSMIUM", seed=s).pnl
        t = make_trader(osm=osm, pep=pep)
        b = v1_server(t, "INTARIAN_PEPPER_ROOT", seed=s).pnl
        tots.append(a + b)
        t = make_trader(osm=base_osm, pep=base_pep)
        a = v1_server(t, "ASH_COATED_OSMIUM", seed=s).pnl
        t = make_trader(osm=base_osm, pep=base_pep)
        b = v1_server(t, "INTARIAN_PEPPER_ROOT", seed=s).pnl
        bases.append(a + b)
    diffs = [t - b for t, b in zip(tots, bases)]
    return (statistics.mean(tots), statistics.stdev(tots),
            statistics.mean(diffs), statistics.stdev(diffs),
            sum(1 for d in diffs if d > 0))


def v2_scores(osm, pep):
    t = make_trader(osm=osm, pep=pep)
    o = run_server_session_v2(t, "ASH_COATED_OSMIUM").pnl
    t = make_trader(osm=osm, pep=pep)
    p = run_server_session_v2(t, "INTARIAN_PEPPER_ROOT").pnl
    tr = []
    for d in ["-2", "-1", "0"]:
        t = make_trader(osm=osm, pep=pep)
        o2 = run_training_session_v2(t, "ASH_COATED_OSMIUM", d).pnl
        t = make_trader(osm=osm, pep=pep)
        p2 = run_training_session_v2(t, "INTARIAN_PEPPER_ROOT", d).pnl
        tr.append(o2 + p2)
    return o, p, tr


def main():
    candidates = [
        ("baseline (127989)",  {}, {}),
        ("e16+t65+cu0",        {"quote_edge": 16}, {"accumulate_threshold": 65, "cooldown_up": 0}),
        ("e18+t65+cu0",        {"quote_edge": 18}, {"accumulate_threshold": 65, "cooldown_up": 0}),
        ("e22+t65+cu0",        {"quote_edge": 22}, {"accumulate_threshold": 65, "cooldown_up": 0}),
        ("e22+t60+cu0",        {"quote_edge": 22}, {"accumulate_threshold": 60, "cooldown_up": 0}),
        ("e16+t60+cu0",        {"quote_edge": 16}, {"accumulate_threshold": 60, "cooldown_up": 0}),
    ]

    # v2 baseline for training-Δ comparison
    b_osm_v2, b_pep_v2, b_tr_v2 = v2_scores({}, {})

    print(f"{'candidate':>20}  "
          f"{'v2_osm':>6} {'v2_pep':>6} {'v2_tot':>6}  {'v2tr_avg_Δ':>9}  "
          f"{'v1_tot':>6} {'v1_σ':>5} {'v1_Δ':>5} {'v1σ_Δ':>5} {'wins':>5}")
    for name, osm, pep in candidates:
        o, p, tr = v2_scores(osm, pep)
        tr_d = sum(tr) - sum(b_tr_v2)
        v1_mean, v1_sd, v1_d, v1_ds, wins = v1_mean_wins(osm, pep, {}, {}, n=60)
        print(f"{name:>20}  "
              f"{o:6.0f} {p:6.0f} {o+p:6.0f}  {tr_d/3:+9.0f}  "
              f"{v1_mean:6.0f} {v1_sd:5.0f} {v1_d:+5.0f} {v1_ds:5.0f} {wins:2d}/60")


if __name__ == "__main__":
    main()
