# Self-Review: project_osm_dynamic_gate

**Origin:** Exploratory session artifact. This spec bypassed formal Phase A/B; the exploration's visualizer + `candidate_rules.md` + `validated_rule.md` + simulator runs (`validate_rule1*.py`) served the role that a staffed Phase A/B would have served. Skeptic is asked to scrutinize the validation rigor accordingly.

## What's the most likely way this finding is wrong?

**The 724 events/day on OSM are not all capturable, and the $3,456/day edge calculation treats them as if they are.**

Specific mechanism: the exploration's event count counts every tick where an agg_bid or agg_ask appears in the book. But (a) the event is only worth full edge if we fill AT that price, (b) our `vol <= 9 or real_edge >= 2` guard rejects some of them anyway, (c) position limits (OSM ±80) will eventually bind and block further fills even when edge is available, and (d) the MC harness's 80 % quote randomization removes ~20 % of events from any given simulation seed.

If the realized capture fraction is, say, 40 % rather than the ~75 % assumed in the effect-size derivation, the per-session uplift drops to ~$130/session — below the $150 continue threshold that killed the Kalman project in wave 4. The spec could fail the Cycle 3 exit criteria even though the mechanism is real.

**Mitigations in the spec:** the falsification threshold is set at $50/session (not $150), acknowledging that MC may under-estimate and server + capture-fraction slippage may eat half of the theoretical edge. A binary pass at +$50 with a flag for "below $150 theoretical" would be the borderline outcome, and the outbox note requests Skeptic to allow that calibration.

## Strongest counter-explanation for the Phase B-equivalent pattern

The validated_rule.md's simulator numbers (take-only iter23 replica: +$3,756/day on OSM ask side) could be inflated by **unrealistic fill assumptions**. Specifically:

1. **The simulator assumes immediate fill at the aggressive quote's displayed price.** In reality, queue priority may mean another taker hits the agg quote before our order lands, leaving us unfilled. The exploration's "94 % unhit by other traders" stat argues against this — if 94 % go unhit, queue priority is not the binding constraint. But "unhit by trades this tick" is weaker than "would have been unhit had our order been in the book this tick." If our submission changes the equilibrium (increased competition for the flow), the unhit fraction could collapse post-integration.
2. **The iter23-replica simulator may not faithfully reproduce iter23's full quote stack.** If our replica is missing some quote layer that would have partially hit these prices anyway, the baseline is inflated and the uplift is overstated.

**Confounder: the 305289 analysis is not truly independent.** That analysis also used book snapshots and the same structural observation about OSM_FV. Two converging estimates derived from the same underlying data are not two independent signals — they are one signal stated twice.

**What would make me believe the counter-explanation:** if Integrator's MC delta comes in below $50/session despite the $250–$350 point estimate, it's evidence that one or more of these assumptions failed in practice.

## Why are the 964 Q3 events on OSM day 0 not just noise clustering?

(Note: the 964 figure appears not to be in the exploration docs I reviewed; the event counts I can verify are 593 of 997 day-0 OSM agg_asks concentrated in Q3 per `validated_rule.md` §"Event counts". I answer to that.)

The Q3 concentration (ticks 5000–7500) is NOT noise clustering for three reasons:

1. **It coincides with a mechanical intraday drift regime.** Day 0 mid traces show the OSM mid walking from ~10003 to ~10010 over Q3, which is exactly the window during which static `OSM_FV = 10001` fails. Under the model "agg_ask events fire when mid > 10001 and bots quote inside the market," we expect Q3 concentration. Under the null "events are Poisson," we expect uniform dispersion; day 0 Q3 is 5.9× over-represented (593/997 × 4 quartiles = 2.38× above uniform), and a chi-squared goodness-of-fit test on the four-quartile distribution would reject uniformity easily.
2. **The Q3 concentration replicates structurally.** Day −1 and day +1 also show Q3-like regimes (smaller magnitude) where event counts spike. If it were noise clustering, the specific quartile would randomize day-to-day; it doesn't.
3. **The forward-mid reversion signal survives the Q3 subset.** Conditioning on Q3-only events, the mean forward mid change is still +5.20 at k=1 (`exploration/validated_rule.md` §"Forward-mid reversion"). If Q3 events were noise, conditioning on them would attenuate the signal; instead, it strengthens. This is diagnostic of a real mechanism concentrated in drift regimes.

