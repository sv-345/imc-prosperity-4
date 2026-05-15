# Integrator Outbox

**Owner:** Integrator (append-only).
**Readers:** Allocator (primary).

Integration cycle outcomes — MC results, submission IDs, server PnL,
baseline update status. Allocator parses and routes follow-up
(re-route to Researcher if gates failed, log to routing_log, escalate
on regression).

Format:

```
Spec: [name]
Implementation: [one-line code change summary]
MC result: per-tick X, P05 Y, sensitivity range Z
Submissions: [list of IDs]
Server results: [per-tick per submission]
3-sample mean: <after reproduction>
Baseline status: UPDATED | REVERTED | PENDING_REPRODUCTION
Notes: <anything Skeptic should know about calibration>
```

---

2026-04-18 22:18 — iter23 reproduction (5-sample bootstrap)

Spec: iter23 reproduction
Implementation: no code change — `ROUND_2/iter23_trader.py` submitted as-is twice to reach 5-sample server baseline.
New file: none (baseline file unchanged)
MC result: n/a (reproduction-only invocation; MC gate skipped per protocol)
Gate verdict: n/a (reproduction, no new spec)
Submissions: 300360, 300390
Server results:
  300360: per-tick 9.5315, total $9,531.50, delta vs 3-sample baseline (9.680) −1.5%
  300390: per-tick 9.632, total $9,632.00, delta vs 3-sample baseline (9.680) −0.5%
5-sample mean: 9.641 per-tick (stdev 0.135 across 9.867, 9.501, 9.673, 9.5315, 9.632)
  Delta vs prior 3-sample mean: −0.4% (within noise — 3-sample stdev 0.185)
Decision: baseline confirmed — iter23 remains the baseline.
  5-sample mean 9.641 ≥ 9.500 threshold per consolidated_baseline/README.md revert logic.
  Neither new sample <7.0 catastrophic; circuit breaker not applicable (reproduction of baseline, not new spec regression).
Outcome: BASELINE_CONFIRMED_5_SAMPLE
Notes:
  - Rate limiting: 10-minute cap did not block back-to-back submissions (launched ~2 min apart). CLI accepted both.
  - Time to complete: submission 1 ~2 min sim, submission 2 ~2 min sim. Total wall clock ~5 min.
  - 5-sample stdev (0.135) is TIGHTER than the initial 3-sample stdev (0.185), reducing statistical ambiguity. iter23 is now more firmly above the iter12 revert threshold.
  - MC-vs-server divergence: MC predicts 10.028 per-tick, server delivers 9.641 → MC over-predicts by +4.0% (was +3.6% at 3-sample). Pattern consistent; no escalation warranted.
  - No individual sample triggered a circuit breaker. No HALT.md write.
  - No informational escalation needed — this is the happy-path baseline-confirmation outcome, not a reproduction-did-not-hold case.
