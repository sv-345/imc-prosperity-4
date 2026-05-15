# Submission Log

**Owner:** Integrator subagent (append-only).
**Readers:** user (**primary observability surface for autonomous operation**), Director, Main Session, Skeptic.

Under autonomous-submission mode, this log is the first file the user
reads to understand what the system did between invocations. Keep it
scannable. Every submission — single, reproduction, bootstrapping —
gets one block-format entry below.

## Format

One block per submission:

```
Submission <ID> — <ISO timestamp>
Spec: <name from Skeptic approval, or "iter<N> reproduction", or "iter<N> bootstrap">
Implementation: <one-line code summary — function(s) modified, diff size>
MC pre-submit: per-tick <X>, P05 <Y>, sensitivity <Z>
Server result: per-tick <A>  (total <T> on 1000-tick session)
Delta vs baseline: <+N.N% | −N.N% | flat>  (baseline at time of submit: iter<K>, <B> per-tick)
Action: <see taxonomy below>
Skeptic note: <from approval entry, if present; else "n/a (reproduction)">
```

### Action taxonomy (use verbatim for machine-greppability)

- `submitted only` — neutral delta, no reproduction, no baseline change
- `triggered reproduction` — first submission, single-sample improvement ≥ 1 %, queued 2 reproductions
- `reproduction submission` — one of the 2 reproduction runs
- `updated baseline` — 3-sample mean improvement held; baseline pointer moved
- `reverted (reproduction did not hold)` — 3-sample mean dropped below threshold; baseline unchanged
- `circuit-breaker triggered` — per-tick regression > 5 %; HALT written; no further submissions
- `gate failed` — did not submit; MC gates failed (for completeness, logged so the sequence is auditable)

## Prominent baseline-update marker

When baseline changes, insert a header line so it's visible when
scrolling:

```
=== BASELINE UPDATE ===
iter<OLD> (<X.XXX> per-tick) → iter<NEW> (<Y.YYY> per-tick 3-sample mean)
spec: <name>
reproduction submission IDs: <id1>, <id2>, <id3>
```

## Circuit-breaker marker

When circuit breaker trips, insert:

```
!!! CIRCUIT BREAKER TRIGGERED !!!
iter<N> (spec <NAME>) — server per-tick <A> vs baseline <B> — delta <−Z%>
HALT.md written. All autonomous submissions suspended.
Review this entry + outbox.md, decide kill/revise/revert, clear HALT to resume.
```

---

## Log entries

Submission 300360 — 2026-04-19T02:14:16Z
Spec: iter23 reproduction
Implementation: no code change — identical `ROUND_2/iter23_trader.py` resubmitted for 5-sample baseline bootstrap (4th sample).
MC pre-submit: n/a (reproduction — MC gate skipped per reproduction-only protocol)
Server result: per-tick 9.5315  (total $9,531.50 on 1000-tick session)
Delta vs baseline: −1.5%  (baseline at time of submit: iter23, 9.680 per-tick 3-sample mean)
Action: reproduction submission
Skeptic note: n/a (reproduction)

Submission 300390 — 2026-04-19T02:16:33Z
Spec: iter23 reproduction
Implementation: no code change — identical `ROUND_2/iter23_trader.py` resubmitted for 5-sample baseline bootstrap (5th sample).
MC pre-submit: n/a (reproduction — MC gate skipped per reproduction-only protocol)
Server result: per-tick 9.632  (total $9,632.00 on 1000-tick session)
Delta vs baseline: −0.5%  (baseline at time of submit: iter23, 9.680 per-tick 3-sample mean)
Action: reproduction submission
Skeptic note: n/a (reproduction)

NOTE — 2026-04-19T02:18:30Z — iter23 5-sample baseline confirmed
5 server samples: 9.867, 9.501, 9.673, 9.5315, 9.632 per-tick
5-sample mean: 9.641 per-tick (stdev 0.135)
Threshold: ≥ 9.500 per-tick (per consolidated_baseline/README.md revert logic)
Verdict: 9.641 ≥ 9.500 → baseline remains iter23. No revert to iter12.
Circuit breaker NOT triggered (both new samples within normal noise band; neither <7.0 catastrophic).
Bootstrapping task complete.
