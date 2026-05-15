"""Sweep PEPPER params against 127989 baseline via server-book MC.

Baseline: accumulate_threshold=70, buy_above_fv=8, default_sell_qty=8,
          insider_sell_qty=15, cooldown_up=20, cooldown_down=-10.

114525 (no-sell) got server PEP=7286; 127989 (insider-aware MM) got 7577
(+291). So spread-capture in hold phase is the value-add.
"""
from __future__ import annotations
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from parametric_trader import make_trader
from server_book_replay import run_server_session


def run_pep(pep_params, n_seeds=50):
    pnls = []
    for s in range(n_seeds):
        t = make_trader(pep=pep_params)
        r = run_server_session(t, "INTARIAN_PEPPER_ROOT", seed=s)
        pnls.append(r.pnl)
    return pnls


def main():
    n_seeds = 50
    baseline = run_pep({}, n_seeds)  # all defaults
    bm = statistics.mean(baseline)
    bs = statistics.stdev(baseline)
    print(f"Baseline (defaults):  mean={bm:.0f}  std={bs:.0f}\n")

    def sweep(name, param, values, other=None):
        print(f"\n=== {name} sweep ===")
        other = other or {}
        print(f"{param:>22}  {'mean':>6}  {'std':>4}  {'Δmean':>6}  {'wins':>5}")
        best = None
        for v in values:
            params = {**other, param: v}
            pnls = run_pep(params, n_seeds)
            diffs = [p - b for p, b in zip(pnls, baseline)]
            dm = statistics.mean(diffs)
            wins = sum(1 for d in diffs if d > 0)
            mean = statistics.mean(pnls)
            std = statistics.stdev(pnls)
            flag = "*BEAT*" if dm > 0 and wins >= 35 else ""
            print(f"{str(v):>22}  {mean:6.0f}  {std:4.0f}  {dm:+6.0f}  {wins:>2d}/{n_seeds} {flag}")
            if best is None or dm > best[0]:
                best = (dm, v, mean, wins)
        print(f"  best: {param}={best[1]}  Δ={best[0]:+.0f}  wins={best[3]}")
        return best

    sweep("default_sell_qty",    "default_sell_qty",    [3, 5, 8, 10, 12, 15, 20, 25])
    sweep("insider_sell_qty",    "insider_sell_qty",    [8, 10, 12, 15, 20, 25, 30, 40])
    sweep("cooldown_up",         "cooldown_up",         [0, 10, 15, 20, 25, 30, 40, 50])
    sweep("cooldown_down",       "cooldown_down",       [0, -5, -10, -15, -20, -30])
    sweep("buy_above_fv",        "buy_above_fv",        [3, 5, 8, 10, 12, 15, 20])
    sweep("accumulate_threshold","accumulate_threshold",[50, 60, 65, 70, 75, 78, 80])


if __name__ == "__main__":
    main()
