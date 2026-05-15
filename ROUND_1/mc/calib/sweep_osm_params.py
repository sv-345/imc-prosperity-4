"""Sweep OSMIUM (quote_edge, min_inside_qty) against 127989 baseline.

Uses server-book replay (validated ranking MC, Spearman ρ=1.0 across all 4
submissions). Paired comparison: same seeds for candidate and baseline.

Baseline: quote_edge=12, min_inside_qty=15 (127989).

A real improvement requires:
  - Paired mean diff > 0 with wins ≥ 35/50 seeds
  - (Optional) non-overlapping 80% CI vs baseline
"""
from __future__ import annotations
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from parametric_trader import make_trader
from server_book_replay import run_server_session


def run_osm(osm_params, n_seeds=50):
    pnls = []
    for s in range(n_seeds):
        t = make_trader(osm=osm_params)
        r = run_server_session(t, "ASH_COATED_OSMIUM", seed=s)
        pnls.append(r.pnl)
    return pnls


def main():
    n_seeds = 50
    baseline = run_osm({"quote_edge": 12, "min_inside_qty": 15}, n_seeds)
    bm = statistics.mean(baseline)
    bs = statistics.stdev(baseline)
    print(f"Baseline (edge=12, min=15):  mean={bm:.0f}  std={bs:.0f}\n")

    # Grid: edge 9..18, min_inside 5, 10, 15, 20, 25, 30
    edges = [9, 10, 11, 12, 13, 14, 15, 16, 17, 18]
    mins = [5, 10, 15, 20, 25, 30]
    print(f"{'edge':>4} {'min':>4}  {'mean':>6}  {'std':>4}  {'Δmean':>6}  {'wins':>5}  {'verdict'}")
    results = []
    for e in edges:
        for m in mins:
            pnls = run_osm({"quote_edge": e, "min_inside_qty": m}, n_seeds)
            diffs = [p - b for p, b in zip(pnls, baseline)]
            dm = statistics.mean(diffs)
            wins = sum(1 for d in diffs if d > 0)
            mean = statistics.mean(pnls)
            std = statistics.stdev(pnls)
            flag = ""
            if dm > 0 and wins >= 35:
                flag = "*BEAT*"
            elif dm < 0 and wins < 15:
                flag = "worse"
            results.append((e, m, mean, std, dm, wins))
            print(f"{e:>4d} {m:>4d}  {mean:6.0f}  {std:4.0f}  {dm:+6.0f}  {wins:>2d}/{n_seeds}  {flag}")

    # Top 5 by mean Δ
    print("\nTop 5 by paired Δmean:")
    results.sort(key=lambda r: -r[4])
    for e, m, mean, std, dm, wins in results[:5]:
        print(f"  edge={e:2d} min={m:2d}  mean={mean:5.0f}  Δ={dm:+5.0f}  wins={wins}")


if __name__ == "__main__":
    main()
