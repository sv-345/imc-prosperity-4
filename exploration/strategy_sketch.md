# Strategy sketch — OSM dynamic-FV take-gate

## What iter23 does now (reference)

`ROUND_2/iter23_trader.py` lines 87, 338-377:

```python
OSM_FV = 10001  # module-level constant

def _trade_osmium(self, product, d, pos, take_sig=0):
    fv = OSM_FV                       # ← static
    dynamic_fv = self._inner_mid(d)   # ← already computed
    if dynamic_fv is None:
        dynamic_fv = fv

    for ap in sorted(d.sell_orders):
        if ap >= fv: break            # ← static gate misses ap at 10001-dynamic_fv
        vol = -d.sell_orders[ap]
        real_edge = dynamic_fv - ap
        if vol <= 9 or real_edge >= 2:
            ...take...

    for bp in sorted(d.buy_orders, reverse=True):
        if bp <= fv: break            # ← mirror
        vol = d.buy_orders[bp]
        real_edge = bp - dynamic_fv
        if vol <= 9 or real_edge >= 2:
            ...take...
```

The quote placement (lines 384-424) uses `fv ± edge=20` and `fv ± mi=15`
against the static `fv = OSM_FV`. This placement is NOT part of the fix.

## What the rule-aware version does differently

**Replace only the take-gate anchor**; leave quote placement at 10001.

```python
def _trade_osmium(self, product, d, pos, take_sig=0):
    static_fv = OSM_FV
    dynamic_fv = self._inner_mid(d)
    if dynamic_fv is None:
        dynamic_fv = static_fv

    # NEW: gate clamped to [static_fv - 10, static_fv + 10]
    gate = int(round(max(static_fv - 10, min(static_fv + 10, dynamic_fv))))

    # Take-ask: use dynamic gate instead of static
    for ap in sorted(d.sell_orders):
        if ap >= gate: break              # ← changed
        vol = -d.sell_orders[ap]
        real_edge = dynamic_fv - ap
        if vol <= 9 or real_edge >= 2:
            ...take...

    for bp in sorted(d.buy_orders, reverse=True):
        if bp <= gate: break              # ← changed
        vol = d.buy_orders[bp]
        real_edge = bp - dynamic_fv
        if vol <= 9 or real_edge >= 2:
            ...take...

    # Quote placement: UNCHANGED, still uses static_fv
    ...bid_edge = static_fv - edge
    ...ask_edge = static_fv + edge
    ...bid_pj = min(bb + 1, static_fv - 1)
    ...ask_pj = max(ba - 1, static_fv + 1)
    ...
```

### When this changes behavior

- **During intraday mid drift** (e.g., day 0 Q3 where mid = 10008-10020):
  - iter23: skips asks at 10001-10007 — misses them.
  - rule-aware: `gate ≈ 10008`, takes asks at 10001-10007 where
    `real_edge ≥ 2` — captures them.
- **During normal mid** (10000-10002): gate ≈ static_fv, identical to
  iter23. No behavior change.
- **Mid outside [9991, 10011]**: `gate` clamps to static_fv ± 10, preventing
  runaway drift-chasing.

### When it does NOT change behavior

- Quote placement (bid_pj, ask_pj, bid_edge, ask_edge) — all still
  anchored at 10001. Skew, layering, and edge sizing unchanged.
- PEP logic — unchanged. Agg_bid take on PEP is rejected (drift eats
  edge); agg_ask take is already correct.
- `vol <= 9 or real_edge >= 2` guard — kept. Still filters informed
  flow on the newly-accessible price band.
- Defensive widen on `take_sig` — unchanged.

## Expected PnL impact

From `ROUND_2/305289/analysis.md`:
- Item 1 (dynamic gate): **+$2-4k** on a 1-day server session.
- Item 2 (tighten `vol <= 9` fallback): +$0.5-1.5k. Complementary; can
  be layered on later.

Scaling caveats:
- Server session = 1 day × 1k ticks; 305289 measured in that scale.
- Training-CSV numbers in this exploration are per 10k-tick day.
- Final-round: 1M ticks → proportionally larger absolute PnL.

For the 20% community alpha claim against a $9,641 baseline:
`$9,641 × 0.20 = $1,928`. This fits squarely in the $2-4k/day
server-session range for the item-1 fix alone.

## Risks and mitigations

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| Adverse selection on newly-accessible ask band (10001-10007) | Medium | Keep `vol <= 9 or real_edge >= 2` guard. |
| `_inner_mid` returns None on sparse books | Low (~1% ticks) | Fallback to static_fv preserves iter23 behavior. |
| Dynamic gate chases mid into extreme regimes | Low | Clamp `gate ∈ [static_fv − 10, static_fv + 10]`. |
| 80% quote randomization changes which ticks have aggressive quotes | Medium | Effect is structural across 3 training days (328 agg_bid, 396 agg_ask events), not isolated to any one sample. Alpha should persist under resampling. |

## Measurement plan

1. Run `prosperity4mcbt` with both iter23 and the modified version
   on training data. Report mean/median/max OSM MTM_mid across N
   simulations.
2. Compare per-hour cumulative PnL curves; the alpha should concentrate
   in intraday drift regimes (Q3/Q4 of some days).
3. Sanity check: number of `_trade_osmium` take firings should
   increase by 100-300/day (328 + 396 = 724 new gates, ~30-50% hit
   rate accounting for volume caps).

## What this sketch explicitly does NOT do

- Does not modify iter23's PEP logic. PEP agg_bid take is a trap; PEP
  agg_ask take is already correct.
- Does not change MM quote placement. The 10001 anchor is load-bearing
  for iter23's spread/skew/layering tuning.
- Does not address R1/R2 strategy differences (separate concern).
- Does not define the Kalman filter. That's `project_latent_fv_kalman`'s
  scope. This rule-aware fix is a CHEAPER alternative that could land
  first and is robust to Kalman landing later — the gate computation
  is the swappable piece.

## Integration hook for Kalman-Phase-C

If/when the Kalman filter lands, swap the `gate` computation from
`_inner_mid(d)` to `kalman_posterior_mean`. The guard `vol <= 9 or
real_edge >= 2` and the clamp `[static_fv ± 10]` stay. This is a
one-line change in Phase C.
