# Review — `kalman_model.md` (project_latent_fv_kalman, Phase A milestone A1)

**Reviewer role:** Microstructure / quant sanity layer for upstream infrastructure (this is the human-judgment gate that Skeptic doesn't cover for Phase A).
**Date:** 2026-04-18
**Subject file:** `research_org/researchers/project_latent_fv_kalman/phase_a/kalman_model.md` (520 lines)
**Reference reads:** scoping.md; `docs/round2_deep_work_scoping/projects/06_latent_fair_value_kalman.md`; `docs/round2_deep_work_scoping/data_inventory.md`; `chrispyroberts-imc-prosperity-4/docs/round2_model.md`; `ROUND_2/iter23_trader.py`.

---

## Overall verdict

**SOUND_WITH_MINOR_ISSUES** — proceed to A2.

The mathematical core (RW + iid Gaussian noise → Kalman) is textbook-correct, identification holds, the variance decomposition is right, and every data field the spec uses appears in `data_inventory.md`. Parameter counts are well under the red-flag threshold (Q + R + INFLATE per product = 3 free params; ≤5 per product). The one-sided-book regime is handled.

The issues below are real but don't gate A2 implementation — they're things the Researcher should resolve during A3 validation and B comparison, not before writing `filter.py`.

---

## Key findings

1. **Math and identification are clean.** The variance decomposition `R̂ = -Cov_1(Δy)`, `Q̂ = Var(Δy) - 2R̂` is the standard moment estimator for a RW + iid noise model. ACF(Δy) clustering tightly at -0.49 across all six day×product combinations is exactly the signature this filter is designed for. Q and R are jointly identifiable (not just up to a ratio); the spec uses this correctly.

2. **The OSM motivation is overstated by one outlier session.** §1.1 quotes the per-day clean means as 10000.83 / 10001.58 / 10000.15 — all within ±1 of 10001 — and then cites the 305289 session at 10004 as proof of "session-mean drift ±3 ticks." Three training days agreeing within ±1 vs one server session at +3 is one observation, not a population. The MC calibration in `chrispyroberts.../docs/round2_model.md` independently picks 10001 as constant FV. The Kalman is still the right *general* tool, but the "FV is non-stationary across sessions" headline is leaning on a single data point.

3. **PEP intercept handling for production server sessions is ambiguous.** §3.3 argues for "no session reset" because training-day intercepts differ by exactly +1000 (the cumulative drift). That's true for the training tape, where days are chained continuous time. But R2 server sessions are independent 1000-tick runs (per `r2_mechanics.md` and `data_inventory.md`). The spec mixes "warm-start from prior-day tail" (§3.5) with this chained-time framing, but production has no prior-day tail accessible — the cold-start path (`μ̂ = first observed _inner_mid - 0.1·tick_0`) is what will actually run on the server. **The spec should clearly mark cold-start as the production default** and treat warm-start as a Phase B / training-only construct.

4. **Two different `_inner_mid` definitions create an apples-to-oranges risk.** §2.2 reuses iter23's `_inner_mid` (vol ∈ [10,15], spread ∈ [15,17]) for OSM. §3.7 introduces a NEW PEP-style inner-mid (vol ∈ [8,12]) that isn't in iter23. The current iter23 PEP path uses `detect_pepper_intercept` (3-layer fallback). Phase B's PnL ablation needs to be explicit about whether the comparison is `iter23_FV_pipeline` vs `Kalman_with_new_inner_mid` (mixing two changes) or vs `Kalman_with_iter23_FV_inputs` (clean A/B). The ambiguity isn't a model defect but it will bite at Phase B if not resolved now.

5. **No synthetic-data validation in the plan.** The spec's §6 lists "validation.md (milestone A3)" as held-out *real* day +1 only. There's no plan to generate data from the assumed model with known Q, R, then verify the filter recovers them. Without this, a Phase B "Kalman beats iter23 by $300" claim is hard to disentangle from "the filter happened to fit the noise on day +1." Adding a 30-minute synthetic recovery test before A3 would let Phase B claims stand on a stronger footing.

6. **State dimension is fine for `traderData`.** OSM is 1 scalar (`x_t`); PEP is 1 scalar (`s_t`) with `μ̂` as a frozen constant — total ≤4 floats per product including `P`. Comfortably under 3 kB.

7. **Honest about scope, but two minor consistency issues with non-goals.** Scoping.md says "Not changing the PEP deterministic slope 0.1 assumption." The 2-dim fallback in §3.4 (slowly-varying `μ_t`) effectively allows the *intercept* to drift, which means the empirical slope `(FV_T - FV_0) / T` could differ from 0.1. Probably still in spirit (slope is fixed, intercept moves), but worth a one-line acknowledgment. Separately, the filter doesn't condition on trade flow per §4.5 — that's correctly out of scope (Project 03 Hawkes territory).

---

## Specific concerns

### 1. §1.1 — single-session "10004" doesn't establish session-to-session FV drift

- **Location:** lines 30–48
- **Issue:** Three training-day clean means (10000.83 / 10001.58 / 10000.15) are within ±1 of 10001. The "drift ±3 ticks session-to-session" framing rests on the 305289 session at 10004. That's a sample of one. The MC calibration (`docs/round2_model.md` §1.1) independently uses 10001 as a constant.
- **Why it matters:** Phase B will measure "improvement vs hardcoded 10001". If the true session-mean FV genuinely *is* near 10001 in most sessions, the Kalman's adaptive estimate will mostly track 10001 too, and the PnL improvement will be in the noise except on outlier sessions. The motivation should reflect that this is "robustness against rare drift sessions," not "the constant is consistently wrong."
- **Suggested fix:** Either (a) gather more server sessions to verify 305289 isn't an outlier, or (b) reframe the motivation to "low-cost insurance against drift sessions" rather than "the constant is structurally wrong."

### 2. §3.3 / §3.5 — PEP warm-start vs cold-start is ambiguous for production

- **Location:** lines 296–311 (warm-start framing), 327–342 (warm vs cold start)
- **Issue:** The chained-time argument for "no session reset" is empirically true on the training tape but doesn't apply to R2 server sessions, which are independent 1000-tick runs. The Phase C deliverable will run on the server, where only cold-start is reachable.
- **Why it matters:** If A2 ships an implementation that defaults to warm-start, it will silently fall back to cold-start on the server (no prior-day tail in `traderData`), but the spec's §3.3 caveat ("the current day's μ may need a +1000/-1000 jump") could be read as "use the chained intercept" — which would be wrong for the server.
- **Suggested fix:** Explicitly mark cold-start (line 339) as the production default. Move warm-start to a "training-only / Phase B comparison" subsection. Verify A2's API doesn't make warm-start the default constructor.

### 3. §2.2 vs §3.7 — different `_inner_mid` definitions for OSM and PEP

- **Location:** lines 96–116 (OSM uses iter23's `_inner_mid`); lines 372–384 (PEP defines a new one with vol ∈ [8,12])
- **Issue:** iter23's PEP path uses `detect_pepper_intercept`'s 3-layer fallback, not a single-layer inner-mid. The spec's PEP `_inner_mid_pep` is a NEW construct that doesn't exist in iter23.
- **Why it matters:** Phase B's "Kalman vs iter23" comparison conflates two changes (replace heuristic `detect_pepper_intercept` AND change the inner-mid definition). A clean A/B requires one of them held constant.
- **Suggested fix:** Be explicit in §3.7 about whether `_inner_mid_pep` is supposed to *replace* `detect_pepper_intercept` (in which case Phase B is fine) or *feed into* it as the layer-1 substitute (in which case the comparison must control for the inner-mid choice). Recommend the former — it's cleaner — but it should be stated.

### 4. §2.3 — `INFLATE = 25` is hand-picked

- **Location:** lines 117–129
- **Issue:** The choice `INFLATE = 25` for one-sided rows has no derivation; the rationale "trust the prior" is qualitative. The sensitivity envelope (§5.1) tests {10, 25, 50}, which is good, but the nominal isn't anchored.
- **Why it matters:** Mostly cosmetic — at K_∞ ≈ 0.25 and ~3.9% one-sided rows, even INFLATE = 5 would barely move the steady-state estimate. But a brief calibration note would help future readers.
- **Suggested fix:** Add a one-line back-of-envelope: e.g., "INFLATE = 25 chosen so that an inflated R is ≥ the worst-case bias of `_inner_mid`'s ±8 fallback expressed as a variance equivalent." Not blocking.

### 5. §6 — no synthetic-data validation in the milestone plan

- **Location:** lines 463–475
- **Issue:** A3/A4 (validation) is described as held-out day +1 only. No synthetic recovery test (generate data with known Q, R; verify filter posterior recovers them within sampling error).
- **Why it matters:** The reviewer prompt explicitly flagged this. Without synthetic recovery, Phase B improvements vs iter23 are hard to attribute to "filter quality" vs "fortuitous noise fit on day +1." A 30–60 minute synthetic test before A3 closes this gap cheaply.
- **Suggested fix:** Add a §6.1 milestone (call it A2.5 or A4): generate 10 sessions of synthetic data with `Q = 0.145, R = 1.68`, run the filter, verify mean posterior at steady state is within ±0.05 of true `x` and `P_∞` matches the closed-form `P_∞ = (-Q + √(Q² + 4QR))/2`.

### 6. `t` in §3 — session-relative or cumulative?

- **Location:** lines 76–78 (`tick_index = state.timestamp // 100`); used throughout §3 in `μ̂ + 0.1·t`
- **Issue:** iter23 uses `state.timestamp // 100` as session-relative tick index. The PEP equation `FV = μ̂ + 0.1·t + s_t` requires `t` to be the cumulative tick count *since the slope started* if `μ̂` is the global series intercept (10999.99 etc.). But if `μ̂` is the *session* intercept, then `t` should be session-relative.
- **Why it matters:** Mixing the two will produce a fair-value estimate off by `0.1 × (cumulative_ticks - session_ticks)` — potentially hundreds of ticks of bias.
- **Suggested fix:** State explicitly in §3.1 or §3.6: "`t = state.timestamp // 100` is session-relative; `μ̂` is the corresponding session intercept (i.e., μ̂ ≈ early-session mid)."

### 7. Sub-tension with MC calibration on the noise model

- **Location:** §1.2 motivation; cross-reference `chrispyroberts.../docs/round2_model.md` §1.1 ("OSM — constant" with σ=3.69 "dominated by bot-3 quotes flipping the top-of-book tick")
- **Issue:** The MC calibration explicitly says the σ = 3.69 in Δmid is a *structural* artifact of bot-3 quote flipping, not Gaussian iid noise. The Kalman model treats it as iid Gaussian. The ACF(-0.49) is consistent with both interpretations (iid noise OR bot-flipping), so the filter is a valid *phenomenological* model — but it's not literally what's happening.
- **Why it matters:** Mostly philosophical — the filter will work the same way. But the MC bot model (`F_t = 10001` constant in `round2_model.md`) implies that the MC simulator will not generate session-to-session FV drift, so the Kalman's marginal benefit *in MC* will be smaller than its marginal benefit *on real data*. This may explain a future "MC says +$100, server says +$500" pattern. Worth noting in advance.
- **Suggested fix:** One paragraph in §4 acknowledging that the MC calibration treats OSM FV as constant and that the filter's value on MC will be lower-bounded by what's needed to absorb bot-3 oscillation, while real-server value should include any actual session drift.

---

## Things I couldn't evaluate

- **Whether the day +1 R̂ / Q̂ values (1.696 / 0.136) are within "consistent with day −1, 0" sampling error.** The spec asserts ~30% consistency by visual inspection; I didn't compute the actual sampling distribution of these moment estimators on ~7800 samples. Could be tighter or looser than the spec claims. Not a blocker.
- **Whether the empirical Δmid distribution is actually fat-tailed enough to bite the Gaussian assumption.** §4.1 hand-waves "|Δmid| ≥ 5 in <0.5%". I didn't pull the actual histogram. If kurtosis is much larger than 3, the filter could under-react to legitimate FV moves and the held-out RMSE will reflect this.
- **Whether the `_inner_mid` filter (vol ∈ [10,15], spread ∈ [15,17]) is robust under R2's known wall asymmetries.** iter23's filter is OSM-tuned; the spec assumes it transfers cleanly. The MC model in `round2_model.md` shows OSM walls at -10/+9 (spread 19) and inner at ±8 (spread 16) — the spread filter should fit, but I didn't verify on day +1 ticks.
- **Whether iter23 actually leaks $1k from the FV miscalibration claim.** The scoping.md cites `ROUND_2/305289/analysis.md` — I didn't verify that diagnosis. If the leak is smaller than claimed, the project's expected alpha range ($500–$1800) is off.

---

## Summary action items

For the Researcher (to address in A2 / A3, not blocking A2):

1. Make cold-start the explicit production default for PEP (concern #2).
2. Decide and document: does `_inner_mid_pep` replace `detect_pepper_intercept` entirely, or just its layer 1? (concern #3)
3. Add a synthetic-data recovery test to A3 or as a new A2.5 milestone (concern #5).
4. Clarify `t` in §3 is session-relative (concern #6).
5. Consider reframing §1.1 motivation as "drift insurance" rather than "constant is wrong" until more server sessions confirm 305289 isn't an outlier (concern #1).
6. Add one paragraph in §4 about expected MC vs server divergence due to MC's constant-FV bot model (concern #7).

For the Director: no escalation needed. Wave 2 can proceed. Skeptic will catch any Phase C deviations from this spec, and the issues above are within Phase B's normal "tighten the comparison" remit.

No write to `escalations.md`. No write to `HALT.md`.
