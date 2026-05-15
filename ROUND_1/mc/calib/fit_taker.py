"""Fit taker model params to 127989 ground truth.

Ground truth (1 server session, 1000 ticks) from extract_127989_fills.py:
  OSMIUM: 87 fills, buy_qty=255, sell_qty=268, pnl=3144
  PEPPER: 25 fills, buy_qty=120, sell_qty=40,  pnl=7577

We grid-search (taker_rate, qty_lo, qty_hi) per product; run many MC seeds
with 127989.py strategy; score = weighted mismatch on (n_fills, buy_qty,
sell_qty, pnl). Keep the top-K; show them.

Runtime budget: ~30 combos × 30 seeds × 1000 ticks. Should be under a minute.
"""
from __future__ import annotations
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from synth_replay import _load_trader_from_path, run_session


SUBMISSION_127989 = ("/Users/svelaga/Documents/IMC Prosperity/"
                     "ROUND_1/submissions/127989/127989.py")

TRUTH = {
    "ASH_COATED_OSMIUM": {
        "n_fills": 87, "buy_qty": 255, "sell_qty": 268, "pnl": 3144,
    },
    "INTARIAN_PEPPER_ROOT": {
        "n_fills": 25, "buy_qty": 120, "sell_qty":  40, "pnl": 7577,
    },
}


def stats_for(results):
    n = len(results)
    pnls = [r.pnl for r in results]
    fills = [len(r.fills) for r in results]
    buys = [sum(f.qty for f in r.fills if f.side == "BUY") for r in results]
    sells = [sum(f.qty for f in r.fills if f.side == "SELL") for r in results]
    return {
        "pnl_mean": statistics.mean(pnls),
        "pnl_std": statistics.stdev(pnls) if n > 1 else 0,
        "n_fills_mean": statistics.mean(fills),
        "buy_qty_mean": statistics.mean(buys),
        "sell_qty_mean": statistics.mean(sells),
    }


def score(mc, truth):
    """Relative mismatch score — lower is better."""
    def rel(a, b):
        if b == 0:
            return abs(a) / max(abs(a), 1)
        return abs(a - b) / max(abs(b), 1)
    # Weight: n_fills and buy/sell qty count double; pnl single
    return (2 * rel(mc["n_fills_mean"], truth["n_fills"])
            + 2 * rel(mc["buy_qty_mean"], truth["buy_qty"])
            + 2 * rel(mc["sell_qty_mean"], truth["sell_qty"])
            + 1 * rel(mc["pnl_mean"], truth["pnl"]))


def sweep(product, n_seeds, rates, qty_ranges):
    truth = TRUTH[product]
    print(f"\n=== {product} ===")
    print(f"TRUTH: n_fills={truth['n_fills']}  buy_qty={truth['buy_qty']}  "
          f"sell_qty={truth['sell_qty']}  pnl={truth['pnl']}")
    out = []
    for rate in rates:
        for qr in qty_ranges:
            # Fresh trader per run (stateful)
            results = []
            for s in range(n_seeds):
                t = _load_trader_from_path(SUBMISSION_127989)
                r = run_session(t, product, seed=s,
                                taker_rate=rate, qty_range=qr)
                results.append(r)
            mc = stats_for(results)
            sc = score(mc, truth)
            row = {
                "rate": rate, "qty_range": qr,
                "n_fills": mc["n_fills_mean"],
                "buy_qty": mc["buy_qty_mean"],
                "sell_qty": mc["sell_qty_mean"],
                "pnl_mean": mc["pnl_mean"],
                "pnl_std": mc["pnl_std"],
                "score": sc,
            }
            out.append(row)
            print(f"  rate={rate:.3f} qty={qr}  "
                  f"n_fills={mc['n_fills_mean']:5.1f}  "
                  f"buy={mc['buy_qty_mean']:6.1f}  "
                  f"sell={mc['sell_qty_mean']:6.1f}  "
                  f"pnl={mc['pnl_mean']:+6.0f}±{mc['pnl_std']:.0f}  "
                  f"score={sc:.3f}")
    out.sort(key=lambda r: r["score"])
    print("\n-- Top 3 --")
    for row in out[:3]:
        print(f"  rate={row['rate']:.3f} qty={row['qty_range']}  "
              f"score={row['score']:.3f}  "
              f"n_fills={row['n_fills']:.1f} "
              f"buy={row['buy_qty']:.1f} sell={row['sell_qty']:.1f} "
              f"pnl={row['pnl_mean']:+.0f}")
    return out


def main():
    n_seeds = 30
    print(f"Grid sweep with {n_seeds} seeds per combo")
    osm_rates = [0.042, 0.06, 0.08, 0.10, 0.12, 0.14]
    osm_qtys = [(1, 5), (2, 6), (2, 8), (3, 10)]
    osm = sweep("ASH_COATED_OSMIUM", n_seeds, osm_rates, osm_qtys)

    pep_rates = [0.033, 0.020, 0.015, 0.010]
    pep_qtys = [(3, 8), (2, 6), (1, 5), (2, 4)]
    pep = sweep("INTARIAN_PEPPER_ROOT", n_seeds, pep_rates, pep_qtys)

    outp = Path(__file__).parent / "fit_taker_results.json"
    outp.write_text(json.dumps({
        "ASH_COATED_OSMIUM": osm,
        "INTARIAN_PEPPER_ROOT": pep,
    }, default=list, indent=2))
    print(f"\nWrote {outp}")


if __name__ == "__main__":
    main()
