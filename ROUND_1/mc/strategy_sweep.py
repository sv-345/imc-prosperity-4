"""Parameter sweep over OSMIUM edge and PEPPER wall_offset using MC v1.

For each (product, parameter) combo, run N seeds against the exact recorded
R1 book. Report mean/stdev/p95 per configuration.

This answers: is the 127989 submission's edge=10 optimal under MC v1?
"""
from __future__ import annotations
import statistics
from book_replay import run_replay, OSMIUM, PEPPER, SERVER_PNL
from strategies_r1 import make_osmium_stable, make_pepper_trending


def sweep_osmium(edges, n_seeds=100, min_inside_qtys=(15,)):
    print(f"\n{'edge':>6} {'mi_qty':>8} {'mean':>10} {'stdev':>8} {'p05':>8} {'p50':>8} {'p95':>8}")
    for mi in min_inside_qtys:
        for edge in edges:
            strat = make_osmium_stable(fv_anchor=10000.0, edge=edge, min_inside_qty=mi)
            pnls = run_replay(OSMIUM, strat, "ASH_COATED_OSMIUM", n_seeds=n_seeds)
            pnls.sort()
            m = statistics.mean(pnls); sd = statistics.stdev(pnls)
            p05 = pnls[5*n_seeds//100]; p50 = pnls[n_seeds//2]; p95 = pnls[95*n_seeds//100]
            print(f"  {edge:>4} {mi:>8} {m:>10.0f} {sd:>8.0f} {p05:>8.0f} {p50:>8.0f} {p95:>8.0f}")


def sweep_pepper(wall_offsets, n_seeds=50):
    print(f"\n{'wall_off':>10} {'mean':>10} {'stdev':>8} {'p05':>8} {'p50':>8} {'p95':>8}")
    for wo in wall_offsets:
        strat = make_pepper_trending(wall_offset=wo)
        pnls = run_replay(PEPPER, strat, "INTARIAN_PEPPER_ROOT", n_seeds=n_seeds)
        pnls.sort()
        m = statistics.mean(pnls); sd = statistics.stdev(pnls)
        p05 = pnls[5*n_seeds//100]; p50 = pnls[n_seeds//2]; p95 = pnls[95*n_seeds//100]
        print(f"  {wo:>8} {m:>10.0f} {sd:>8.0f} {p05:>8.0f} {p50:>8.0f} {p95:>8.0f}")


def main():
    print(f"OSMIUM server PnL (submission 127989, edge=10): {SERVER_PNL['ASH_COATED_OSMIUM']}")
    print("Sweep OSMIUM edge × min_inside_qty (100 seeds each, book-replay)")
    sweep_osmium(edges=[2, 4, 6, 8, 10, 12, 14, 16], n_seeds=100, min_inside_qtys=(5, 15, 30))

    print(f"\nPEPPER server PnL (submission 127989): {SERVER_PNL['INTARIAN_PEPPER_ROOT']}")
    print("Sweep PEPPER wall_offset (50 seeds each, book-replay)")
    sweep_pepper(wall_offsets=[6, 8, 9, 10, 11, 12], n_seeds=50)


if __name__ == '__main__':
    main()