The underlying mechanism (book bot posts aggressive quote, it rests 1 tick, disappears) is independent of the intraday regime. The regime just determines when the quote is "aggressive" relative to mid.

## What would make me retract?

**Empirical triggers for retraction (in priority order):**

1. **Integrator MC delta < +$50/session** across all three training days. The falsification threshold. Direct empirical rejection.
2. **Server result < +$50/session** across 3-sample reproduction after Integrator submits. Bypasses MC miscalibration worries; this is the real test.
3. **Per-day MC delta shows one day with a strong negative result** (e.g., day +1 comes in at −$150/session). This would indicate either (a) the clamp is wrong for that day's drift regime, or (b) there's a confounding day-specific effect the exploration missed. Even if overall mean is positive, a single-day catastrophe is a retraction signal.
4. **The `vol <= 9` guard rejects most of the new events** in the Integrator MC runs — i.e., the newly-accessible price band is dominated by large informed flow we wouldn't want to take. Verifiable by Integrator instrumenting `take` call counts.
5. **Post-submission: server delivers −$50/session regression.** Circuit breaker would fire; at that point retract and revert.

**Methodological triggers:**

6. If Skeptic's review surfaces a confounder I didn't enumerate here and that confounder plausibly explains the +$2–4k/day signal, retract and revise.
7. If another researcher finds that iter24 through iter26 (neighboring iters in `chrispyroberts-imc-prosperity-4/`) already attempted this fix and failed on server, the exploration's framing is stale and the spec needs rework.

## Known limitations

- **One-sided books** (~1 % of ticks): gate falls back to static OSM_FV, reverting to iter23 behavior. Net: no harm, no benefit on those ticks.
- **Mid clamped to [10001 ± 10]:** if a session has mid sustained above 10011 (unlikely based on training data — max observed is ~10020 but only transiently), the clamp binds and we behave as "mid = 10011" — partial capture only. The clamp is a deliberate risk/reward trade-off.
- **Integer rounding of the gate** means when `dynamic_fv = 10003.5`, the gate snaps to 10004. Ask at 10004 is allowed (not blocked), ask at 10005 is still allowed. The half-tick rounding is a second-order effect; exploration results are not sensitive to it.
- **The spec is small (3-line diff)** which means there's little room for Integrator to go wrong. It also means the absolute effect size is bounded — this is not a $2,000/session alpha, it's a $250–350 one. Expectations should match.

## Bypassed-phase-structure disclosure (for Skeptic)

**The standard framework routes Researcher A → B → C → Skeptic.** This spec went Exploration → C → Skeptic, skipping A and B. The rationale and compensations:

- **Equivalent to Phase A (infrastructure):** the exploration built visualizer tooling (`visualize_bots.py`), event-counting pipelines (`recon.py`, `inspect_events.py`), and the per-tick inner-mid reference harness. These tools exist and are reusable.
- **Equivalent to Phase B (analysis):** the exploration produced cross-day event counts, forward-mid reversion statistics (with t-statistics), per-event edge calculations, participation-rate measurements, and simulator runs with multiple variant configurations (`validate_rule1a` through `validate_rule1g.py`). The simulator runs include a hold-out-day-style test (iter23 replica across all three training days).
- **What's weaker than standard Phase B:** no cross-validated fold structure with explicit train/test splits, no multiple-testing correction (hypotheses explored ad-hoc, not pre-registered), no adversarial confounder enumeration beyond what is in this self-review.

Skeptic should scrutinize validation rigor with the Phase B gaps in mind. The `$50/session falsification threshold` is deliberately set lower than the Cycle 3 $150 continue threshold to accommodate the weaker Phase B equivalent: even if the exploration's numbers are off by 2×, the spec should still show a detectable effect — and if it doesn't, retract.
