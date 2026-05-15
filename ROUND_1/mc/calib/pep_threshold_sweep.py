"""Sweep PEP accumulate_threshold fine-grained across both training (10k ticks)
and live MC (1k ticks). The two regimes may prefer different thresholds because
session length changes the trend-capture vs cycling-profit tradeoff.
"""
from __future__ import annotations
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from parametric_trader import make_trader
from server_book_replay import run_server_session
from training_book_replay import run_training_session


def training_avg(pep_params):
    totals = []
    for day in ["-2", "-1", "0"]:
        t = make_trader(pep=pep_params)
        pnl = run_training_session(t, "INTARIAN_PEPPER_ROOT", day).pnl
        totals.append(pnl)
    return sum(totals) / 3, totals


def live_avg(pep_params, n=50):
    pnls = []
    for s in range(n):
        t = make_trader(pep=pep_params)
        pnls.append(run_server_session(t, "INTARIAN_PEPPER_ROOT", seed=s).pnl)
    return statistics.mean(pnls), pnls


def main():
    thresholds = [55, 58, 60, 62, 65, 68, 70, 72, 75, 78, 80]
    print(f"{'thr':>3}  {'tr_avg':>7}  {'tr_d-2':>7}  {'tr_d-1':>7}  {'tr_d0':>7}  "
          f"{'live':>6}  {'live σ':>6}")
    for thr in thresholds:
        p = {"accumulate_threshold": thr}
        tr_avg, tr_days = training_avg(p)
        li_avg, li_pnls = live_avg(p, n=30)
        print(f"{thr:3d}  {tr_avg:7.0f}  {tr_days[0]:7.0f}  {tr_days[1]:7.0f}  "
              f"{tr_days[2]:7.0f}  {li_avg:6.0f}  {statistics.stdev(li_pnls):6.0f}")


if __name__ == "__main__":
    main()
