"""Sweep OSM edge at fine granularity on BOTH training (10k ticks) and live MC (1k ticks).

Goal: find the live-optimal edge (real server is 1k ticks), not training-optimal.
"""
from __future__ import annotations
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from parametric_trader import make_trader
from server_book_replay import run_server_session
from training_book_replay import run_training_session


def training_avg(osm_params):
    totals = []
    for day in ["-2", "-1", "0"]:
        t = make_trader(osm=osm_params)
        pnl = run_training_session(t, "ASH_COATED_OSMIUM", day).pnl
        totals.append(pnl)
    return sum(totals) / 3, totals


def live_avg(osm_params, n=50):
    pnls = []
    for s in range(n):
        t = make_trader(osm=osm_params)
        pnls.append(run_server_session(t, "ASH_COATED_OSMIUM", seed=s).pnl)
    return statistics.mean(pnls), pnls


def main():
    edges = [10, 12, 16, 22, 30, 40, 60, 100, 150]
    print(f"{'edge':>4}  {'tr_avg':>7}  {'tr_d-2':>7}  {'tr_d-1':>7}  {'tr_d0':>7}  "
          f"{'live':>6}  {'live σ':>6}")
    for e in edges:
        p = {"quote_edge": e}
        tr_avg, tr_days = training_avg(p)
        li_avg, li_pnls = live_avg(p, n=30)
        print(f"{e:4d}  {tr_avg:7.0f}  {tr_days[0]:7.0f}  {tr_days[1]:7.0f}  "
              f"{tr_days[2]:7.0f}  {li_avg:6.0f}  {statistics.stdev(li_pnls):6.0f}")


if __name__ == "__main__":
    main()
