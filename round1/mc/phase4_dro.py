"""Phase 4 — Distributionally Robust Optimization of R1 strategy parameters.

Decision variables θ (strategy parameters):
  - OSMIUM:  edge ∈ {8, 10, 12, 14, 16, 18}, min_inside_qty ∈ {10, 15, 20, 25}
  - PEPPER:  family ∈ {buy-only, trending}; trending sell_qty ∈ {0, 4, 8, 15}

Uncertainty set Ξ (scenarios = MC parameter perturbations + session slices):
  S1 base:    calibrated params, full 2000-tick session
  S2 slow:    taker_rate × 0.7
  S3 fast:    taker_rate × 1.3
  S4 wide:    taker_qty range extended (e.g. (2,10) → (2,14) for OSMIUM)
  S5 first:   first 1000 ticks
  S6 second:  second 1000 ticks

DRO objective: maximize over θ of min over s ∈ Ξ of E_s[PnL | θ, s].

We also report:
  - EV-optimal (argmax under baseline only)
  - CVaR@5% over all scenarios (worst 5% of (scenario, seed) pairs)
"""
from __future__ import annotations
import statistics
import sys
import time
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from book_replay import run_replay, load_ticks
from mc_r1_v1 import OSMIUM, PEPPER
from strategies_r1 import make_osmium_stable
from strategies_others import make_pepper_buyonly

# ---------------------------------------------------------------------
# Scenario definition: each scenario overrides (product_params, ticks).
# ---------------------------------------------------------------------

def scenarios_for_osmium(n_ticks):
    base_ticks = load_ticks("ASH_COATED_OSMIUM")
    half = len(base_ticks) // 2
    return {
        "S1_base":   (OSMIUM, base_ticks),
        "S2_slow":   (replace(OSMIUM, taker_rate=OSMIUM.taker_rate * 0.7), base_ticks),
        "S3_fast":   (replace(OSMIUM, taker_rate=OSMIUM.taker_rate * 1.3), base_ticks),
        "S4_wide":   (replace(OSMIUM, taker_qty=(2, 14)), base_ticks),
        "S5_first":  (OSMIUM, base_ticks[:half]),
        "S6_second": (OSMIUM, base_ticks[half:]),
    }


def scenarios_for_pepper(n_ticks):
    base_ticks = load_ticks("INTARIAN_PEPPER_ROOT")
    half = len(base_ticks) // 2
    return {
        "S1_base":   (PEPPER, base_ticks),
        "S2_slow":   (replace(PEPPER, taker_rate=PEPPER.taker_rate * 0.7), base_ticks),
        "S3_fast":   (replace(PEPPER, taker_rate=PEPPER.taker_rate * 1.3), base_ticks),
        "S4_wide":   (replace(PEPPER, taker_qty=(3, 12)), base_ticks),
        "S5_first":  (PEPPER, base_ticks[:half]),
        "S6_second": (PEPPER, base_ticks[half:]),
    }


# ---------------------------------------------------------------------
# Custom PEPPER trending with configurable sell_qty (for sweep).
# The make_pepper_trending in strategies_r1 has sell_qty = min(8, lim+pos).
# Here we parameterize it.
# ---------------------------------------------------------------------

def make_pepper_trending_sq(sell_qty: int = 8, accum_thresh: int = 70, limit: int = 80,
                            wall_offset: int = 10):
    from mc_r1_v1 import OrderIntent, TickContext
    from strategies_r1 import _best_bid, _best_ask

    def strategy(ctx):
        lim = limit
        bb = _best_bid(ctx)
        ba = _best_ask(ctx)
        intent = OrderIntent()
        if bb is None or ba is None:
            return intent
        worst_bid = min(lv.price for lv in ctx.book.bid_levels_sorted())
        worst_ask = max(lv.price for lv in ctx.book.ask_levels_sorted())
        fv_from_bid = worst_bid + wall_offset
        fv_from_ask = worst_ask - wall_offset
        if abs(fv_from_bid - fv_from_ask) > 1:
            return intent
        fv = (fv_from_bid + fv_from_ask) // 2
        pos = ctx.position

        for lv in ctx.book.ask_levels_sorted():
            if lv.price >= fv:
                break
            fill = min(lv.bot_vol, lim - pos)
            if fill > 0:
                intent.bids.append((lv.price, fill))
                pos += fill

        if pos < accum_thresh:
            buy_limit = fv + 8
            for lv in ctx.book.ask_levels_sorted():
                if lv.price > buy_limit or lv.price < fv:
                    continue
                fill = min(lv.bot_vol, lim - pos)
                if fill > 0:
                    intent.bids.append((lv.price, fill))
                    pos += fill
                if pos >= lim:
                    break
            remaining = lim - pos
            if remaining > 0:
                intent.bids.append((bb + 1, remaining))
        else:
            buy_cap = lim - pos
            if buy_cap > 0:
                bid_price = min(bb + 1, fv - 1)
                intent.bids.append((bid_price, buy_cap))
            sq = min(sell_qty, lim + pos)
            if sq > 0:
                ask_price = max(ba - 1, fv + 1)
                intent.asks.append((ask_price, sq))
        return intent
    return strategy


# ---------------------------------------------------------------------
# Sweep + DRO engine
# ---------------------------------------------------------------------

