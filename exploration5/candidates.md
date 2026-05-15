# Candidate rules for exploration5

Baseline for comparison: **iter25_tb1** (already validated). Each
candidate modifies tb1, so Δ is measured vs tb1 baseline, not iter23.

## Candidate 1 — Dynamic outer edge (A)

**Rule**: Replace `bid_edge = fv - edge`, `ask_edge = fv + edge` with
`bid_edge = int(dynamic_fv) - edge` and `ask_edge = int(dynamic_fv) + edge`.

**Mechanism**: outer safety-net layer is currently static at fv±20 = 9981/10021.
When mid is far from fv, this layer is asymmetric (e.g., mid=10007, bid_edge=9981
is mid-26, ask_edge=10021 is mid+14). Moving with mid keeps the layer symmetric
around actual mid.

**Predicted capture**: small — outer layer rarely fills. Marginal improvement
in big-reversion events where price briefly reaches extreme.

**Orthogonality to tb1**: Composes cleanly. tb1 changes inner layer; this
changes outer layer.

**Orthogonality to Rule 2**: Does NOT touch take-gate. Static take-gate at
fv=10001 remains. Not a Rule 2 repeat.

## Candidate 2 — Size boost during sustained elevation (B)

**Rule**: Track consecutive ticks where `dynamic_fv >= 10005`. If count ≥ 5,
boost `mi` from 15 to 25. Mirror for sustained deflation (dynamic_fv ≤ 9997).
Reset counter when regime ends.

**Mechanism**: tb1 captures spread at mid±1 during elevation but caps size at
mi=15. Sustained elevation means many ticks of favorable fills; boosting size
captures more per tick.

**Risk**: larger inventory at extreme regimes. Covered by pos limit 80.

**Predicted capture**: incremental fills during elevated sub-windows where tb1
already has a presence. Estimated +$100-300/day.

**Orthogonality to tb1**: Composes. Uses tb1's bid_pj/ask_pj placement, just
more size at same price.

**Orthogonality to Rule 2**: No take-gate change.

## Candidate 3 — Middle layer at mid±3 (C)

**Rule**: Add a third quote layer at `bid_mid = int(dynamic_fv) - 3` and
`ask_mid = int(dynamic_fv) + 3` with size 8. Fills between inner (mid±1) and
outer (fv±20).

**Mechanism**: Orders traversing the book in 3-7 tick bands currently bypass
our book. A middle layer captures some of these.

**Risk**: adverse fills at mid±3 during sustained adverse flow.

**Predicted capture**: depends on how much trade flow happens in mid±3 band.
Estimated +$50-200/day.

**Orthogonality**: Composes with tb1 (separate layer).

## Candidate 4 — Conditional take-gate (E)

**Rule**: Relax take-gate ONLY when iter23 is currently short-positioned
(pos < -20) AND mid has elevated for 3+ consecutive ticks. In that case, allow
take-ask up to `ap < int(dynamic_fv)` instead of `ap < fv`. This covers short
inventory at favorable prices during elevated regimes.

**Mechanism**: iter23's static take-gate prevents buying asks ≥ 10001. When
short and mid=10007, asks at 10002-10006 are good fills (cover at below-mid).
Current logic skips these.

**Risk**: Rule 2 territory. Rule 2 removed mean-reversion enforcement by
taking above fv. This version is CONDITIONAL — only when we're already short
and need to cover. So we're trading inventory (not risking adverse selection
on top of no inventory).

**Predicted capture**: depends how often iter23 goes short AND mid elevated.
If rare, marginal. If common, +$200-500.

**Orthogonality to Rule 2**: Structurally different — conditional on position
AND regime. Not unconditional dynamic gate.

## Order of testing

1. **Candidate 1** (outer edge) — simplest, quickest to implement. Probably minor.
2. **Candidate 2** (size boost) — orthogonal and plausibly high-impact.
3. **Candidate 3** (middle layer) — new layer, risk of noise.
4. **Candidate 4** (conditional take-gate) — Rule 2 risk, test carefully.

Testing protocol per candidate:
- Clone iter25_tb1.py to iter26_<candidate>_trader.py
- Apply minimal change
- Run prosperity3bt 2--1, 2-0, 2-1 full-length
- Compare per-day OSM PnL vs tb1 baseline
- Gate: +$300 3-day total AND all 3 days positive
