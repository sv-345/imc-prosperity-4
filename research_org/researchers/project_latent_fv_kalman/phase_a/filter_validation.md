# Phase A, Milestone A2 — Filter Validation Results

**Project:** `latent_fv_kalman`
**Milestone:** A2 — filter implementation (`phase_a/filter.py`)
**Harness:** `python3 phase_a/filter.py`
**Date:** 2026-04-18

This document records the numerical results of the validation harness
built into `filter.py`.  Reproduce with:

    cd research_org/researchers/project_latent_fv_kalman/phase_a
    python3 filter.py

All data paths are read-only from `ROUND_2/prices_round_2_day_{-1,1}.csv`.

---

## Test 1 — Posterior P convergence to analytical P_∞

Spec ref: `kalman_model.md` §§2.4, 3.3 (variance decomposition) and
§§2.6, 3.6 (update equations).

Analytical steady-state from Riccati `P_∞ = (−Q + √(Q² + 4QR)) / 2`:

| product | Q     | R     | P_∞ analytical | P_final (fit day) | rel error |
|---------|------:|------:|---------------:|------------------:|----------:|
| OSM     | 0.145 | 1.68  | 0.42635        | 0.42636           | 0.00 %    |
| PEP     | 0.040 | 1.61  | 0.23456        | 0.23456           | 0.00 %    |

Fit day: `prices_round_2_day_-1.csv` (9,237 OSM ticks, ~9,237 PEP
ticks).  Both filters converge to P_∞ well within the ±5 % tolerance;
empirically the scalar recursion reaches steady state within 10 ticks
of cold start.

**Interpretation:** The implementation correctly applies the
predict/update recursion — the fixed-point of `P_{t+1} = (1 − K)(P_t +
Q)` with `K = (P_t + Q) / (P_t + Q + R)` matches the analytical
solution to 5 decimal places.

---

## Test 2 — Held-out day +1 one-step RMSE

Spec ref: `kalman_model.md` §1.2 (filter purpose) and §5.1 (comparison
with raw-mid baseline).

Methodology:

- **Filter RMSE:** `inner_mid[t+1] − fv_after_update[t]` where
  `fv_after_update[t]` is the filter's posterior FV estimate at tick
  `t` (for PEP, `fv(tick+1)` extrapolates with the +0.1 drift).
- **Raw RMSE:** `inner_mid[t+1] − inner_mid[t]` for OSM; for PEP we
  subtract the known +0.1/tick drift so both baselines use the same
  information about deterministic drift (apples-to-apples).

Warmup = 50 ticks (discard transient; filter converges in ~10 ticks per
Test 1 so 50 is generous).

| product | filter RMSE | raw RMSE | reduction | n pairs | one-sided ticks |
|---------|-----------:|--------:|----------:|--------:|----------------:|
| OSM     | 0.7314     | 0.7853  | 6.9 %     | 9,548   | 643             |
| PEP     | 1.2815     | 1.7404  | 26.4 %    | 9,198   | 0               |

Both filters produce one-step predictions with RMSE below the raw
baseline on held-out data.  The PEP gain is larger because the known
+0.1 slope captures most of the drift, leaving a smaller residual that
the filter smooths aggressively (K_∞ ≈ 0.14, 7-tick smoother).  OSM
gets a smaller but still positive improvement because its K_∞ ≈ 0.25
(4-tick smoother) — slightly more responsive to individual ticks, so
less noise reduction.

**Interpretation:** The filter provides measurable alpha-neutral
benefit on held-out data — it compresses bid-ask-bounce noise
relative to raw mid.  Phase B will measure whether this translates
into PnL improvement in the MC harness (out of scope here).

---

## Test 3 — Serialization round-trip

Spec ref: `kalman_model.md` §8 (traderData round-trip budget).

Format (per product):  `<tag>:<mu>,<x>,<P>,<tick>`

- OSM example:  `OSM:0.000,10001.234,1.680,9999` = 30 chars
- PEP example:  `PEP:10999.990,-0.123,1.550,9999` = 31 chars
- Pair blob:    `<osm>|<pep>` = 62 chars total.

Validation: round-tripped a filled-in `PairedKalman` through
`.serialize()` → `.deserialize()`.

| check                    | pass? |
|--------------------------|------:|
| blob size <= 200 chars   | 62    |
| product tags preserved   | ✓     |
| mu round-trip (1e−3)     | ✓     |
| x round-trip (1e−3)      | ✓     |
| P round-trip (1e−3)      | ✓     |
| tick counter preserved   | ✓     |

**Interpretation:** The compact format leaves >138 chars of headroom in
the 200-char design budget and >3,686 chars in the IMC 3,750-char
`traderData` cap.  Other state (regime counters, fallback intercepts)
can share the channel without risk.

---

## Test 4 — One-sided-book gain attenuation (smoke test)

Spec ref: `kalman_model.md` §§2.3, 2.5 (R inflation factor = 25).

With P_pred = 2.0, R_base = 1.68:

- K with full book:      `2.0 / (2.0 + 1.68) = 0.5435`
- K with one-sided R×25: `2.0 / (2.0 + 42.0) = 0.0455`

Gain attenuation factor: 0.5435 / 0.0455 ≈ 12×.  For P at steady state
(P ≈ 0.43), the ratio is even larger (~21×).  The update step still
runs — in contrast to treating `y=None` as missing — so the filter
absorbs directional information with small weight, which is the
specified behavior.

**Adversarial check:** confirmed via direct replay — passing
`one_sided=True` on every tick of a synthetic 1,000-tick stream gives
P convergence to `P_∞(Q, 25·R)` instead of `P_∞(Q, R)` (i.e., a
different steady state consistent with the higher noise regime).

---

## Overall

All four tests pass.  The implementation is ready for the A3
milestone (held-out validation on day +1 with RMSE-over-time plots
and one-sided-book stress test) and for downstream consumption in
Phase B (PnL ablation vs iter23).

Remaining gaps (NOT blockers for A2):

- No explicit day-boundary reset / state chaining test.  Warm-start
  helpers are implemented but untested under simulated day-transitions.
  Phase A3 should exercise these.
- The RMSE test measures pure one-step-ahead prediction accuracy,
  not downstream trading PnL.  Phase B handles the latter.
