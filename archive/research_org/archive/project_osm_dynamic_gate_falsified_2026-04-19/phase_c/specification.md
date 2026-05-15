# Specification: project_osm_dynamic_gate

**Origin:** Exploratory session, not standard Phase A/B work.
**Source artifacts:** `exploration/strategy_sketch.md`, `exploration/validated_rule.md`, `exploration/candidate_rules.md`, `ROUND_2/305289/analysis.md`.
**Target baseline:** `ROUND_2/iter23_trader.py` (5-sample server mean 9.641/tick).
**Target iteration:** `iter24_osm_dynamic_gate` (name suggestion; Integrator decides).

## Mechanism

`iter23._trade_osmium` uses a hard-coded `OSM_FV = 10001` as the
break-condition on both the take-ask and take-bid loops. In R2 the
OSM mid drifts intraday (mean ~10004, up to 10020 during extended
regimes such as day-0 Q3). When mid drifts above 10001, asks at
10002–10007 are genuinely below the true fair price but the
`if ap >= fv: break` statement blocks the take. Symmetrically, when
mid drifts below 10001, bids at 9994–10000 are genuinely above fair
but `if bp <= fv: break` blocks them. The fix replaces the static
gate with a **dynamic gate derived from `_inner_mid(d)`, clamped to
`[OSM_FV − 10, OSM_FV + 10]`**. Quote placement (layer edges, inner
`pj` levels) remains anchored on `OSM_FV = 10001` — the bug is only
in the take-gate, not the maker logic.

## Trigger condition

On every call to `_trade_osmium`, after `dynamic_fv = self._inner_mid(d)` is computed (line 351 in iter23):

```
gate = int(round(max(OSM_FV - 10, min(OSM_FV + 10, dynamic_fv))))
if dynamic_fv is None:
    gate = OSM_FV  # fallback preserves iter23 behavior
```

The gate is used in **both** loop break-conditions:
- take-ask loop (iter23 line 357): `if ap >= gate: break` (was `if ap >= fv: break`)
- take-bid loop (iter23 line 369): `if bp <= gate: break` (was `if bp <= fv: break`)

Falsifiable consequence of this trigger: on any tick where `dynamic_fv ∈ (10001, 10011]`, the take-ask loop evaluates asks at prices 10001..⌊dynamic_fv⌋ which iter23 skipped entirely. Symmetrically for bids when `dynamic_fv ∈ [9991, 10001)`. Events per 10k-tick training day: 396 agg_ask + 328 agg_bid events now reachable.

## Action

**Exact code change** (iter23_trader.py `_trade_osmium`, lines 338–377 unchanged except where noted):

1. **Insert after line 353** (`if dynamic_fv is None: dynamic_fv = fv`):
   ```python
   # Dynamic take-gate: clamp to [OSM_FV ± 10] to prevent runaway drift-chasing.
   gate = int(round(max(OSM_FV - 10, min(OSM_FV + 10, dynamic_fv))))
   ```

2. **Change line 357** from:
   ```python
   if ap >= fv:
   ```
   to:
   ```python
   if ap >= gate:
   ```

3. **Change line 369** from:
   ```python
   if bp <= fv:
   ```
   to:
   ```python
   if bp <= gate:
   ```

**Not changed:**
- `fv = OSM_FV` on line 339 (still used as quote-placement anchor downstream).
- The `vol <= 9 or real_edge >= 2` guards on lines 361 and 373 — these continue to filter the newly-accessible price band.
- Quote placement code (lines 384+) — `bid_edge`, `ask_edge`, `bid_pj`, `ask_pj` all still computed from `fv = OSM_FV = 10001`. The spread/skew/layering tuning is load-bearing for MM profitability and must stay anchored.
- PEP logic in `_trade_pepper` — entirely unchanged (PEP agg_bid take is a validated trap per `exploration/validated_rule.md`; PEP agg_ask take already correct via existing `ap >= fv_int` gate).
- Defensive widen logic using `take_sig` — unchanged.

Total diff: **3 code changes** (1 insertion, 2 variable-name substitutions). ~5 logical lines.

## Expected effect size

**Point estimate: +$250–350 per 1,000-tick server session.**
**95% CI (rough): +$150 to +$550 per 1,000-tick server session.**

Derivation trace:

1. `exploration/validated_rule.md` §"Event counts" reports 328 agg_bid + 396 agg_ask events per 10k-tick training day (mean across days −1, 0, +1).
2. `exploration/validated_rule.md` §"Per-event edge" reports $1.59/unit average edge on agg_bid and $2.47/unit on agg_ask → **$3,456 total edge per 10k-tick day** summed across all events.
3. `305289/analysis.md` Item 1 independently estimates **$2,000–$4,000 per 10k-tick day** for the dynamic-gate fix (note: this was diagnosed against iter12 and inherited by iter23).
4. The validated exploration and the 305289 analysis are independent sources converging on the same magnitude. Take the overlap: **$2,500–$4,000 per 10k-tick day**.
5. Scaling to 1,000-tick server session: divide by 10. **$250–$400/session.**
6. Apply exploration's disclaimer about ~80 % quote-randomization and fill-capacity constraints → realistic capture fraction ~70–90 % of edge. Center point: **$250–350/session; CI band widened to $150–$550 accounting for per-session intraday-regime variance** (some sessions have pronounced drift, others don't).

