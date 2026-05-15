"""Sweep PEP insider detection and reaction parameters.

PEP is 70% of PnL; small insider tweaks can move it more than OSM edge can.

Params:
  insider_qty: threshold qty to detect insider trade (default 8)
  cooldown_up: no-sell ticks after insider BOUGHT (default 20)
  cooldown_down: aggressive-sell ticks after insider SOLD (default -10)
  insider_sell_qty: qty when in aggressive-sell (default 15)
  default_sell_qty: qty when no insider signal (default 8)
  sell_offset: best_ask - X for sell price (default 1)
  buy_above_fv: max buy price above fv during accumulate (default 8)
"""
from __future__ import annotations
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from parametric_trader import make_trader
from server_book_replay import run_server_session
from training_book_replay import run_training_session


def tr_avg(pep):
    return sum(
        run_training_session(make_trader(pep=pep), "INTARIAN_PEPPER_ROOT", d).pnl
        for d in ["-2", "-1", "0"]
    ) / 3


def live_avg(pep, n=30):
    return statistics.mean([
        run_training_session(make_trader(pep=pep), "INTARIAN_PEPPER_ROOT", "0").pnl
        for _ in [0]
    ]) if False else statistics.mean([
        run_server_session(make_trader(pep=pep), "INTARIAN_PEPPER_ROOT", seed=s).pnl
        for s in range(n)
    ])


def sweep(name, base, var_name, values):
    print(f"\n=== {name}: {var_name} ∈ {values} ===")
    baseline_tr = tr_avg({**base})
    baseline_li = live_avg({**base})
    print(f"  base tr={baseline_tr:.0f}  live={baseline_li:.0f}")
    for v in values:
        p = {**base, var_name: v}
        t = tr_avg(p)
        l = live_avg(p, n=30)
        print(f"  {var_name}={v:>4}: tr={t:.0f}  (Δ{t-baseline_tr:+.0f})   "
              f"live={l:.0f}  (Δ{l-baseline_li:+.0f})")


def main():
    # With thr=65 fixed (live-optimal)
    base = {"accumulate_threshold": 65}
    sweep("insider_sell_qty", base, "insider_sell_qty", [8, 10, 12, 15, 20, 25])
    sweep("default_sell_qty", base, "default_sell_qty", [4, 6, 8, 10, 12, 15])
    sweep("cooldown_up",     base, "cooldown_up", [0, 5, 10, 15, 20, 30, 50])
    sweep("cooldown_down",   base, "cooldown_down", [0, -5, -10, -15, -20, -30])
    sweep("insider_qty",     base, "insider_qty", [5, 7, 8, 10, 12])
    sweep("buy_above_fv",    base, "buy_above_fv", [3, 5, 6, 8, 10, 12, 15])
    sweep("sell_offset",     base, "sell_offset", [0, 1, 2, 3])
    sweep("bid_offset",      base, "bid_offset", [0, 1, 2])


if __name__ == "__main__":
    main()
