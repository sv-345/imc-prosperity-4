# Routing Log

**Owner:** Allocator (append-only).
**Readers:** Director (via EOD report), all roles.

---

[2026-04-18 21:30:00] cycle 1 bootstrap — HALT empty, no routable work, sleeping
[2026-04-18 21:31:00] cycle 2 — HALT.md non-empty ("test halt"), Allocator stopping per protocol
[2026-04-18 21:32:00] cycle 3 (resume) — HALT empty again, Allocator re-bootstrapping; kill-switch test PASSED
[2026-04-18 21:35:00] cycle 4 — Director cycle 1 detected: strategic/new_projects.md updated with `latent_fv_kalman`, priorities.md rewritten
[2026-04-18 21:36:00] cycle 4 — created researchers/project_latent_fv_kalman/ from _template/; wrote Phase A kickoff to its inbox.md
[2026-04-18 22:20:00] Wave 1 — autonomy ACTIVE; spawned Researcher (latent_fv_kalman A1) + Integrator (iter23 reproduction); both COMPLETE; 5-sample baseline confirmed at 9.641/tick; no circuit breaker; next-wave target: Researcher A2
[2026-04-18 22:29:00] Wave 2 — spawned Researcher (latent_fv_kalman A2 filter implementation); COMPLETE in 1.5h; P convergence <0.01% rel err vs P_∞; held-out day+1 RMSE −6.9% OSM, −26.4% PEP; no submissions; next-wave target: Researcher A3
[2026-04-18 22:55:00] Wave 3 — first wave under depth-mode contract; spawned Researcher (latent_fv_kalman A3) to verify pre-existing A3 artifacts + close Phase A; PHASE_COMPLETE in 0.6h (verification+coverage-band extension); synthetic-data coverage 95.60%/95.82% matches Gaussian theory; Phase A → B gate PASS; no submissions; next-wave target: Researcher Phase B milestone B1 (recommend Director cycle first)
[2026-04-19 03:35:00] Wave 4 — spawned Researcher (latent_fv_kalman B1 PnL ablation) under Phase B exit criteria from Director cycle 2; MILESTONE_COMPLETE in 4.0h; 6 Kalman variants + 1 control × 100 sessions; best variant V5 (PEP-only) +$11-12/1k-session — below $150 continue threshold; NULL_RESULT per Cycle 3 exit criteria; spinoff finding: latent iter23 PEP FV bug worth +$10/10k-session detected via V6 control; no submissions; next: Director decision (kill vs B2 cross-check vs independent bugfix)
[2026-04-19 04:43:00] Off-wave (Main Session) — project_osm_dynamic_gate pulled from Skeptic inbox and archived to research_org/archive/project_osm_dynamic_gate_falsified_2026-04-19/ due to prosperity3bt backtest falsification (all variants regressed vs iter23, Δ=−$196 to −$19,724 over 3 training days). No Skeptic review occurred; no review cycle consumed. strategic/new_projects.md and skeptic/inbox.md updated. See exploration/validated_rule.md FALSIFICATION section for mechanism.



