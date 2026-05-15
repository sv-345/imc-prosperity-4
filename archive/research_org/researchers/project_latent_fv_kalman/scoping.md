# Scoping — project_latent_fv_kalman

**Owner:** Researcher on this project.
**Readers:** Director, Allocator, Skeptic.

---

Project: **latent_fv_kalman**

## Angle
The baseline iter23 uses a hardcoded `OSM_FV = 10001` as the primary
gate in the OSM take-condition, plus a 3-layer heuristic
(`detect_pepper_intercept`) for PEP FV. The iter12 post-mortem
(`ROUND_2/305289/analysis.md`) traced the largest single leak to the
stale OSM_FV: R2 mean mid is ~10,004, not 10,001, and the
mis-calibration drove one-sided OSM inventory (−76 final) and
systematically wrong-side fills. This project replaces both static FV
references with online Kalman state-space estimates that adapt to the
observed market distribution within a single session.

## Deliverable
Phase C spec will contain:
- Replacement for the `fv = OSM_FV` and `detect_pepper_intercept` code paths in `_trade_osmium` / `_trade_pepper`
- Per-tick online update equations (no look-ahead, no batch re-fit)
- Warm-start priors estimated from training days −1 and 0
- Filter noise parameters with ±20 % sensitivity envelope per MC gates

## Effort estimate
- Phase A — 6–10 h (state-space model + online filter + day −1/0 fit + day +1 validation)
- Phase B — 8–12 h (held-out PnL comparison, sensitivity, ablation vs iter23)
- Phase C — 3–5 h (minimum-diff spec against iter23)
- Total — 17–27 h

## Success probability
40 % (per `docs/round2_deep_work_scoping/recommendation.md` ranking).

## Data dependencies
- `ROUND_2/prices_round_2_day_{-1,0,1}.csv` — fit + held-out
- `ROUND_2/trades_round_2_day_{-1,0,1}.csv` — trade intensities for measurement-noise calibration
- `chrispyroberts-imc-prosperity-4/tmp/r2_iter23q/session_summary.csv` — iter23 MC baseline for PnL ablation
- `ROUND_2/iter23_trader.py` — READ ONLY; baseline for minimum-diff spec
- `ROUND_2/305289/analysis.md` — leak diagnosis that motivates the project

## Non-goals
- Not designing new take-condition logic (Project 03 Hawkes owns that)
- Not regime-switching FV (Project 02 owns that)
- Not changing the PEP deterministic slope 0.1 assumption (well-validated; out of scope)
- Not tuning OSM outer edge=20 or PEP recycle thresholds (iter-tuning territory, not depth research)
- Not touching Trader code (Integrator-only)
