# Round 2 Deep-Work Scoping — Recommendation

Top 3 projects ranked by expected-value per unit effort, followed by
outright rejections.

Rank metric: `P(success) × E(alpha | success) ÷ effort_hours`.

---

## Ranking table

| # | project | P(success) | E(α \| success) | effort (h) | expected $ / h | rank |
|---|---|---:|---:|---:|---:|---:|
| 06 | Latent FV Kalman filter | 40 % | $500 – $1,800 (mid $1,150) | 22 | **$20.9/h** | **1st** |
| 03 | Hawkes event-sequence | 30 % | $500 – $2,000 (mid $1,250) | 27 | $13.9/h | 2nd |
| 02 | Multi-day regime-switching | 15 % | $400 – $1,500 (mid $950) | 28 | $5.1/h | 3rd |
| 07 | Avellaneda-Stoikov MM | 25 % | $300 – $1,200 (mid $750) | 29 | $6.5/h | (close 4th) |
| 05 | OSM × PEP cointegration | 10 % | $200 – $800 (mid $500) | 24 | $2.1/h | (last non-rejected) |
| 01 | L3 order-book reconstruction | 0 % | — | — | **REJECTED — data unavailable** |
| 04 | Counterparty-conditional quoting | 0 % | — | — | **REJECTED — data unavailable** |

---

## 1st — fund FIRST: Project 06 — Latent fair-value Kalman filter

**Why ranked #1:**
- The 305289 post-mortem explicitly identified stale `OSM_FV = 10,001` as the largest single addressable leak. Project 06 is the direct fix.
- Highest P(success) of the feasible set (40 %) because the diagnostic work is already done — the project just needs to build the estimator.
- Shortest scoped effort (17–27 h) of any non-rejected project.
- Low overfit surface: one bandwidth parameter, standard Bayesian state-space model, both products share infrastructure.

**Fund this single project first.** It is Director's first
`new_projects.md` entry. If it produces a clean Phase B result,
Integrator can ship against iter23 baseline before the next project
is Phase C complete.

## 2nd — queued: Project 03 — Hawkes event-sequence modeling

Second priority once Project 06 is past Phase A. Tackles a different
leak category (adverse selection timing) and complements rather than
competes with Kalman FV. If both deliver, they stack.

## 3rd — queued: Project 02 — Multi-day regime-switching

Distant 3rd because of small-N risk (3 days) and low online-inference
confidence on 1,000-tick server runs. Only fund after Projects 06 and
03 have either shipped or null-resulted.

---

## REJECTED outright

### Project 01 — L3 order-book reconstruction
Order IDs are not in the exposed tape. No amount of analysis fixes
that. **Kill at scoping.** Archive for future-round revival only.

### Project 04 — Counterparty-conditional quoting
Participant IDs are empty strings in all trade records. No signal to
condition on. **Kill at scoping.** Archive similarly.

### Project 05 — Cross-product cointegration (not killed, but de-prioritized)
Not killed because the data supports the work, but P(success) ≈ 10 %
and expected alpha is small ($200–$800). If the top 3 produce nulls,
reconsider. Otherwise, do not fund before Project 02.

---

## Calibration disclaimer

If every surviving project came back at 50 %+ success probability,
the scoping would be unreliable. These range 10–40 %, clustered
correctly around the "most deep work fails" prior. If Director
disagrees with a specific estimate, the right lever is to adjust the
probability here, not to fund blindly.

## File paths referenced

- Baseline: `ROUND_2/iter23_trader.py`
- iter12 post-mortem that motivates Project 06: `ROUND_2/305289/analysis.md`
- Data inventory: `docs/round2_deep_work_scoping/data_inventory.md`
- Per-project scoping: `docs/round2_deep_work_scoping/projects/*.md`
- R1 precedent PnL breakdown: `docs/round1_postmortem/`
