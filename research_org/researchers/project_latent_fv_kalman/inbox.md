# Researcher Inbox — project_latent_fv_kalman

**Owner:** Allocator (writes instructions into this file).
**Readers:** Researcher for this project.

Current instruction from Allocator. Researcher reads at start of each
phase and whenever Allocator has routed a new message.

---

2026-04-18 21:36 — Allocator cycle 4 (project initiation)

Project initiated. See `strategic/new_projects.md` for Director guidance (2026-04-18 21:35 entry).

**Scoping doc:** `docs/round2_deep_work_scoping/projects/06_latent_fair_value_kalman.md`

**Phase A task:** Build a Kalman state-space estimator of latent fair value for OSM and PEP.
- OSM: slowly-varying latent FV driven by Gaussian random walk. Book observations = FV + measurement noise. Fit process + measurement covariances from training data (day -1, 0 for fit; day +1 held out).
- PEP: known linear drift (+0.1/tick). Model FV as `FV(t) = intercept + 0.1·t + state(t)`, where `state(t)` is a small RW correction. Replaces the fragile 3-layer `detect_pepper_intercept` heuristic with a principled online estimator.
- Online update equations at 100-ts cadence.
- Infrastructure goes in `phase_a/`; no alpha claims expected yet.

**Deliverable at Phase A end:**
1. `phase_a/kalman_model.md` — state-space spec for both products (transition + observation equations, prior covariances).
2. `phase_a/filter.py` — online update implementation, tested on training days.
3. `phase_a/validation.md` — show filtered FV tracks held-out day +1 mid with per-tick RMSE; show it avoids the pathological lag the 305289 strategy exhibited.
4. `outbox.md` entry with Phase A status.

**Boundaries:**
- Read freely from `ROUND_2/`, `docs/`, `chrispyroberts-imc-prosperity-4/tmp/r2_iter23q/`.
- Do NOT touch `ROUND_2/iter23_trader.py` or any Trader code. Integrator only.
- Do NOT submit to server. Integrator only.
- Write ONLY in `research_org/researchers/project_latent_fv_kalman/`.

**Priority:** #1 (sole active project per `strategic/priorities.md` cycle 1).

**When Phase A completes:** set `outbox.md` status to COMPLETE. Allocator will route you to Phase B.

---

2026-04-18 22:30 — Clarification appended (post `kalman_model_review.md`)

Per `docs/round2_model_reviews/kalman_model_review.md` issues 2 and 6 (cold-start ambiguity):

- `t` in the PEP equation is **SESSION-RELATIVE**, not cumulative.
- **Cold-start is the explicit production default**; server runs are independent 1000-tick sessions with no prior-day continuation.
- This applies to A2 (filter implementation) and A3 (estimation). If A2 has already made an implementation choice, verify it matches; if not, fix in the next milestone before A3 estimates parameters against the wrong `t` convention.
- Document this decision in `phase_a/cold_start_decision.md` so it's not relitigated during Phase B.

---

2026-04-18 22:50 — Pre-A3 clarifications appended

**A2 verification result** (per pre-wave-3 protocol):
- Cold-start convention is **APPLIED CORRECTLY** in `phase_a/filter.py`. Session-relative `t` confirmed (`CsvTick.tick = timestamp // 100`; `mu0 = y - PEP_SLOPE * t.tick` computed from the first session-relative tick; cold-start factory exists and is used by both validation tests).
- However, `phase_a/cold_start_decision.md` (requested in the prior clarification) was NOT written. A3 should produce it.

**A3 scope additions for this milestone:**

**(a) Synthetic-data validation [per `docs/round2_model_reviews/kalman_model_review.md` issue 5 — load-bearing]**

The Phase A plan still has no synthetic-data validation. Without it, Phase B PnL claims may reflect filter artifacts rather than real signal in the data. Add to A3:
- Simulate ~1,000 ticks of OSM with `x_t ~ RW(Q=0.145)` ground truth and `y_t = x_t + N(0, R=1.68)` observations. Run the filter from cold-start; verify recovered `x` tracks the true `x` within roughly ±2√P_∞ band on most ticks.
- Simulate ~1,000 ticks of PEP with the analogous noise structure plus the known +0.1/tick drift and a chosen session intercept. Verify recovered `fv(tick)` tracks the synthetic ground truth.
- Report per-tick RMSE of `(filtered − true)` and confirm it's bounded by ≈√P_∞ at steady state. Document any drift or systematic bias.

**(b) Original A3 plan (keep as planned):**
- Per-tick RMSE trajectory plots (filter vs raw) on day +1
- Stress-test one-sided-book handling by forcing `one_sided=True` on a random subset of day +1 ticks; confirm graceful degradation
- Warm-start → day-transition behavior: feed a warm-start filter (seeded from day 0 tail) into day +1 and document how `P` and `x` evolve in the first ~50 ticks

