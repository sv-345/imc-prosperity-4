# Tape-pinning falsification test — results

## TL;DR

**The spec'd density trigger (BAND=2) is structurally unfireable.** 2,819
density-signal crossings across the 3 training days produced **zero**
fills — because OSM's book goes one-sided during aggressive moments,
leaving the narrow `(fv, fv±BAND]` band empty exactly when the signal
wants to act. A widened variant (BAND=5, non-spec) fired 3 times and
returned −$195 over 3 days.

**The spec's mechanism-level predictions failed.** No fires in the
high-scheduled-% windows (0–50K, 50–100K) on any day, at either BAND.
So the claim *"density trigger fires in tape-pinned windows and fails
because prices are tape-pinned"* is not what the backtest showed. The
tape-pinning hypothesis is **neither confirmed nor falsified by this
test** — the test couldn't reach the mechanism it set out to probe.

This is a **partial** result per the spec's classification rubric.

## Raw results

### BAND=2 (per spec)

| day | base osm | var osm | Δ | signal crossings | fires |
|-----|---------:|--------:|--:|-----------------:|------:|
| 2--1 | 19,376 | 19,376 | 0 | 422 | 0 |
| 2-0  | 19,720 | 19,720 | 0 | 1,464 | 0 |
| 2-1  | 18,431 | 18,431 | 0 | 933 | 0 |
| **SUM** | **57,527** | **57,527** | **0** | **2,819** | **0** |

The signal hit |S|≥3 on 2,819 ticks but the book never had liquidity
in `(fv, fv+2]` or `[fv-2, fv)` at any of those ticks. Diagnostic on
all crossings:

| signal direction | book state | count |
|---|---|---:|
| UP (bid-density) | best ask > fv+3 | 1,123 |
| UP | best ask < fv (already caught by primary gate) | 56 |
| DN (ask-density) | best bid < fv-3 | 1,640 |
| DN | best bid ≥ fv-2 | **0** |

When bid pressure mounts, asks retreat to 10004–10005+. When ask
pressure mounts, bids are pinned at the wall (≈9985). The book is
**not tight** during aggressive regimes. The density moment and the
"scheduled-ask near fv" moment are disjoint events in OSM data.

### BAND=5 (pre-test calibration after diagnostic)

Motivation: BAND=2 is structurally degenerate. Widening to BAND=5
lets the trigger actually fire — otherwise the test cannot distinguish
"tape-pinned, no alpha" from "trigger broken". Documented here as a
one-off extension; no further tuning.

| day | base osm | var osm | Δ | fires | qty |
|-----|---------:|--------:|--:|-----:|----:|
| 2--1 | 19,376 | 19,376 | 0 | 0 | 0 |
| 2-0  | 19,720 | 19,740 | **+20** | 1 | 10 |
| 2-1  | 18,431 | 18,216 | **−215** | 2 | 15 |
| **SUM** | **57,527** | **57,332** | **−195** | **3** | **25** |

Per-bucket Δ (OSM, timestamps in thousands):

| day | 0–50K | 50–100K | 100–150K | 150–200K |
|-----|------:|--------:|---------:|---------:|
| 2--1 | 0 | 0 | 0 | 0 |
| 2-0  | 0 | 0 | 0 | 0 |
| 2-1  | 0 | 0 | 0 | −24 |

All fires were UP direction (lifting asks at 10006). One day positive
(+$20), two days zero or negative (0, −$215).

## Per-criterion evaluation (vs spec's predictions)

Spec's "tape-pinning real" criteria:

| criterion | BAND=2 | BAND=5 | verdict |
|---|:---:|:---:|:---|
| 3-day Δ ≤ 0 | ✓ (0) | ✓ (−195) | met |
| ≥ 2 of 3 days Δ ≤ 0 | ✓ (3/3 exactly 0) | ✓ (2/3) | met |
| Bucketed Δ most negative in 0–50K or 50–100K | ✗ | ✗ | **failed** |
| ≥ 20 fires/day netting ≤ $50/day | ✗ (0 fires) | ✗ (≤1/day) | **failed** |

