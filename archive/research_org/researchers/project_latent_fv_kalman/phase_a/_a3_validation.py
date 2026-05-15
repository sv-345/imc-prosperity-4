"""Phase A milestone A3 validation harness.

Generates the numerical results documented in `phase_a/validation.md`:

    Part A — Synthetic-data validation (5 seeds; OSM and PEP)
    Part B — Held-out + stress-test on day +1
        B1: per-tick rolling RMSE trajectory
        B2: randomized one-sided stress test (10 / 25 / 50 % forced)
        B3: warm-start -> day-transition behavior

Read-only with respect to A1/A2 outputs (kalman_model.md, filter.py,
filter_validation.md).  Outputs go to stdout; the markdown report
copies the numbers verbatim.

Run:  python3 research_org/researchers/project_latent_fv_kalman/phase_a/_a3_validation.py
"""

from __future__ import annotations

import math
import os
import random
import sys
from typing import List, Optional, Tuple

# Allow direct import of filter.py from the same directory
HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from filter import (  # noqa: E402
    OSM_Q,
    OSM_R_BASE,
    PEP_Q,
    PEP_R_BASE,
    PEP_SLOPE,
    LatentFVKalman,
    load_prices_csv,
)

DATA_DIR = "/Users/svelaga/Documents/IMC Prosperity/ROUND_2"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _rmse(errors: List[float]) -> float:
    if not errors:
        return float("nan")
    return math.sqrt(sum(e * e for e in errors) / len(errors))


def _mean(xs: List[float]) -> float:
    if not xs:
        return float("nan")
    return sum(xs) / len(xs)


def _std(xs: List[float]) -> float:
    if len(xs) < 2:
        return float("nan")
    m = _mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


# ---------------------------------------------------------------------------
# Part A.1 — Synthetic OSM validation
# ---------------------------------------------------------------------------


def synth_osm_one_seed(
    seed: int,
    n_ticks: int = 1000,
    x0: float = 10001.0,
    Q: float = OSM_Q,
    R: float = OSM_R_BASE,
    warmup: int = 50,
) -> dict:
    """Generate truth + obs, run filter, return summary stats."""
    rng = random.Random(seed)
    sigma_w = math.sqrt(Q)
    sigma_v = math.sqrt(R)

    truths: List[float] = []
    obs: List[float] = []
    x = x0
    for _ in range(n_ticks):
        truths.append(x)
        obs.append(x + rng.gauss(0.0, sigma_v))
        x += rng.gauss(0.0, sigma_w)

    # Cold-start filter, seeded on first observation per production convention.
    filt = LatentFVKalman.cold_start_osm()
    filt.x = obs[0]
    filt.P = 25.0
    # Mirror the production cold-start: tick0 = first_observed_tick - 1, then
    # the first update() advances to that tick.  Synthetic ticks start at 0.
    filt.tick = -1

    filtered: List[float] = []
    for y in obs:
        filt.update(y, one_sided=False)
        filtered.append(filt.x)

    # Diagnostics after warmup.
    err = [filtered[i] - truths[i] for i in range(warmup, n_ticks)]
    raw_err = [obs[i] - truths[i] for i in range(warmup, n_ticks)]
    P_inf = LatentFVKalman.steady_state_P(Q, R)
    sqrt_Pinf = math.sqrt(P_inf)
    # Coverage: fraction of per-tick errors with |err| <= 2*sqrt(P_inf).
    # For a steady-state Gaussian posterior, theory predicts ~95.4 %.
    band2 = 2.0 * sqrt_Pinf
    band1 = 1.0 * sqrt_Pinf
    cov_within_2sig = sum(1 for e in err if abs(e) <= band2) / len(err)
    cov_within_1sig = sum(1 for e in err if abs(e) <= band1) / len(err)
    max_abs_err = max(abs(e) for e in err)
    return {
        "seed": seed,
        "n": n_ticks,
        "warmup": warmup,
        "rmse_filter_vs_truth": _rmse(err),
        "rmse_raw_vs_truth": _rmse(raw_err),
        "bias_filter": _mean(err),
        "bias_raw": _mean(raw_err),
        "sqrt_P_inf": sqrt_Pinf,
        "P_final": filt.P,
        "P_inf": P_inf,
        "cov_within_2sig": cov_within_2sig,
        "cov_within_1sig": cov_within_1sig,
        "max_abs_err": max_abs_err,
    }


