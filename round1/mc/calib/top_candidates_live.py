"""Validate top candidates from multi_day_validate on server-book MC (1000-tick live).

Candidates are the ones that were ROBUST on training. We now confirm they also
beat baseline on live bot books (127989 session) with MC-sampled takers.
"""
from __future__ import annotations
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from parametric_trader import make_trader
from server_book_replay import run_server_session


def run_cand(osm, pep, n=50):
    op, pp = [], []
    for s in range(n):
        t = make_trader(osm=osm, pep=pep)
        op.append(run_server_session(t, "ASH_COATED_OSMIUM", seed=s).pnl)
        t = make_trader(osm=osm, pep=pep)
        pp.append(run_server_session(t, "INTARIAN_PEPPER_ROOT", seed=s).pnl)
    tot = [o + p for o, p in zip(op, pp)]
    return op, pp, tot


def main():
    candidates = [
        ("baseline",     {}, {}),
        ("e22+t62",      {"quote_edge": 22}, {"accumulate_threshold": 62}),
        ("e22+t65",      {"quote_edge": 22}, {"accumulate_threshold": 65}),
        ("22t62+sk.10",  {"quote_edge": 22, "skew_per_pos": 0.10}, {"accumulate_threshold": 62}),
        ("22t62+sk.15",  {"quote_edge": 22, "skew_per_pos": 0.15}, {"accumulate_threshold": 62}),
        ("22t62+sk-.05", {"quote_edge": 22, "skew_per_pos": -0.05}, {"accumulate_threshold": 62}),
        ("22t62+mi25",   {"quote_edge": 22, "min_inside_qty": 25}, {"accumulate_threshold": 62}),
        ("bE18/sE22+t62", {"buy_edge": 18, "sell_edge": 22}, {"accumulate_threshold": 62}),
    ]
    b_op, b_pp, b_tot = run_cand({}, {}, n=50)
    print(f"baseline  OSM={statistics.mean(b_op):.0f}  PEP={statistics.mean(b_pp):.0f}  "
          f"TOT={statistics.mean(b_tot):.0f}  σ={statistics.stdev(b_tot):.0f}")
    print()
    print(f"{'candidate':>14}  {'OSM':>5}  {'PEP':>5}  {'TOT':>5}  {'Δmean':>6}  {'wins':>5}")
    for name, osm, pep in candidates:
        if name == "baseline":
            continue
        op, pp, tot = run_cand(osm, pep, n=50)
        diffs = [t - b for t, b in zip(tot, b_tot)]
        dm = statistics.mean(diffs)
        wins = sum(1 for d in diffs if d > 0)
        print(f"{name:>14}  {statistics.mean(op):5.0f}  {statistics.mean(pp):5.0f}  "
              f"{statistics.mean(tot):5.0f}  {dm:+6.0f}  {wins:2d}/50")


if __name__ == "__main__":
    main()
