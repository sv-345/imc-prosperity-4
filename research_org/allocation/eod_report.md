# End-of-Day Report

**Owner:** Allocator (overwrite body every 24h from start time); Director appends strategic note at the bottom.
**Readers:** Director (primary input for cycle).

---

EOD Report — 2026-04-18 (bootstrap day)

## Routing decisions in last 24h
- Kill-switch test executed (cycles 1–3); Allocator stops on HALT, resumes on clear. PASSED.
- Director cycle 1 funded `latent_fv_kalman` (Project 06).
- Project directory creation pending (Allocator cycle 4, triggered by `new_projects.md` update).

## Active projects
| Project | Phase | Status | Time in phase | Notes |
|---|---|---|---|---|
| latent_fv_kalman | A | awaiting_launch | 0 h | Researcher not yet launched; directory created by Allocator cycle 4 |

## Skeptic activity
Reviews issued: 0 (not yet launched).

## Integrator activity
Submissions: 0 (not yet launched).
Per-tick best: 9.680 (iter23 baseline, 3-sample mean).
Baseline updates: none. 2 additional reproduction submissions queued as Integrator's first cycle.

## Escalations
Open: 0.
Resolved by Director since last EOD: 0.

## Patterns worth Director attention
- None yet — system is in bootstrap.

---

Director cycle 1 — 2026-04-18 21:35
Decisions made: 2 (funded `latent_fv_kalman` as first project; set priorities.md with single-project concentration; rejected projects 01 and 04 in scoping; queued 03 and 02)
Escalations resolved: 0 (none open)
Active project count: 1
Next user check-in suggested: 24 h after first Researcher Phase A begins (check `researchers/project_latent_fv_kalman/outbox.md` for Phase A completion status)

---

Director cycle 2 — 2026-04-18 23:30 (Phase A PASS acknowledged; Phase B framing)
Phase A → B gate: PASS. All four depth requirements satisfied per wave 3 report (math correctness, edge-case enumeration, validation, documentation). Synthetic coverage 95.60 %/95.82 % matches Gaussian theory; OSM filter −6.9 % RMSE, PEP filter −26.4 % RMSE on day +1.
Decisions made:
  1. Phase B exit criteria set: kill < $150/session uplift; continue ≥ $150/session; heightened Skeptic scrutiny > $1,800/session. Binary kill/continue at one threshold (no middle band). Reasoning anchored to 1σ noise ($135), iter23 precedent ($263), and scoped α ceiling ($1,800).
  2. Hawkes funding: Option A (continue holding). Do not fund in parallel. Framework has not yet run one project through full A → C → integration; parallel projects would compete for Skeptic attention at Phase C. Re-evaluate after Kalman Phase B outcome.
  3. Regime-switching: same deferral as Hawkes.
  4. Off-wave work process gap (wave 3 report): accept as-is; not urgent. No escalations.md entry this cycle.
Escalations resolved: 0 (none open).
Active project count: 1 (latent_fv_kalman, Phase B entry).
Stop conditions restated in priorities.md: null result → kill; 8 h milestone overrun → escalation review; 2 wk wall-clock → Director review.
Next Director check-in: after Phase B first milestone (B1) outbox entry, or on escalation.

---

Main Session note — 2026-04-19 (off-wave framework action)

Rule 2 (OSM dynamic gate) was found via separate exploratory session and routed through the framework as **project_osm_dynamic_gate**. Phase A/B skipped (exploration artifacts stand in). Phase C spec + self-review written; queued for Skeptic at `skeptic/inbox.md`. See `strategic/new_projects.md` 2026-04-19 entry for full detail.

Key facts for Director attention at next cycle:
- Independent of Kalman Phase B outcome (Wave 4 result: Kalman NULL_RESULT). OSM dynamic-gate spec claims ~orthogonality; Integrator MC gate is the empirical test.
- Expected uplift $250–$350/session (CI $150–$550) — crosses continue threshold at point estimate, borderline at CI lower bound.
- Falsification threshold set at < $50/session (lower than the Cycle 3 $150 continue bar) to accommodate weaker Phase B equivalent and possible MC under-crediting.
- Spec requests MC-gate adjustment: per-tick parity (not strict improvement) because MC hard-codes OSM_FV = 10001 (same structural bias that affected Kalman Phase B).
- Next wave will spawn Skeptic on this spec. If Skeptic APPROVES, Integrator follows and ships autonomously per the circuit-breaker-gated contract.

Kalman Phase B kill/continue decision remains open (wave 4 report). Director can address both at next cycle, or route OSM-dynamic-gate through Skeptic/Integrator first and revisit Kalman after iter24 ships.

---

Main Session note — 2026-04-19T04:43:24Z (off-wave framework action)

project_osm_dynamic_gate falsified by backtest before Skeptic review.
prosperity3bt run on 3 R2 training days showed all variants (dynamic
clamp 3/5/10; static-FV shifts 10002-10005) regressing vs iter23
baseline by Δ=−$196 to −$19,724 over 3 days. Root cause: iter23's
static 10001 gate was implicitly enforcing mean-reversion (declining
to buy asks at elevated prices during up-regimes); dynamic gate
removed this filter and bought into drift. Exploration's isolated
simulator did not model this adverse-selection dynamic.

Actions taken: spec pulled from `skeptic/inbox.md`; project directory
moved to `research_org/archive/project_osm_dynamic_gate_falsified_2026-04-19/`;
`strategic/new_projects.md` annotated with FALSIFIED AND ARCHIVED
update; `routing_log.md` off-wave entry logged.

Methodology gap for Director attention: exploration session's
validation (forward-mid signal tests + isolated simulator) did not
include a direct prosperity3bt PnL backtest, which caught regression
on first attempt. **Recommend framework amendment requiring
backtest-before-Skeptic for exploration-derived specs** — i.e. before
an exploration artifact is allowed to substitute for Phase A/B and
enter the Skeptic queue, a prosperity3bt sanity-run on training days
must be in the self-review bundle. This one action would have saved
the Skeptic cycle and the routing overhead.

Both prior candidate rules from the exploration session are now
empirically falsified (Rule 1: PEP agg_bid take — drift eats edge;
Rule 2: OSM dynamic gate — backtest regressed). The community's 20 %
alpha is not in these mechanisms.
