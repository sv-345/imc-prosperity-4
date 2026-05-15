# Priorities

**Owner:** Director (overwrite each cycle).
**Readers:** Allocator (primary), all roles.

---

Cycle 3 — 2026-04-18 23:30 (Phase A PASS; Phase B framing)

Active projects in priority order:

1. **latent_fv_kalman — DEPTH MODE, Phase B entry.**
   - Phase A PASSED (all four depth requirements met; see wave 3 routing_log entry and outbox A3 PHASE_COMPLETE).
   - Phase B produces per-variant predicted PnL uplift vs iter23 baseline (9.641/tick, $9,641/session 5-sample mean).
   - **Phase B exit criteria** (all values are per-session $ uplift over a 1,000-tick server-equivalent MC session, matching the `new_projects.md` alpha spec):
     - Kill project if best variant predicted uplift < **$150/session**.
     - Continue to Phase C (integration spec) if best variant predicted uplift ≥ **$150/session**.
     - Heightened Skeptic scrutiny if best variant predicted uplift > **$1,800/session** (above scoped range — treat as suspect until independently re-validated).
   - Phase B milestone count: estimated 6–12 per scoping.
   - **Stop conditions (in addition to the exit criteria above):**
     - Phase B null result across all variants → kill.
     - Any milestone exceeds 8 h without expected output → escalation review (per depth-mode framework).
     - Phase B wall-clock exceeds 2 weeks → Director review.

2. **Hawkes event-sequence — QUEUED.** Funding decision deferred until Kalman Phase B outcome is known. Not funded this cycle.

3. **Regime-switching — QUEUED.** Same deferral.

Notes:
- Threshold reasoning: $150 ≈ 1σ of the 5-sample iter23 noise band ($135), and sits below the iter23 precedent uplift ($263). Anything smaller is indistinguishable from noise and not worth Integrator's Phase C cost. Binary kill/continue at a single number (no "reconsider" middle band).
- $1,800 ceiling is the top of the scoping doc's `E(α | success)` range. Findings above it are more likely to indicate MC/server divergence or a bug than genuine alpha; Skeptic gets extra scrutiny budget.
- MC calibration note for Kalman specs (in `integrator/consolidated_baseline/README.md`) applies to Phase C integration — Skeptic and Integrator already informed.
- Hawkes deferral reason: framework has not yet run one project end-to-end (A → B → C → integration). Parallel projects would compete for Skeptic attention exactly when Kalman Phase C hits. Revisit after Phase B outcome.
- Projects 01 (L3) and 04 (counterparty) remain REJECTED. Project 05 (cointegration) remains de-prioritized behind 02 and 03.