def synth_osm_multi_seed(seeds: List[int]) -> List[dict]:
    return [synth_osm_one_seed(s) for s in seeds]


# ---------------------------------------------------------------------------
# Part A.2 — Synthetic PEP validation
# ---------------------------------------------------------------------------


def synth_pep_one_seed(
    seed: int,
    n_ticks: int = 1000,
    mu_true: float = 12000.0,
    Q: float = PEP_Q,
    R: float = PEP_R_BASE,
    slope: float = PEP_SLOPE,
    warmup: int = 100,
) -> dict:
    """PEP synthetic: x_t = mu + 0.1*t + s_t, with s_t random walk."""
    rng = random.Random(seed)
    sigma_w = math.sqrt(Q)
    sigma_v = math.sqrt(R)

    s = 0.0
    truths: List[float] = []
    obs: List[float] = []
    for t in range(n_ticks):
        x = mu_true + slope * t + s
        truths.append(x)
        obs.append(x + rng.gauss(0.0, sigma_v))
        s += rng.gauss(0.0, sigma_w)

    # Production cold-start convention: derive mu from the first observation,
    # set tick0 = first_tick - 1.  First synthetic tick is t=0.
    mu_obs_init = obs[0] - slope * 0
    filt = LatentFVKalman.cold_start_pep(mu=mu_obs_init, tick0=-1)

    fv_filtered: List[float] = []
    for y in obs:
        filt.update(y, one_sided=False)
        fv_filtered.append(filt.fv())  # uses internal tick counter, post-update

    err = [fv_filtered[i] - truths[i] for i in range(warmup, n_ticks)]
    raw_err = [obs[i] - truths[i] for i in range(warmup, n_ticks)]
    err_early = [fv_filtered[i] - truths[i] for i in range(min(100, n_ticks))]
    P_inf = LatentFVKalman.steady_state_P(Q, R)
    sqrt_Pinf = math.sqrt(P_inf)
    band2 = 2.0 * sqrt_Pinf
    band1 = 1.0 * sqrt_Pinf
    cov_within_2sig = sum(1 for e in err if abs(e) <= band2) / len(err)
    cov_within_1sig = sum(1 for e in err if abs(e) <= band1) / len(err)
    max_abs_err = max(abs(e) for e in err)
    return {
        "seed": seed,
        "n": n_ticks,
        "warmup": warmup,
        "mu_true": mu_true,
        "mu_filter_init": mu_obs_init,
        "mu_init_error": mu_obs_init - mu_true,
        "rmse_filter_vs_truth": _rmse(err),
        "rmse_raw_vs_truth": _rmse(raw_err),
        "bias_filter": _mean(err),
        "bias_raw": _mean(raw_err),
        "rmse_first_100": _rmse(err_early),
        "sqrt_P_inf": sqrt_Pinf,
        "P_final": filt.P,
        "P_inf": P_inf,
        "cov_within_2sig": cov_within_2sig,
        "cov_within_1sig": cov_within_1sig,
        "max_abs_err": max_abs_err,
    }


def synth_pep_multi_seed(seeds: List[int]) -> List[dict]:
    return [synth_pep_one_seed(s) for s in seeds]


