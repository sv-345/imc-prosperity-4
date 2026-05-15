"""Phase 3 Level 2 validation — strategy-ranking preservation.

Run all 4 submitted strategies (110534, 113620, 114525, 127989) through
book-replay, then compare MC ranking to server ranking.

Pass criterion: Spearman rank correlation ≈ 1.0 (same order).
"""
from __future__ import annotations
import statistics
from book_replay import run_replay, OSMIUM, PEPPER
from strategies_r1 import make_osmium_stable, make_pepper_trending
from strategies_others import make_osmium_stable_nopj, make_pepper_rw_mm, make_pepper_buyonly

N_SEEDS = 100  # per product per submission

# Server PnLs (from activitiesLog, final tick per product)
SERVER = {
    "110534": {"osmium": 1981.44, "pepper": 1958.60, "total": 3940.04},
    "113620": {"osmium": 2828.03, "pepper": 7286.00, "total": 10114.03},
    "114525": {"osmium": 3126.53, "pepper": 7286.00, "total": 10412.53},
    "127989": {"osmium": 3143.66, "pepper": 7577.00, "total": 10720.66},
}

# Strategy factories with submission-specific parameters
SUBMISSIONS = {
    "110534": {
        "osmium": (make_osmium_stable_nopj(fv_anchor=10000.0, edge=7, limit=50), 50),
        "pepper": (make_pepper_rw_mm(limit=50, edge=7, min_inside_qty=10), 50),
    },
    "113620": {
        "osmium": (make_osmium_stable(fv_anchor=10000.0, edge=7, min_inside_qty=15, limit=80), 80),
        "pepper": (make_pepper_buyonly(limit=80), 80),
    },
    "114525": {
        "osmium": (make_osmium_stable(fv_anchor=10000.0, edge=10, min_inside_qty=15, limit=80), 80),
        "pepper": (make_pepper_buyonly(limit=80), 80),
    },
    "127989": {
        "osmium": (make_osmium_stable(fv_anchor=10000.0, edge=12, min_inside_qty=15, limit=80), 80),
        "pepper": (make_pepper_trending(limit=80), 80),  # approximates insider-aware w/o insider
    },
}


def spearman(xs, ys):
    """Spearman rank correlation. Assumes no ties for simplicity."""
    def rank(xs):
        idx = sorted(range(len(xs)), key=lambda i: xs[i])
        r = [0] * len(xs)
        for rnk, i in enumerate(idx):
            r[i] = rnk
        return r
    rx, ry = rank(xs), rank(ys)
    n = len(xs)
    d2 = sum((rx[i] - ry[i]) ** 2 for i in range(n))
    return 1 - 6 * d2 / (n * (n * n - 1)) if n > 1 else 1.0


def main():
    print(f"Phase 3 Level 2 — strategy ranking preservation")
    print(f"Running {N_SEEDS} seeds per product per submission\n")

    results = {}  # sub_id -> {osmium: (mean, sd), pepper: (mean, sd), total: mean}
    for sub_id, cfg in SUBMISSIONS.items():
        print(f"-- {sub_id} --")
        osm_strat, osm_lim = cfg["osmium"]
        pep_strat, pep_lim = cfg["pepper"]

        osm_pnls = run_replay(OSMIUM, osm_strat, "ASH_COATED_OSMIUM",
                              n_seeds=N_SEEDS, position_limit=osm_lim)
        pep_pnls = run_replay(PEPPER, pep_strat, "INTARIAN_PEPPER_ROOT",
                              n_seeds=N_SEEDS, position_limit=pep_lim)

        osm_m, osm_sd = statistics.mean(osm_pnls), statistics.stdev(osm_pnls)
        pep_m, pep_sd = statistics.mean(pep_pnls), statistics.stdev(pep_pnls)
        total_m = osm_m + pep_m

        results[sub_id] = {
            "osmium": (osm_m, osm_sd),
            "pepper": (pep_m, pep_sd),
            "total": total_m,
        }
        svr = SERVER[sub_id]
        print(f"  OSMIUM  MC mean={osm_m:7.0f} sd={osm_sd:5.0f}  server={svr['osmium']:7.1f}  "
              f"z={(svr['osmium']-osm_m)/max(osm_sd,1):+.2f}")
        print(f"  PEPPER  MC mean={pep_m:7.0f} sd={pep_sd:5.0f}  server={svr['pepper']:7.1f}  "
              f"z={(svr['pepper']-pep_m)/max(pep_sd,1):+.2f}")
        print(f"  TOTAL   MC mean={total_m:7.0f}                 server={svr['total']:7.1f}")
        print()

    # Ranking comparison
    subs = list(SUBMISSIONS.keys())

    print("=== Rankings (best → worst) ===\n")

    for product in ("osmium", "pepper", "total"):
        mc_vals = [results[s][product] if product == "total" else results[s][product][0]
                   for s in subs]
        sv_vals = [SERVER[s][product] for s in subs]

        # Order by value descending
        mc_order = sorted(subs, key=lambda s: (-(results[s][product] if product == "total"
                                                  else results[s][product][0])))
        sv_order = sorted(subs, key=lambda s: -SERVER[s][product])

        rho = spearman(mc_vals, sv_vals)
        print(f"{product.upper():>7}  MC order:     {' > '.join(mc_order)}")
        print(f"{'':>7}  Server order: {' > '.join(sv_order)}")
        print(f"{'':>7}  Spearman ρ = {rho:.3f}")
        print()


if __name__ == "__main__":
    main()