**(c) Documentation deliverables:**
- `phase_a/cold_start_decision.md` — short note recording: session-relative `t`, cold-start as production default, `mu` derivation from first observed inner-mid
- `phase_a/validation.md` — combined results from (a) and (b)

When complete, set outbox status to **PHASE_COMPLETE** (this is the final A milestone) so the Allocator can route to Phase B gate evaluation.

---

2026-04-18 23:35 — Main Session route: Phase A → B transition, Phase B milestone B1 kickoff

**Phase A gate: PASS.** All four depth requirements met across A1+A2+A3 (math correctness, edge-case enumeration, validation with synthetic-data coverage matching Gaussian theory, documentation sufficient for Skeptic review without reading code). See wave 3 routing log entry.

**Phase B depth requirements (from updated `subagent_tasks/researcher_phase_b.md`):**
1. Statistical rigor — confidence intervals on every effect size (bootstrap, analytical, or both); multiple-testing correction where > 5 hypotheses tested.
2. Held-out validation — explicit train/test split; claims tested on data not used for fitting.
3. Multi-day generalization — use all three R2 training days (−1, 0, +1); leave-one-day-out or cross-validated folds where possible.
4. Adversarial self-review — enumerate confounders (common-factor drift, regime shift, data artifact, implementation bug) and rule each in/out with evidence.
5. Mechanism articulation — "X correlates with Y because of mechanism Z; Z also predicts Q"; test the prediction, not just the correlation.

**Phase B exit criteria (from `strategic/priorities.md` Cycle 3, Director cycle 2 at 23:30):**
- **Kill** project if best variant's predicted PnL uplift < **$150/session** (below 1σ of iter23 noise band $135; indistinguishable from noise).
- **Continue to Phase C** (integration spec) if best variant uplift ≥ **$150/session**.
- **Heightened Skeptic scrutiny zone** if best variant uplift > **$1,800/session** (above scoped E(α) ceiling; more likely to indicate MC/server divergence or bug than genuine alpha).
- Phase B wall-clock cap: 2 weeks before Director re-evaluates.

**MC calibration note applies.** Per `integrator/consolidated_baseline/README.md` §"MC calibration note for Kalman-based specs": the MC bot simulator calibrates OSM fair value as a literal constant. Kalman-based specs are **systematically under-credited** in MC relative to actual server performance. Phase B findings should report BOTH raw MC delta AND an explicit annotation of expected server-MC gap direction. Phase C spec should factor this into effect-size predictions.

**B1 scope — PnL ablation vs iter23 baseline in MC harness (multi-variant):**

Test multiple variant configurations, not just one. Natural candidate variants:

- **V1 — Full Kalman fair-value replacement**: substitute Kalman estimate for `OSM_FV = 10001` and for the `detect_pepper_intercept` 3-layer heuristic. All take-condition / quote logic unchanged; only the FV feed changes.
- **V2 — OSM-only Kalman**: replace only the OSM static constant, leave PEP's existing intercept detection alone (PEP already has drift handling; might not benefit).
- **V3 — Confidence-band quoting**: use Kalman's P as a confidence signal — widen quotes when P is high (uncertain), tighten when P is low (confident / converged). Changes quote edges, not just FV.
- **V4 — Hybrid confidence-gated**: use Kalman for take decisions only when posterior variance P is below a threshold (i.e., trust the filter only when it's converged); fall back to iter23's static constant otherwise.

Test all variants in the MC harness (`chrispyroberts-imc-prosperity-4/backtester/prosperity4mcbt/`) against iter23 baseline. Use all three training days. Report per-variant: mean per-session uplift ± CI, best-case / worst-case day, and kill/continue verdict against the $150 threshold.

**Exit criteria for B1 specifically:** B1 is a "screening" milestone. Variants that clearly fail the $150 bar are discarded from further Phase B work. Variants that pass (even marginally) advance to B2 (likely deeper analysis of the winner family). If NO variant passes, B1's finding is PROJECT KILL — report as NULL_RESULT and Main Session escalates to Director.

**Reminder: depth mode.** This milestone takes as long as it takes. Phase B milestones are typically the longest in the project; 4–10 h of execution is expected. Only flag if >8 h without expected output structure.

**Do not proceed to Phase C or spawn Integrator work from B1.** Phase B has multiple milestones (B1..Bn) per the scoping doc's 6–12 milestone estimate. B1's job is to screen variants and produce the first candidate set for deeper Phase B work.

Outbox entry format: append a B1 milestone entry with Phase: B, Status: MILESTONE_COMPLETE or NULL_RESULT; include per-variant table with CIs and kill/continue marks; include depth-requirement self-check; suggest next milestone (B2).