def sweep_one(product_params, strategy, ticks, n_seeds, position_limit, product_key):
    pnls = run_replay(product_params, strategy, product_key,
                      n_seeds=n_seeds, position_limit=position_limit,
                      ticks=ticks)
    return pnls


def run_grid(grid, scenarios, product_key, position_limit, n_seeds):
    """Returns dict: θ_name -> {scenario_name -> list[PnL]}."""
    out = {}
    t0 = time.time()
    for cfg_name, strat in grid.items():
        out[cfg_name] = {}
        for s_name, (pp, ticks) in scenarios.items():
            pnls = sweep_one(pp, strat, ticks, n_seeds, position_limit, product_key)
            out[cfg_name][s_name] = pnls
    print(f"  (grid {len(grid)} × scenarios {len(scenarios)} × seeds {n_seeds} = "
          f"{len(grid)*len(scenarios)*n_seeds} replays in {time.time()-t0:.1f}s)")
    return out


def summarize(results):
    """For each config: per-scenario mean, min-scenario mean, overall CVaR@5%."""
    summary = {}
    for cfg, per_scen in results.items():
        per_scen_means = {s: statistics.mean(v) for s, v in per_scen.items()}
        min_mean = min(per_scen_means.values())
        avg_mean = statistics.mean(per_scen_means.values())
        # Pool all seeds × scenarios for CVaR
        all_pnls = sorted(v for seeds in per_scen.values() for v in seeds)
        cvar5 = statistics.mean(all_pnls[: max(1, len(all_pnls) // 20)])
        summary[cfg] = {
            "per_scen_mean": per_scen_means,
            "min_mean": min_mean,
            "avg_mean": avg_mean,
            "cvar5": cvar5,
        }
    return summary


def print_summary(summary, title):
    print(f"\n=== {title} ===")
    scen_names = list(next(iter(summary.values()))["per_scen_mean"].keys())
    header = f"{'config':>28} " + " ".join(f"{s:>9}" for s in scen_names) + \
             f"  {'min':>7} {'avg':>7} {'cvar5':>7}"
    print(header)
    print("-" * len(header))
    # Rank by min-mean (DRO-optimal at top)
    order = sorted(summary.keys(), key=lambda c: -summary[c]["min_mean"])
    for cfg in order:
        s = summary[cfg]
        row = f"{cfg:>28} " + " ".join(f"{s['per_scen_mean'][sn]:>9.0f}" for sn in scen_names)
        row += f"  {s['min_mean']:>7.0f} {s['avg_mean']:>7.0f} {s['cvar5']:>7.0f}"
        print(row)


def main():
    N_SEEDS = 40

    # ---- OSMIUM grid (realistic edges; MC bug at large edge patched in book_replay) ----
    osm_grid = {}
    for edge in (6, 8, 10, 12, 14, 16, 18, 20):
        for mi in (10, 15, 20):
            osm_grid[f"edge={edge:2d},mi={mi:2d}"] = make_osmium_stable(
                fv_anchor=10000.0, edge=edge, min_inside_qty=mi, limit=80)

    print("Phase 4 DRO — OSMIUM grid sweep")
    osm_scenarios = scenarios_for_osmium(None)
    osm_results = run_grid(osm_grid, osm_scenarios, "ASH_COATED_OSMIUM", 80, N_SEEDS)
    osm_summary = summarize(osm_results)
    print_summary(osm_summary, "OSMIUM (ranked by min-scenario mean)")

    # ---- PEPPER grid ----
    pep_grid = {
        "buyonly": make_pepper_buyonly(limit=80),
    }
    for sq in (0, 4, 8, 15):
        pep_grid[f"trend,sq={sq:2d}"] = make_pepper_trending_sq(
            sell_qty=sq, accum_thresh=70, limit=80, wall_offset=10)

    print("\nPhase 4 DRO — PEPPER grid sweep")
    pep_scenarios = scenarios_for_pepper(None)
    pep_results = run_grid(pep_grid, pep_scenarios, "INTARIAN_PEPPER_ROOT", 80, N_SEEDS)
    pep_summary = summarize(pep_results)
    print_summary(pep_summary, "PEPPER (ranked by min-scenario mean)")

    # ---- Final recommendation ----
    osm_best_dro = max(osm_summary, key=lambda c: osm_summary[c]["min_mean"])
    osm_best_ev  = max(osm_summary, key=lambda c: osm_summary[c]["per_scen_mean"]["S1_base"])
    pep_best_dro = max(pep_summary, key=lambda c: pep_summary[c]["min_mean"])
    pep_best_ev  = max(pep_summary, key=lambda c: pep_summary[c]["per_scen_mean"]["S1_base"])
    print("\n=== Recommendation ===")
    print(f"OSMIUM  EV-optimal:  {osm_best_ev}  (S1_base mean={osm_summary[osm_best_ev]['per_scen_mean']['S1_base']:.0f})")
    print(f"OSMIUM  DRO-optimal: {osm_best_dro} (min-scenario mean={osm_summary[osm_best_dro]['min_mean']:.0f})")
    print(f"PEPPER  EV-optimal:  {pep_best_ev}  (S1_base mean={pep_summary[pep_best_ev]['per_scen_mean']['S1_base']:.0f})")
    print(f"PEPPER  DRO-optimal: {pep_best_dro} (min-scenario mean={pep_summary[pep_best_dro]['min_mean']:.0f})")


if __name__ == "__main__":
    main()
