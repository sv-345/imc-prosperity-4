# New Projects

**Owner:** Director (append-only).
**Readers:** Allocator (primary).

---

2026-04-18 21:35 — Director cycle 1

Project: **latent_fv_kalman**
Scoping doc: `docs/round2_deep_work_scoping/projects/06_latent_fair_value_kalman.md`
Researcher: new
Initial guidance: Build a Kalman state-space estimator of latent fair value for OSM and PEP, replacing the hardcoded `OSM_FV = 10001` constant (identified as the primary leak in `ROUND_2/305289/analysis.md`). Phase A: state-space model and online filter. Phase B: held-out validation on day +1, sensitivity on filter noise parameters, demonstration that replacing static FV with filtered estimate improves the take-condition firing on OSM. Phase C: minimum-diff spec against baseline iter23 (`ROUND_2/iter23_trader.py`). Target alpha: $500–$1,800 per 1,000-tick server session. MC gate: per-tick ≥ 10.028 (iter23 baseline), P05 ≥ 9.5.
Expected effort: 17–27 h total (Phase A: 6–10 h, Phase B: 8–12 h, Phase C: 3–5 h).
Expected probability of success: 40 %.

---

2026-04-19 — Main Session routing (exploration → framework)

Project: **project_osm_dynamic_gate**
Source: exploratory session (not standard phase work). Evidence in `exploration/strategy_sketch.md`, `exploration/validated_rule.md`, `exploration/candidate_rules.md`. Confirms the bug diagnosed against iter12 in `ROUND_2/305289/analysis.md` is still present in iter23.
Status: Phase C spec queued for Skeptic at `research_org/skeptic/inbox.md`. Phase A/B phases skipped — exploration artifacts stand in.
Scoping doc: `exploration/validated_rule.md`
Spec path: `research_org/researchers/project_osm_dynamic_gate/phase_c/specification.md`
Self-review: `research_org/researchers/project_osm_dynamic_gate/phase_c/self_review.md`
Expected uplift: **$250–$350/session point estimate** (CI $150–$550); crosses Cycle 3 continue threshold ($150) with the point estimate. Independent diagnostic in 305289/analysis.md agrees on $2–4k/10k-tick-day magnitude.
Falsification threshold: < $50/session MC uplift.
Skeptic notes: spec bypassed standard A/B phases. Scrutinize validation rigor accordingly; exploration has 3-day data + t-stats |t|=18–95 + 94 % participation-rate support, but lacks CV folds / multiple-testing correction / pre-registered hypotheses. Skeptic inbox entry details the tensions.
Integration timing: expected to ship BEFORE Kalman Phase B completes (only one spec in flight, trivial 3-line diff). Kalman Phase B (if resumed) will run against updated baseline.
Orthogonality claim: the exploration and this spec claim Rule 2 (OSM dynamic gate) is code-level orthogonal to Kalman Phase C. Integrator's MC gate is where this is empirically verified.

Update 2026-04-19T04:43:24Z: FALSIFIED AND ARCHIVED
Backtested on 3 R2 training days via prosperity3bt: all variants
regressed vs iter23 baseline by $196-$2,487 over 3 days.
Mechanism: iter23's static gate implicitly enforced mean-reversion
that dynamic gate removed. Spec pulled from Skeptic queue.
Archived to research_org/archive/project_osm_dynamic_gate_falsified_2026-04-19/.
