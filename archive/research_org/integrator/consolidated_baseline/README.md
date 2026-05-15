# Consolidated Baseline — iter23

**Owner:** Integrator.
**Readers:** all roles.

The current champion Trader that all new research is compared against.
Integrator updates this directory ONLY after 3-sample server reproduction
shows improvement.

## Current baseline

- **Strategy file:** `ROUND_2/iter23_trader.py`
- **Iteration lineage:** iter12 → iter20 → iter21 → iter22 → iter23
  (iter22: defensive bot-take widening; iter23: signal-gated PEP
  recycle size)

## Server reproduction (5-sample — confirmed 2026-04-19)

| run | submission ID | total PnL (1000-tick session) | per-tick |
|---|---|---:|---:|
| 1 | (pre-bootstrap) | $9,867 | 9.867 |
| 2 | (pre-bootstrap) | $9,501 | 9.501 |
| 3 | (pre-bootstrap) | $9,673 | 9.673 |
| 4 | 300360 | $9,531.50 | 9.5315 |
| 5 | 300390 | $9,632.00 | 9.632 |
| **mean** | | **$9,640.90** | **9.641** |
| stdev | | $135 | 0.135 |

Prior 3-sample mean was $9,680 per-tick (stdev $185). The 5-sample
mean drifted −0.4% to $9,641, but stdev tightened from 0.185 to 0.135
— iter23 is now firmly above the $9,500 revert threshold on a larger
sample, not below it.

## MC per-tick prediction (iter23)

Source: `chrispyroberts-imc-prosperity-4/tmp/r2_iter23q/session_summary.csv`
(n = 100 MC sessions across days −1, 0, +1):

| statistic | per-tick |
|---|---:|
| mean | 10.028 |
| stdev | 0.135 |
| P05 | 9.771 |
| P50 | 10.022 |
| P95 | 10.234 |
| min | 9.672 |
| max | 10.392 |

**MC vs server gap:** MC over-predicts server by +4.0 % (10.028 → 9.641
on 5-sample mean; was +3.6 % on 3-sample). Known pattern; use MC for
ranking candidates, not for absolute calibration.

## Statistical significance — bootstrapping complete (2026-04-19)

Original 3-sample iter23 mean ($9,680) was ~1.4 σ above iter12. The
5-sample bootstrapping (+2 reproductions: 300360, 300390) confirmed
the baseline:

- 5-sample mean: **$9,641 per-tick** (stdev $135)
- Threshold: ≥ $9,500 per 1000-tick session → **PASS (+$141 margin)**
- Verdict: iter23 retained as baseline. iter12 revert path closed.

Neither reproduction triggered a circuit breaker. Per-tick distribution
is well within the expected noise band (1.4% stdev/mean). See
`submission_log.md` entries for submissions 300360 and 300390.

## MC gates for new specifications vs iter23

Any new spec must clear, at iter23-patched baseline:

- **Per-tick ≥ 10.028** (match iter23 MC mean, no regression)
- **P05 ≥ 9.5** (preserves margin above reversion threshold)
- **±20 % sensitivity within 20 % of nominal** (per Integrator protocol)

## Related documentation

- `docs/round2_log_analysis/` — R2 server log parsing and PnL breakdowns
- `docs/round2_postmortems/` — submission post-mortems
- `ROUND_2/knowledge/` — R2 mechanics, alpha signals, dead ends
- `ROUND_2/305289/analysis.md` — iter12 submission analysis (OSM_FV mis-calibration finding; pre-iter22 work)
- `chrispyroberts-imc-prosperity-4/iter22_trader.py`, `iter24_trader.py` through `iter26_trader.py` — neighboring iterations for diff context

## Per-tick leaderboard reference

Frontier: **$13/tick** (from bootstrap spec). Terminal condition:
sustained per-tick at or near frontier across 3+ submissions. Current
baseline is at 9.641/tick (5-sample) — room to +3.36/tick before
terminal.

## MC calibration note for Kalman-based specs

Added 2026-04-18 22:30 per `docs/round2_model_reviews/kalman_model_review.md` issue 7.

The MC bot simulator calibrates OSM fair value as a literal constant (see `chrispyroberts-imc-prosperity-4/docs/round2_model.md`, §1.1 "OSM — constant"). The `latent_fv_kalman` project treats OSM fair value as a latent random walk with measurement noise. As a result:

- MC will **systematically under-credit** Kalman-based fair-value improvements relative to actual server performance.
- The standard MC gate "per-tick ≥ baseline" may reject Kalman specs that would actually win on server.
- The standard MC-vs-server divergence threshold (15 %) is calibrated on iter23-class strategies and may not apply to Kalman specs.

**Recommended adjustments for Kalman specs:**

- **Skeptic:** do not reject Kalman specs solely on MC per-tick being flat or marginally below baseline. Look for evidence in Phase B that the filter recovers signal beyond the constant-fair model.
- **Integrator:** for the first Kalman submission, treat MC gates as a sanity check (no catastrophic regression) rather than a strict improvement threshold. Subsequent Kalman submissions can use the measured server-vs-MC delta from the first as an empirical correction factor.
- **Director:** aware that Kalman submissions may produce larger positive MC-server gaps than baseline. Adjust the 15 % divergence-escalation threshold for Kalman specs only — flag at +30 % or above for Kalman, not 15 %.

This note expires when sufficient Kalman submission data exists to recalibrate empirically (likely after 3–5 Kalman submissions).
