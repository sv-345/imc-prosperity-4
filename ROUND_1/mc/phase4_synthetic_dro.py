"""Phase 4 cross-check: DRO sweep using SYNTHETIC MCSim (not book-replay).

Purpose: confirm that the DRO-optimal strategy identified under recorded
book-replay remains optimal when bot books are freshly sampled from the
calibrated parameters. A ranking match between the two harnesses is strong
evidence that the DRO recommendation is robust to book realization and not
an artifact of the single recorded session.

Scenarios (6):
  S1_base      baseline calibration
  S2_slow      taker_rate × 0.7
  S3_fast      taker_rate × 1.3
  S4_noisy     fv_sigma × 1.5 (OSMIUM) / fv_drift × 1.5 (PEPPER)
  S5_sparse    wall_presence_rate × 0.8 (more one-sided books)
  S6_widesize  taker_qty extended

Note: edges kept ≤ 20 — MCSim has no taker price-band, so deep-edge fallback
exploits the same MC bug fixed in book_replay. Realistic edges avoid this.
"""
from __future__ import annotations
import statistics
import sys
import time
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from mc_r1_v1 import OSMIUM, PEPPER, MCSim
from strategies_r1 import make_osmium_stable
from strategies_others import make_pepper_buyonly
from phase4_dro import make_pepper_trending_sq


def osmium_scenarios():
    return {
        "S1_base":     OSMIUM,
        "S2_slow":     replace(OSMIUM, taker_rate=OSMIUM.taker_rate * 0.7),
        "S3_fast":     replace(OSMIUM, taker_rate=OSMIUM.taker_rate * 1.3),
        "S4_noisy":    replace(OSMIUM, fv_sigma=OSMIUM.fv_sigma * 1.5),
        "S5_sparse":   replace(OSMIUM, wall_presence_rate=OSMIUM.wall_presence_rate * 0.8),
        "S6_widesize": replace(OSMIUM, taker_qty=(2, 14)),
    }


def pepper_scenarios():
    return {
        "S1_base":     PEPPER,
        "S2_slow":     replace(PEPPER, taker_rate=PEPPER.taker_rate * 0.7),
        "S3_fast":     replace(PEPPER, taker_rate=PEPPER.taker_rate * 1.3),
        "S4_noisy":    replace(PEPPER, fv_drift=PEPPER.fv_drift * 1.5),
        "S5_sparse":   replace(PEPPER, wall_presence_rate=PEPPER.wall_presence_rate * 0.8),
        "S6_widesize": replace(PEPPER, taker_qty=(3, 12)),
    }


def run_one(product_params, strategy, n_seeds, n_ticks, position_limit, fv0=None):
    pnls = []
    for seed in range(n_seeds):
        sim = MCSim(product_params, n_ticks=n_ticks, seed=seed,
                    position_limit=position_limit, strategy=strategy, fv0=fv0)
        sim.run()
        pnls.append(sim.pnl + sim.position * sim.fv)
    return pnls


def run_grid(grid, scenarios, n_seeds, n_ticks, position_limit, fv0=None):
    out = {}
    t0 = time.time()
    for cfg_name, strat in grid.items():
        out[cfg_name] = {}
        for s_name, pp in scenarios.items():
            out[cfg_name][s_name] = run_one(pp, strat, n_seeds, n_ticks,
                                            position_limit, fv0=fv0)
    print(f"  (grid {len(grid)} × scenarios {len(scenarios)} × seeds {n_seeds} = "
          f"{len(grid)*len(scenarios)*n_seeds} sims in {time.time()-t0:.1f}s)")
    return out


def summarize(results):
    summary = {}
    for cfg, per_scen in results.items():
        per_scen_means = {s: statistics.mean(v) for s, v in per_scen.items()}
        summary[cfg] = {
            "per_scen_mean": per_scen_means,
            "min_mean": min(per_scen_means.values()),
            "avg_mean": statistics.mean(per_scen_means.values()),
        }
    return summary


def print_summary(summary, title):
    print(f"\n=== {title} ===")
    scen_names = list(next(iter(summary.values()))["per_scen_mean"].keys())
    header = f"{'config':>28} " + " ".join(f"{s:>10}" for s in scen_names) + \
             f"  {'min':>7} {'avg':>7}"
    print(header)
    print("-" * len(header))
    order = sorted(summary.keys(), key=lambda c: -summary[c]["min_mean"])
    for cfg in order:
        s = summary[cfg]
        row = f"{cfg:>28} " + " ".join(f"{s['per_scen_mean'][sn]:>10.0f}" for sn in scen_names)
        row += f"  {s['min_mean']:>7.0f} {s['avg_mean']:>7.0f}"
        print(row)


def main():
    N_SEEDS = 30
    N_TICKS = 2000

    print(f"Phase 4 SYNTHETIC cross-check ({N_SEEDS} seeds × {N_TICKS} ticks)")
    print("(MCSim synthesizes books fresh — no recorded session)\n")

    # ---- OSMIUM ----
    osm_grid = {}
    for edge in (8, 10, 12, 14, 16, 18, 20):
        for mi in (10, 15, 20):
            osm_grid[f"edge={edge:2d},mi={mi:2d}"] = make_osmium_stable(
                fv_anchor=10000.0, edge=edge, min_inside_qty=mi, limit=80)

    print("-- OSMIUM synthetic sweep --")
    osm_results = run_grid(osm_grid, osmium_scenarios(), N_SEEDS, N_TICKS, 80,
                           fv0=10000.0)
    osm_summary = summarize(osm_results)
    print_summary(osm_summary, "OSMIUM synthetic (ranked by min-scenario mean)")

    # ---- PEPPER ----
    pep_grid = {
        "buyonly": make_pepper_buyonly(limit=80),
    }
    for sq in (0, 4, 8, 15):
        pep_grid[f"trend,sq={sq:2d}"] = make_pepper_trending_sq(
            sell_qty=sq, accum_thresh=70, limit=80, wall_offset=10)

    print("\n-- PEPPER synthetic sweep --")
    pep_results = run_grid(pep_grid, pepper_scenarios(), N_SEEDS, N_TICKS, 80,
                           fv0=12000.1)
    pep_summary = summarize(pep_results)
    print_summary(pep_summary, "PEPPER synthetic (ranked by min-scenario mean)")

    # ---- Recommendation ----
    osm_best_dro = max(osm_summary, key=lambda c: osm_summary[c]["min_mean"])
    osm_best_ev = max(osm_summary, key=lambda c: osm_summary[c]["per_scen_mean"]["S1_base"])
    pep_best_dro = max(pep_summary, key=lambda c: pep_summary[c]["min_mean"])
    pep_best_ev = max(pep_summary, key=lambda c: pep_summary[c]["per_scen_mean"]["S1_base"])

    print("\n=== Synthetic-MC recommendation ===")
    print(f"OSMIUM  EV-optimal:  {osm_best_ev} (S1_base mean={osm_summary[osm_best_ev]['per_scen_mean']['S1_base']:.0f})")
    print(f"OSMIUM  DRO-optimal: {osm_best_dro} (min-scen={osm_summary[osm_best_dro]['min_mean']:.0f})")
    print(f"PEPPER  EV-optimal:  {pep_best_ev} (S1_base mean={pep_summary[pep_best_ev]['per_scen_mean']['S1_base']:.0f})")
    print(f"PEPPER  DRO-optimal: {pep_best_dro} (min-scen={pep_summary[pep_best_dro]['min_mean']:.0f})")


if __name__ == "__main__":
    main()
