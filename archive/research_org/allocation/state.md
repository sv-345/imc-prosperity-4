# Allocation State

**Owner:** Main Session (overwrite each wave).
**Readers:** all roles.

---

## Wave 4 — 2026-04-19 03:35 (Phase B entry; first alpha-relevant findings)

**HALT check:** empty at wave start and end.

**Subagents spawned (1):**
1. Researcher / `latent_fv_kalman` / Phase B milestone B1 (PnL ablation, Kalman FV variants vs iter23 in MC harness) — returned MILESTONE_COMPLETE with NULL_RESULT verdict against the $150/session threshold, 4.0 h (in-range for Phase B depth mode).

**Active projects:**
| project | phase | milestones done / est remaining | current status | next |
|---|---|---|---|---|
| latent_fv_kalman | B | 4 done (A1, A2, A3, B1) / 5–11 Phase B milestones remaining (6–12 scoped) | **B1 NULL_RESULT vs $150 threshold** — Director decision required | Director cycle to confirm kill vs authorize B2 book-replay cross-check |

**Pending inboxes:** skeptic/inbox.md empty; integrator/inbox.md empty.

**Open escalations:** 0 explicit; **1 implicit** — spinoff iter23 bug finding (see wave report) worth Director review for possible standalone bugfix spec.

**Baseline status:** iter23 @ `ROUND_2/iter23_trader.py`, 5-sample mean 9.641 per-tick (unchanged).

**Circuit breaker:** ARMED (HALT empty, no submissions this wave).

**Autonomy:** active. No submissions this wave (Researcher-only; no Phase C spec produced).

**B1 summary (for Director input):**
- 6 Kalman variants + 1 non-Kalman control, 800 MC sessions total.
- Best Kalman variant (V5 PEP-only): +$11–12 per 1,000-tick server-equivalent session (MC: +$111–125 per 10,000-tick MC session).
- $150/session continue threshold **not crossed** by any variant — ratio ~0.07.
- V2 (OSM-only Kalman) went significantly NEGATIVE (−$95/10k-session) confirming the MC calibration note's warning (MC's hardcoded `OSM_FV = 10001` is perfectly tuned; Kalman adds noise relative to MC ground truth).
- V6 (non-Kalman control) revealed a latent iter23 PEP FV bug worth +$10/10k-session → see wave report.

**Next-wave readiness:** Director decision required before wave 5. Options: (a) accept kill per Cycle 3 exit criteria; (b) authorize B2 book-replay harness cross-check before kill (addresses MC structural bias; ~2 h subagent work); (c) address spinoff iter23 bug as separate Integrator work independent of Kalman decision.