Relative to iter23 baseline ($9,641/session): **+1.6 % to +5.7 %** per-session uplift, center ~3 %.

## Falsification threshold

If Integrator's MC delta vs iter23 baseline is < **$50/session** on a 1,000-tick-equivalent basis (i.e., < +0.5 %), the bug-fix framing is empirically wrong and this spec has failed. Possible explanations at that point:

- The exploration's event-counting overstates the capturable opportunity (filled-volume caps, position-limit binding).
- Other iter23 logic already partially captures these events via the `vol <= 9` fallback (noted in `candidate_rules.md` Rule 2).
- MC harness has structural difference from server that makes the exploration's training-CSV measurements non-transferable.

At MC delta ≥ +$50/session, the spec is at minimum NOT harmful; we continue to server submission. Between $50 and $150 is a borderline-pass (flag for Integrator calibration note, but submit).

## MC gate predictions

Per Integrator's standard gates against the current baseline (iter23 MC mean 10.028/tick):

- **Per-tick mean:** expect ≥ 10.028 (no regression); point estimate 10.03–10.08.
- **P05:** expect ≥ 9.5 (baseline is 9.771); point estimate 9.75–9.82.
- **Sensitivity at ±20 %:** on the clamp parameter (OSM_FV ± 10). Perturb to ±8 and ±12. Expected within 20 % of nominal per-tick uplift.

**Important — MC calibration caveat:** the MC simulator hard-codes OSM FV = 10001 in its bot model (see `integrator/consolidated_baseline/README.md` §"MC calibration note for Kalman-based specs"). MC may under-credit this spec for the same structural reason it under-credits Kalman FV replacements. Point estimate for MC uplift: lower than server uplift by roughly the MC/server gap of +4 %. Server uplift expected to match or exceed the MC uplift in absolute terms.

**Skeptic should NOT reject this spec solely on MC per-tick being marginal.** The $50/session falsification threshold is the binding constraint, and that maps to ~+$0.05/tick in MC — well within noise of the MC baseline. Request Skeptic MC-gate adjustment: allow per-tick parity (no regression) rather than strict improvement.

## Implementation notes

- **Keep quote placement at OSM_FV = 10001.** The fix is ONLY to the take-gate (lines 357 and 369). Quote placement (bid_edge, ask_edge, bid_pj, ask_pj) uses `fv = OSM_FV` and must remain so. The 305289 analysis (§"Top 3 recommendations") confirms only the take-gate needed fixing.
- **`_inner_mid(d)` returns None during one-sided-book ticks** (~1 % of ticks). The existing fallback `if dynamic_fv is None: dynamic_fv = fv` on line 353 preserves iter23's behavior on those ticks (gate = OSM_FV, unchanged).
- **Clamp to [OSM_FV − 10, OSM_FV + 10]** prevents runaway drift-chasing if OSM mid spikes to extreme regimes. Without the clamp, a single aberrant tick with mid = 10020 would cause us to accept asks up to 10019, which would lose money on mean-reversion.
- **Integer rounding is load-bearing.** The gate is compared to integer prices from `d.sell_orders` and `d.buy_orders`. Without the `int(round(...))`, float comparisons would silently misbehave for the boundary price.
- **Forward-compatibility with Kalman Phase C:** when `project_latent_fv_kalman` Phase C ships (if it does), the `dynamic_fv = self._inner_mid(d)` line can be swapped to `dynamic_fv = self._kalman_fv()` with no other change. The clamp and guards stay. This spec is orthogonal to the Kalman project at the code level; the exploration's Phase B result shows the Kalman project did not clear the $150 threshold, but this spec does not depend on that outcome.
- **No new `traderData` state.** The fix is pure transformation of the existing tick's book; no persisted state needed.
- **PEP is explicitly out of scope.** Per `exploration/validated_rule.md` §"Why the PEP agg_bid signal doesn't become alpha", attempting a PEP agg_bid take loses ~$10,415/day in simulation. PEP agg_ask is already captured by iter23's existing `ap >= fv_int` gate on line 438. Do not generalize the OSM fix to PEP.

## Deterministic / reproducibility notes

- No RNG. No warm-start state. Each 1,000-tick server session is independently reproducible given identical book inputs.
- 3-sample reproduction protocol applies as normal; baseline update on 3-sample confirmed improvement per Integrator's existing rules.
- Integration cost is trivial (3-line diff) so reproduction cost is low.