def summarise_synth(results: List[dict], label: str) -> None:
    rmses = [r["rmse_filter_vs_truth"] for r in results]
    biases = [r["bias_filter"] for r in results]
    raw_rmses = [r["rmse_raw_vs_truth"] for r in results]
    cov2 = [r["cov_within_2sig"] for r in results]
    cov1 = [r["cov_within_1sig"] for r in results]
    max_errs = [r["max_abs_err"] for r in results]
    sqrt_Pinf = results[0]["sqrt_P_inf"]
    print(f"\n--- Synthetic {label} ({len(results)} seeds) ---")
    print(f"  sqrt(P_inf)               = {sqrt_Pinf:.4f}")
    print(f"  RMSE(filter-truth) mean   = {_mean(rmses):.4f}  std = {_std(rmses):.4f}")
    print(f"  RMSE(filter-truth) range  = [{min(rmses):.4f}, {max(rmses):.4f}]")
    print(f"  bias(filter-truth) mean   = {_mean(biases):+.4f}  std = {_std(biases):.4f}")
    print(f"  RMSE(raw-truth)    mean   = {_mean(raw_rmses):.4f}")
    # Coverage band check — directly answers the A3 prompt's
    # "within roughly +/-2 sqrt(P_inf) on most ticks" requirement.
    print(
        f"  Fraction |err| <= 2*sqrt(P_inf) = {_mean(cov2)*100:.2f} %  "
        f"(theory for Gaussian: 95.45 %)"
    )
    print(f"  Fraction |err| <=   sqrt(P_inf) = {_mean(cov1)*100:.2f} %  (theory: 68.27 %)")
    print(
        f"  Max |filter-truth| (any tick)   = {max(max_errs):.4f}  "
        f"(= {max(max_errs)/sqrt_Pinf:.2f} * sqrt(P_inf))"
    )
    if "rmse_first_100" in results[0]:
        early = [r["rmse_first_100"] for r in results]
        print(f"  RMSE(filter-truth) first 100 ticks = {_mean(early):.4f}")
    print(f"  Per-seed RMSE(filter-truth): {[round(r, 4) for r in rmses]}")
    print(
        f"  Per-seed coverage (2-sigma): "
        f"{[round(c*100, 2) for c in cov2]}"
    )


# ---------------------------------------------------------------------------
# Part B.1 — Day +1 rolling RMSE trajectory
# ---------------------------------------------------------------------------


