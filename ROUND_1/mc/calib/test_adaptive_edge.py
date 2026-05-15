"""Test adaptive-edge idea: base edge=12, but when book one-sided add bonus.

Hypothesis: the gains from wide edge come entirely from one-sided events. If we
keep edge=12 normally (safe, keeps fills) but widen to edge=22 or 30 only when
book is one-sided, we should capture the gain without the risk on normal ticks.
"""
from __future__ import annotations
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from parametric_trader import make_trader
from server_book_replay import run_server_session
from training_book_replay import run_training_session


def tr_avg(osm, pep):
    totals = []
    for day in ["-2", "-1", "0"]:
        t = make_trader(osm=osm, pep=pep)
        a = run_training_session(t, "ASH_COATED_OSMIUM", day).pnl
        t = make_trader(osm=osm, pep=pep)
        b = run_training_session(t, "INTARIAN_PEPPER_ROOT", day).pnl
        totals.append(a + b)
    return totals


def live_paired(osm, pep, n=50):
    tots = []
    base_tots = []
    for s in range(n):
        t = make_trader(osm=osm, pep=pep)
        a = run_server_session(t, "ASH_COATED_OSMIUM", seed=s).pnl
        t = make_trader(osm=osm, pep=pep)
        b = run_server_session(t, "INTARIAN_PEPPER_ROOT", seed=s).pnl
        tots.append(a + b)
        t = make_trader()  # baseline
        a = run_server_session(t, "ASH_COATED_OSMIUM", seed=s).pnl
        t = make_trader()
        b = run_server_session(t, "INTARIAN_PEPPER_ROOT", seed=s).pnl
        base_tots.append(a + b)
    diffs = [t - b for t, b in zip(tots, base_tots)]
    return statistics.mean(diffs), sum(1 for d in diffs if d > 0), statistics.mean(tots)


def main():
    base_tr = tr_avg({}, {})
    print(f"baseline training: avg={sum(base_tr)/3:.0f}")

    pep65 = {"accumulate_threshold": 65, "cooldown_up": 0}

    candidates = [
        # Adaptive with wider bonuses
        ("e12+bon30+t65", {"quote_edge": 12, "onesided_edge_bonus": 30}, pep65),
        ("e12+bon50+t65", {"quote_edge": 12, "onesided_edge_bonus": 50}, pep65),
        ("e12+bon80+t65", {"quote_edge": 12, "onesided_edge_bonus": 80}, pep65),
        ("e12+bon120+t65",{"quote_edge": 12, "onesided_edge_bonus": 120}, pep65),
        ("e12+bon200+t65",{"quote_edge": 12, "onesided_edge_bonus": 200}, pep65),
        # Fixed wide for comparison
        ("e40+t65+cu0",   {"quote_edge": 40}, pep65),
        ("e60+t65+cu0",   {"quote_edge": 60}, pep65),
        ("e100+t65+cu0",  {"quote_edge": 100}, pep65),
        # Baseline (no adapt)
        ("e22+t65+cu0",   {"quote_edge": 22}, pep65),
    ]

    print(f"\n{'candidate':>16}  {'d-2':>5}  {'d-1':>5}  {'d0':>5}  "
          f"{'tr_avg':>6}  {'live_Δ':>7}  {'wins':>5}")
    for name, osm, pep in candidates:
        tr = tr_avg(osm, pep)
        diffs_tr = [t - b for t, b in zip(tr, base_tr)]
        li_d, wins, li_tot = live_paired(osm, pep, n=50)
        print(f"{name:>16}  {diffs_tr[0]:+5.0f}  {diffs_tr[1]:+5.0f}  {diffs_tr[2]:+5.0f}  "
              f"{sum(diffs_tr)/3:+6.0f}  {li_d:+7.0f}  {wins:2d}/50")


if __name__ == "__main__":
    main()
