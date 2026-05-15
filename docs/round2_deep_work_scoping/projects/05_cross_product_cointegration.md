# Project 05 — Cross-product cointegration / stat-arb (OSM × PEP)

## Mechanism
If OSM and PEP mids co-move (shared factor / cointegrated), a
dislocation between them is a mean-reverting signal. Trade the pair:
long the cheap one, short the rich one, exit on reversion to the
cointegration line. On top of existing MM, this adds directional
alpha independent of either product's own edge.

## Required data
**AVAILABLE but CONCERNING.**
- R2 book snapshots: both products on the same timestamp grid (20,000 rows/day, 2 products interleaved).
- PEP drift is **deterministic** at +0.1/tick × 1,000 ticks → constant upward trend. OSM is (mostly) mean-reverting around ~10,004 per training data.
- A deterministic-trend × mean-reverting pair is NOT a cointegrated system in the classical sense — PEP carries no residual. Any "cointegration" result would be spurious regression.

Memory `round1_official_result.md` notes: "OSM/PEP correlation: OSM
mid std dev is ~5, PEP is monotone drift. No meaningful cross-asset
signal."

## Effort
If done anyway:
- **Phase A:** 6–8 h — build paired price series, compute spread, detrend PEP with its known slope.
- **Phase B:** 10–14 h — test if OSM residual (after removing its mean) and PEP residual (after removing its deterministic slope) co-move. Johansen, Engle-Granger, rolling-window OLS. Hold out day +1.
- **Phase C:** 4–6 h — convert to pair-trading triggers.
- **Total:** 20–28 h.

## Probability of producing ≥ $500/slice
**10 %.** Very unlikely given:
1. PEP drift is deterministic; its residual is tiny.
2. Both products share the same 80-unit position cap individually — pair trading competes with single-product MM inventory capacity.
3. R1 post-mortem already concluded no cross-asset signal.

The 10 % captures the remote case that R2 introduces NEW shared-factor coupling that R1 didn't have, detectable only with careful analysis.

## Expected alpha conditional on success
**$200–$800.** Small because pair trades compete with MM for the +80 cap; you would have to reduce MM aggressiveness to free inventory for the pair trade, partially offsetting gains.

## Why fast iteration didn't capture this
iter tuning operates per-product. Cross-product joint strategies are
architecturally distinct and require re-thinking inventory allocation
(pair trade vs single-product MM). That's a depth problem iter can't
crack by tweaking edges.

## Failure modes
1. No residual cointegration exists (most likely).
2. Cointegration exists but is too weak relative to transaction cost of crossing the book to enter/exit pair positions.
3. Capacity conflict: MM wants +80 PEP long; pair trade sometimes wants PEP short; cannot hold both.
4. Spurious statistical signal on 2 days (day -1, 0 used for fit) that fails on day +1 hold-out.
