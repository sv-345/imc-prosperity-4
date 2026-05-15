# Project 06 — Latent fair-value Kalman filter

## Mechanism
Observed mid is a noisy estimate of a latent fair value (FV). Model
FV as a slowly-varying state driven by a Gaussian random walk (for
OSM) or a linear trend (for PEP), with book observations adding
measurement noise. Kalman filter the FV online. Replace the strategy's
hardcoded `OSM_FV = 10001` and `dynamic_fv = inner_mid` with the
Kalman estimate. Addresses the **primary leak identified in iter12
post-mortem** (submission 305289 analysis): R2 mean mid is 10,004,
not 10,001, and the hardcoded constant drove wrong-direction OSM
inventory.

## Required data
**AVAILABLE.**
- Per-tick mid, book levels across all 3 training days.
- Known process dynamics for PEP (slope = 0.1/tick).
- Baseline iter23 already has `detect_pepper_intercept` — a narrow-band FV detector. Kalman is the general version.

## Effort (milestone-count framing)

The hour-budget framing has been retired; see `research_org/README.md` §"On time budgets" for rationale.

- **Phase A:** estimated **5–10 milestones** — state-space spec, filter implementation, synthetic-data validation, held-out validation, one-sided-book stress test, warm-start behavior, convergence analysis, edge-case enumeration. Each milestone meets phase-A depth requirements (mathematical correctness, edge cases, validation, documentation); total wall-clock may be 1–2 weeks across waves.
- **Phase B:** estimated **6–12 milestones** — depends on what the data yields. Mandatory: main-effect estimation with CIs, multi-day cross-validation (use all three R2 training days), confounder enumeration, mechanism tests, sensitivity analyses on filter parameters, ablation against iter23. A NULL_RESULT is a possible legitimate Phase B outcome; if the filter doesn't improve on the static FV constant in PnL space, report and kill.
- **Phase C:** estimated **1–3 milestones** — specification + self-review. May expand to 2–3 if Skeptic issues NEEDS_REVISION and the Researcher iterates.
- **Total:** 12–25 milestones across Phases A–C. Wall-clock wise, this is **weeks of work across multiple research waves**, not days. Depth is the point; pacing adjusts to the work required.

## Probability of producing ≥ $500/slice
**40 %.** Highest of the 7 candidates because:
1. The diagnostic work is already done (305289 analysis pinpointed the leak).
2. The mechanism is well-understood and standard (Kalman is textbook).
3. Only 1 parameter (filter bandwidth) to tune; low overfit risk.
4. MC already has sensitivity tools that would catch regressions.

## Expected alpha conditional on success
**$500–$1,800.** Lower bound: just fixing the stale constant via online estimation. Upper bound: proper filter also captures intra-day FV drift that `_inner_mid` smooths through.

## Why fast iteration didn't capture this
iter10–iter23 iterated on parameters INSIDE the FV-gated logic but
never re-examined the FV itself. Memory `osm_edge_calibration.md` and
`osm_wall_fv_alpha.md` show multiple attempts at wall-based FV that
all regressed on server — because they were attempting to REPLACE the
gate with a different specific rule, not to GENERALIZE it via state
estimation. Kalman is the principled middle path: data-driven without
overfitting to a single book structure rule.

## Failure modes
1. Kalman estimate is dominated by low-frequency drift and ignores the high-frequency mean-reversion that MM needs; actual PnL doesn't move.
2. The memory-documented "one-sided book" ticks cause the filter to lag or misestimate FV during structural book events.
3. Tuning the noise covariances over-fits to training days; day +1 held-out shows no improvement.
4. Server vs MC divergence: MC says Kalman wins by $1 k, server says $0. Known pattern per `mc_v2_deterministic.md`.