def rolling_rmse_traj_osm(
    day_p1_path: str, window: int = 200, warmup: int = 50
) -> Tuple[List[Tuple[int, float, float, int]], float, float, int, int]:
    """For each contiguous window of size `window`, compute filter RMSE and raw RMSE.

    Returns list of (window_start_tick, rmse_filter, rmse_raw, n_pairs)
    plus the overall (warmup-trimmed) numbers for sanity-checking against
    A2's harness.
    """
    ticks = load_prices_csv(day_p1_path, "ASH_COATED_OSMIUM")
    filt = LatentFVKalman.cold_start_osm()
    for t in ticks:
        y = t.inner_mid_osm()
        if y is not None:
            filt.x = y
            filt.P = 25.0
            break

    filt_errs: List[Tuple[int, float, float]] = []  # (tick, err_filter, err_raw)
    prev_y: Optional[float] = None
    prev_fv: Optional[float] = None
    for t in ticks:
        y = t.inner_mid_osm()
        if (
            prev_y is not None
            and y is not None
            and prev_fv is not None
            and filt.n_updates >= warmup
        ):
            filt_errs.append((t.tick, y - prev_fv, y - prev_y))
        filt.update(y, one_sided=t.one_sided())
        if y is not None:
            prev_y = y
            prev_fv = filt.fv()

    # Bucket by floor(tick / window) * window
    buckets: dict = {}
    for tk, ef, er in filt_errs:
        b = (tk // window) * window
        buckets.setdefault(b, []).append((ef, er))
    trajectory: List[Tuple[int, float, float, int]] = []
    for b in sorted(buckets):
        es = buckets[b]
        rf = _rmse([e[0] for e in es])
        rr = _rmse([e[1] for e in es])
        trajectory.append((b, rf, rr, len(es)))

    overall_filter = _rmse([e[1] for e in filt_errs])
    overall_raw = _rmse([e[2] for e in filt_errs])
    return trajectory, overall_filter, overall_raw, len(filt_errs), filt.n_one_sided


def rolling_rmse_traj_pep(
    day_p1_path: str, window: int = 200, warmup: int = 50
) -> Tuple[List[Tuple[int, float, float, int]], float, float, int]:
    ticks = load_prices_csv(day_p1_path, "INTARIAN_PEPPER_ROOT")
    mu0 = None
    tick0 = None
    for t in ticks:
        y = t.inner_mid_pep()
        if y is not None:
            mu0 = y - PEP_SLOPE * t.tick
            tick0 = t.tick
            break
    assert mu0 is not None and tick0 is not None
    filt = LatentFVKalman.cold_start_pep(mu=mu0, tick0=tick0 - 1)

    filt_errs: List[Tuple[int, float, float]] = []
    prev_y: Optional[float] = None
    prev_fv: Optional[float] = None
    for t in ticks:
        y = t.inner_mid_pep()
        if (
            prev_y is not None
            and y is not None
            and prev_fv is not None
            and filt.n_updates >= warmup
        ):
            # raw baseline includes known +0.1 drift (apples-to-apples with filter)
            filt_errs.append((t.tick, y - prev_fv, (y - prev_y) - PEP_SLOPE))
        filt.update(y, one_sided=t.one_sided())
        if y is not None:
            prev_y = y
            prev_fv = filt.mu + filt.slope * (filt.tick + 1) + filt.x

    buckets: dict = {}
    for tk, ef, er in filt_errs:
        b = (tk // window) * window
        buckets.setdefault(b, []).append((ef, er))
    trajectory: List[Tuple[int, float, float, int]] = []
    for b in sorted(buckets):
        es = buckets[b]
        rf = _rmse([e[0] for e in es])
        rr = _rmse([e[1] for e in es])
        trajectory.append((b, rf, rr, len(es)))

    overall_filter = _rmse([e[1] for e in filt_errs])
    overall_raw = _rmse([e[2] for e in filt_errs])
    return trajectory, overall_filter, overall_raw, len(filt_errs)


# ---------------------------------------------------------------------------
# Part B.2 — Randomized one-sided stress test
# ---------------------------------------------------------------------------


def stress_one_sided_osm(
    day_p1_path: str,
    forced_frac: float,
    seed: int,
    warmup: int = 50,
) -> Tuple[float, int, int, int]:
    """Force one-sided=True on a random `forced_frac` of full-book ticks.

    Returns (filter_rmse, n_pairs, n_natural_one_sided, n_forced_one_sided).
    """
    ticks = load_prices_csv(day_p1_path, "ASH_COATED_OSMIUM")
    rng = random.Random(seed)
    forced_set = set()
    n_natural = 0
    for i, t in enumerate(ticks):
        if t.one_sided():
            n_natural += 1
        else:
            if rng.random() < forced_frac:
                forced_set.add(i)
    filt = LatentFVKalman.cold_start_osm()
    for t in ticks:
        y = t.inner_mid_osm()
        if y is not None:
            filt.x = y
            filt.P = 25.0
            break
    errs: List[float] = []
    prev_y: Optional[float] = None
    prev_fv: Optional[float] = None
    for i, t in enumerate(ticks):
        y = t.inner_mid_osm()
        os_flag = t.one_sided() or (i in forced_set)
        if (
            prev_y is not None
            and y is not None
            and prev_fv is not None
            and filt.n_updates >= warmup
        ):
            errs.append(y - prev_fv)
        filt.update(y, one_sided=os_flag)
        if y is not None:
            prev_y = y
            prev_fv = filt.fv()
    return _rmse(errs), len(errs), n_natural, len(forced_set)


def stress_one_sided_pep(
    day_p1_path: str,
    forced_frac: float,
    seed: int,
    warmup: int = 50,
) -> Tuple[float, int, int, int]:
    ticks = load_prices_csv(day_p1_path, "INTARIAN_PEPPER_ROOT")
    rng = random.Random(seed)
    forced_set = set()
    n_natural = 0
    for i, t in enumerate(ticks):
        if t.one_sided():
            n_natural += 1
        else:
            if rng.random() < forced_frac:
                forced_set.add(i)
    mu0 = None
    tick0 = None
    for t in ticks:
        y = t.inner_mid_pep()
        if y is not None:
            mu0 = y - PEP_SLOPE * t.tick
            tick0 = t.tick
            break
    assert mu0 is not None and tick0 is not None
    filt = LatentFVKalman.cold_start_pep(mu=mu0, tick0=tick0 - 1)
    errs: List[float] = []
    prev_y: Optional[float] = None
    prev_fv: Optional[float] = None
    for i, t in enumerate(ticks):
        y = t.inner_mid_pep()
        os_flag = t.one_sided() or (i in forced_set)
        if (
            prev_y is not None
            and y is not None
            and prev_fv is not None
            and filt.n_updates >= warmup
        ):
            errs.append(y - prev_fv)
        filt.update(y, one_sided=os_flag)
        if y is not None:
            prev_y = y
            prev_fv = filt.mu + filt.slope * (filt.tick + 1) + filt.x
    return _rmse(errs), len(errs), n_natural, len(forced_set)


# ---------------------------------------------------------------------------
# Part B.3 — Warm-start day transition behavior
# ---------------------------------------------------------------------------


def warm_start_day_transition_osm(
    day0_path: str, day_p1_path: str, tail: int = 500, peek: int = 50
) -> Tuple[dict, List[Tuple[int, float, float, Optional[float], Optional[float]]]]:
    """Warm-start filter from last `tail` ticks of day 0; replay first `peek` of day +1.

    Returns ({summary}, list of (tick, x, P, observed_y, error_x_minus_y)).
    """
    day0 = load_prices_csv(day0_path, "ASH_COATED_OSMIUM")
    day_p1 = load_prices_csv(day_p1_path, "ASH_COATED_OSMIUM")

    # Build filter from day 0 cold-start, run full day, then take state.
    filt = LatentFVKalman.cold_start_osm()
    for t in day0:
        y = t.inner_mid_osm()
        if y is not None:
            filt.x = y
            filt.P = 25.0
            break
    for t in day0:
        filt.update(t.inner_mid_osm(), one_sided=t.one_sided())

    # Now `filt.x` ~ day-0-tail latent FV, `filt.P` ~ P_inf.
    # Build a "warm-start" using the filter's current x as the new prior mean
    # but with a moderate P0 (this is the warm-start convention of §2.5).
    warm = LatentFVKalman.warm_start_osm(x0=filt.x, P0=5.0)
    # Reset internal tick to 0 so it sees day +1's tick frame.
    warm.tick = 0

    init_x = warm.x
    init_P = warm.P
    first_y = None
    for t in day_p1:
        y = t.inner_mid_osm()
        if y is not None:
            first_y = y
            break

    trace: List[Tuple[int, float, float, Optional[float], Optional[float]]] = []
    for t in day_p1[:peek]:
        y = t.inner_mid_osm()
        warm.update(y, one_sided=t.one_sided())
        err_xy = warm.x - y if y is not None else None
        trace.append((t.tick, warm.x, warm.P, y, err_xy))

    summary = {
        "init_x": init_x,
        "init_P": init_P,
        "first_observed_y": first_y,
        "first_y_minus_init_x": (first_y - init_x) if first_y is not None else None,
        "tick4_x": trace[3][1] if len(trace) > 3 else None,
        "tick4_P": trace[3][2] if len(trace) > 3 else None,
        "tick10_x": trace[9][1] if len(trace) > 9 else None,
        "tick10_P": trace[9][2] if len(trace) > 9 else None,
        "tick50_x": trace[-1][1] if trace else None,
        "tick50_P": trace[-1][2] if trace else None,
        "P_inf": LatentFVKalman.steady_state_P(OSM_Q, OSM_R_BASE),
    }
    return summary, trace


def warm_start_day_transition_pep(
    day0_path: str, day_p1_path: str, tail: int = 500, peek: int = 50
) -> Tuple[dict, List[Tuple[int, float, float, Optional[float], Optional[float]]]]:
    day0 = load_prices_csv(day0_path, "INTARIAN_PEPPER_ROOT")
    day_p1 = load_prices_csv(day_p1_path, "INTARIAN_PEPPER_ROOT")
    mu0 = None
    tick0 = None
    for t in day0:
        y = t.inner_mid_pep()
        if y is not None:
            mu0 = y - PEP_SLOPE * t.tick
            tick0 = t.tick
            break
    assert mu0 is not None and tick0 is not None
    filt = LatentFVKalman.cold_start_pep(mu=mu0, tick0=tick0 - 1)
    for t in day0:
        filt.update(t.inner_mid_pep(), one_sided=t.one_sided())

    # Warm-start day +1: keep mu (the filter's current intercept), reset tick to 0,
    # carry the residual `s` and inflate P moderately.
    warm = LatentFVKalman.warm_start_pep(mu=filt.mu, s0=filt.x, P0=5.0, tick0=0)

    init_s = warm.x
    init_P = warm.P
    init_fv0 = warm.fv()
    first_y = None
    for t in day_p1:
        y = t.inner_mid_pep()
        if y is not None:
            first_y = y
            break

    trace: List[Tuple[int, float, float, Optional[float], Optional[float]]] = []
    for t in day_p1[:peek]:
        y = t.inner_mid_pep()
        warm.update(y, one_sided=t.one_sided())
        fv = warm.fv()
        err = (fv - y) if y is not None else None
        trace.append((t.tick, fv, warm.P, y, err))

    summary = {
        "init_s": init_s,
        "init_P": init_P,
        "init_fv_at_tick0": init_fv0,
        "first_observed_y": first_y,
        "first_y_minus_init_fv": (first_y - init_fv0) if first_y is not None else None,
        "tick7_fv": trace[6][1] if len(trace) > 6 else None,
        "tick7_P": trace[6][2] if len(trace) > 6 else None,
        "tick10_fv": trace[9][1] if len(trace) > 9 else None,
        "tick10_P": trace[9][2] if len(trace) > 9 else None,
        "tick50_fv": trace[-1][1] if trace else None,
        "tick50_P": trace[-1][2] if trace else None,
        "P_inf": LatentFVKalman.steady_state_P(PEP_Q, PEP_R_BASE),
    }
    return summary, trace


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def main() -> None:
    print("=" * 78)
    print("A3 VALIDATION HARNESS")
    print("=" * 78)

    # ---- Part A: synthetic ----
    seeds = [42, 1337, 2024, 7, 8675309]
    print("\n### Part A — Synthetic-data validation (5 seeds)")

    osm_results = synth_osm_multi_seed(seeds)
    summarise_synth(osm_results, "OSM")
    print("\n  Per-seed details (OSM):")
    for r in osm_results:
        print(
            f"    seed={r['seed']:>8}  rmse={r['rmse_filter_vs_truth']:.4f}  "
            f"bias={r['bias_filter']:+.4f}  raw_rmse={r['rmse_raw_vs_truth']:.4f}  "
            f"P_final={r['P_final']:.4f} (P_inf={r['P_inf']:.4f})"
        )

    pep_results = synth_pep_multi_seed(seeds)
    summarise_synth(pep_results, "PEP")
    print("\n  Per-seed details (PEP):")
    for r in pep_results:
        print(
            f"    seed={r['seed']:>8}  rmse={r['rmse_filter_vs_truth']:.4f}  "
            f"bias={r['bias_filter']:+.4f}  raw_rmse={r['rmse_raw_vs_truth']:.4f}  "
            f"first100_rmse={r['rmse_first_100']:.4f}  "
            f"mu_init_err={r['mu_init_error']:+.4f}"
        )

    # ---- Part B.1: rolling trajectory on day +1 ----
    print("\n### Part B.1 — Day +1 per-tick (200-tick window) RMSE trajectory")
    day_p1 = os.path.join(DATA_DIR, "prices_round_2_day_1.csv")

    traj_osm, ovr_f_osm, ovr_r_osm, n_osm, _ = rolling_rmse_traj_osm(day_p1)
    print(
        f"\n  OSM overall (warmup=50): filter={ovr_f_osm:.4f}  raw={ovr_r_osm:.4f}  n={n_osm}"
    )
    print("  window_start  rmse_filter  rmse_raw  n_pairs")
    for b, rf, rr, n in traj_osm:
        bar_filter = "*" * int(round(rf * 20))  # rough visual scale
        print(f"    {b:>10}  {rf:>10.4f}  {rr:>8.4f}  {n:>6}  {bar_filter}")

    traj_pep, ovr_f_pep, ovr_r_pep, n_pep = rolling_rmse_traj_pep(day_p1)
    print(
        f"\n  PEP overall (warmup=50): filter={ovr_f_pep:.4f}  raw={ovr_r_pep:.4f}  n={n_pep}"
    )
    print("  window_start  rmse_filter  rmse_raw  n_pairs")
    for b, rf, rr, n in traj_pep:
        bar_filter = "*" * int(round(rf * 10))
        print(f"    {b:>10}  {rf:>10.4f}  {rr:>8.4f}  {n:>6}  {bar_filter}")

    # ---- Part B.2: stress test ----
    print("\n### Part B.2 — One-sided stress test (forced 10/25/50 % on day +1)")
    print("\n  OSM:")
    print("    forced_frac  filter_rmse  n_pairs  n_natural_OS  n_forced_OS")
    base_filter, n, n_nat, n_force = stress_one_sided_osm(day_p1, 0.0, 42)
    print(f"    baseline     {base_filter:>10.4f}  {n:>7}  {n_nat:>12}  {n_force:>11}")
    for frac in (0.10, 0.25, 0.50):
        rmse_, n_, nn_, nf_ = stress_one_sided_osm(day_p1, frac, 42)
        print(f"    {frac:>10.2f}   {rmse_:>10.4f}  {n_:>7}  {nn_:>12}  {nf_:>11}")

    print("\n  PEP:")
    print("    forced_frac  filter_rmse  n_pairs  n_natural_OS  n_forced_OS")
    base_filter_p, n_p, n_nat_p, n_force_p = stress_one_sided_pep(day_p1, 0.0, 42)
    print(
        f"    baseline     {base_filter_p:>10.4f}  {n_p:>7}  {n_nat_p:>12}  {n_force_p:>11}"
    )
    for frac in (0.10, 0.25, 0.50):
        rmse_, n_, nn_, nf_ = stress_one_sided_pep(day_p1, frac, 42)
        print(f"    {frac:>10.2f}   {rmse_:>10.4f}  {n_:>7}  {nn_:>12}  {nf_:>11}")

    # ---- Part B.3: warm-start day transition ----
    print("\n### Part B.3 — Warm-start day-0 -> day +1 transition (first 50 ticks)")
    day0 = os.path.join(DATA_DIR, "prices_round_2_day_0.csv")

    sum_osm, trace_osm = warm_start_day_transition_osm(day0, day_p1)
    print(f"\n  OSM warm-start summary:")
    print(f"    init_x = {sum_osm['init_x']:.4f}  init_P = {sum_osm['init_P']:.4f}")
    print(
        f"    first day+1 observed y = {sum_osm['first_observed_y']:.4f}  "
        f"shock = {sum_osm['first_y_minus_init_x']:+.4f}"
    )
    print(
        f"    tick 4:  x = {sum_osm['tick4_x']:.4f}  P = {sum_osm['tick4_P']:.4f}"
    )
    print(
        f"    tick 10: x = {sum_osm['tick10_x']:.4f}  P = {sum_osm['tick10_P']:.4f}"
    )
    print(
        f"    tick 50: x = {sum_osm['tick50_x']:.4f}  P = {sum_osm['tick50_P']:.4f}  "
        f"(P_inf = {sum_osm['P_inf']:.4f})"
    )
    print("\n  First 12 ticks of OSM warm-start replay:")
    print("    tick     x         P         y         x-y")
    for tk, x, P, y, e in trace_osm[:12]:
        ystr = f"{y:.4f}" if y is not None else "  None  "
        estr = f"{e:+.4f}" if e is not None else "  None  "
        print(f"    {tk:>4}  {x:>8.4f}  {P:>8.4f}  {ystr:>9}  {estr}")

    sum_pep, trace_pep = warm_start_day_transition_pep(day0, day_p1)
    print(f"\n  PEP warm-start summary:")
    print(f"    init_s = {sum_pep['init_s']:+.4f}  init_P = {sum_pep['init_P']:.4f}")
    print(f"    init fv(tick=0) = {sum_pep['init_fv_at_tick0']:.4f}")
    print(
        f"    first day+1 observed y = {sum_pep['first_observed_y']:.4f}  "
        f"shock = {sum_pep['first_y_minus_init_fv']:+.4f}"
    )
    print(
        f"    tick 7:  fv = {sum_pep['tick7_fv']:.4f}  P = {sum_pep['tick7_P']:.4f}"
    )
    print(
        f"    tick 10: fv = {sum_pep['tick10_fv']:.4f}  P = {sum_pep['tick10_P']:.4f}"
    )
    print(
        f"    tick 50: fv = {sum_pep['tick50_fv']:.4f}  P = {sum_pep['tick50_P']:.4f}  "
        f"(P_inf = {sum_pep['P_inf']:.4f})"
    )
    print("\n  First 12 ticks of PEP warm-start replay:")
    print("    tick     fv          P         y          fv-y")
    for tk, fv, P, y, e in trace_pep[:12]:
        ystr = f"{y:.4f}" if y is not None else "  None   "
        estr = f"{e:+.4f}" if e is not None else "  None   "
        print(f"    {tk:>4}  {fv:>9.4f}  {P:>8.4f}  {ystr:>9}  {estr}")

    print("\n" + "=" * 78)
    print("DONE")
    print("=" * 78)


if __name__ == "__main__":
    main()