Spec's "tape-pinning falsified" criteria:

| criterion | BAND=2 | BAND=5 | verdict |
|---|:---:|:---:|:---|
| 3-day Δ ≥ +$300, ≥ 2/3 days positive | ✗ | ✗ | not met |
| Positive bucket PnL in 0–50K or 50–100K with ≥5 fires | ✗ | ✗ | not met |

**The PnL-level prediction matched (flat or slightly negative); the
mechanism-level predictions failed.** The trigger did not fire in the
windows where tape-pinning was supposed to bite. Therefore the
overall Δ=0/−195 outcome is not evidence *for* tape-pinning — it's
evidence that this density trigger has no access to those windows at
all.

## What this means for the tape-pinning hypothesis

**Neither confirmed nor falsified.** The specific mechanism I hand-waved
through in the previous response ("density trigger fires → lifts
scheduled asks in tight band → no alpha") is structurally impossible:
density fires precisely when the book is one-sided, not when both
sides sit near fv with a scheduled ask on offer. Those are two
different regimes.

What *is* falsified: **my earlier reasoning that ruled out event-density
triggers via tape-pinning**. The reasoning was wrong in the
implication, even if the conclusion ("density triggers don't pay")
turns out to be right for some other reason. The correct stop-reason
for event-density on OSM is simpler and separate from tape-pinning:

> When the book is one-sided, there are no asks in the tight band to
> take (for UP signals) and no bids in the tight band to hit (for DN
> signals). Density triggers with narrow bands cannot fire. Triggers
> with wide bands (BAND ≥ 5) fire rarely (~1/day) and lose mid-reversion
> to fv on the fills they do take.

This is a microstructure observation, not a tape-pinning one.

## What a valid tape-pinning test would look like

Tape-pinning is a claim about **scheduled taker fills at deterministic
timestamps and prices**. To test it, the trigger must actually
encounter those fills:

1. **Schedule-coincidence test.** From `exploration3/osm_schedule.py`,
   take the 178 deterministic OSM ticks. At each, place a same-side
   order (match direction to the scheduled trade) at a price that
   would lift/hit the scheduled counterparty. Measure the markout
   over the next N ticks.
2. **Scheduled-ask specific test.** Track asks ≤ fv+2 at each tick; if
   the current ts is in OSM_SCHEDULE, lift. Compare markout to
   identical logic applied to non-scheduled ticks with asks at the
   same prices.

These would put the hypothesis directly on the hook. The density
trigger does not.

## Next research direction (honest assessment)

The remaining $1,400 gap to leaderboard top scores is not recoverable
via event-density triggers on OSM — not because of tape-pinning, but
because OSM's book structure denies the trigger usable liquidity
except ~1/day, and those fires don't convert to alpha.

Angles still open for the $1,400 gap:
- **Sizing**: tb1 uses `mi=15` inner size. Memory flags sustained
  dynamic_fv elevation/deflation as a candidate size-boost regime
  (iter26_c2_size_boost). Re-examine bench5.py output.
- **Composition**: tb1 inner + c1 outer + c3 middle simultaneously.
  Their per-candidate effects are recorded; stacking is not yet
  benched.
- **PEP edge**: 81% of round 1 PnL came from PEP drift. R2 PEP logic
  has regime-detector + defensive widening but no sizing regime.
- **Schedule-aware**: directly participate in the 178 deterministic
  OSM ticks via schedule-matched orders (not density-gated).
- **Position-exit discipline**: iter25 has no explicit unwind. Trade-
  level exit timing (e.g., forced unwind at mid-revert) may recover
  adverse-selection leaks.

Angles that should be considered closed:
- Event-density triggers in tight bands (structurally dead on OSM).
- Dynamic fv gates for take-loop (r2_osm_dynamic_gate falsified
  separately).
- L1-imbalance signals (r2_exploration3_null).
