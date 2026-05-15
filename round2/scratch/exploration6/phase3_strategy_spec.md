# iter27_phase3 — candidate and result

## Spec

- Clone iter25_tb1.
- Parameterize quote placement: OSM bid_pj = `min(bb+1, dynamic_fv − OSM_PHASE3_K)`, ask_pj = `max(ba−1, dynamic_fv + OSM_PHASE3_K)`. PEP recycle bid_price = `min(bb+1, fv_int − PEP_PHASE3_K)`, ask_price = `max(ba−1, fv_int + PEP_PHASE3_K)`.
- Baseline equivalence: `OSM_K=1, PEP_K=1` reproduces iter25_tb1 exactly (sanity-checked: Δ=$0 on all 3 days).

## Predicted effect (from Step 2 back-of-envelope)

+$2k–$4k per day from widening OSM ask/bid from mid±1 toward mid±3..5 given the bimodal tape distribution (95% at mid±5+, 1.3% inside ±3).

## Observed effect on prosperity3bt, 3 R2 training days

| OSM_K | PEP_K | Δ 3-day total | per-day [d-1, d0, d1] |
|---|---|---|---|
| 1 | 1 | +0 | [0, 0, 0] |
| 2 | 1 | −1 | [−77, +54, +22] |
| **3** | **1** | **+17** | [−96, +38, +75] |
| 4 | 1 | −32 | [−125, −1, +94] |
| 5 | 1 | −104 | [−125, −1, +22] |
| 6 | 1 | −91 | [−120, +7, +22] |
| 3 | 2 | −10 | [−132, +47, +75] |
| 3 | 3 | +2 | [−132, +59, +75] |
| 5 | 3 | −119 | [−161, +20, +22] |

**Best: OSM_K=3, PEP_K=1 at +$17 / 3 days.** Day -1 regresses by $96. **Well below the +$200 tentative gate, let alone the +$500 validation gate.**

## Why the back-of-envelope was wrong

The theoretical analysis assumed our ask sits at fv+1 most of the time, so widening to fv+3 gains +2 edge per fill. In practice, the formula `ask_pj = max(ba−1, fv+K)` anchors to the book: when OSM inner-wall bots quote asks at fv+5..fv+10 (the dominant regime), ba−1 is already fv+4..fv+9, and `max(ba−1, fv+K)` = ba−1 regardless of K ≤ 4 or 5. iter25_tb1's placement already sits inside the wall, collecting the bimodal tape at near-maximum edge the book allows.

Widening with K only bites on the minority of ticks with ba ≤ fv+K+1 (tight book, typically when inner bots are absent or at tight levels). On those ticks, widening does exactly what the hypothesis predicted — misses the 1.3% inner-band tape, gains edge on the 47% wall-band tape. But the delta is small because:
1. Few ticks have tight enough book for widening to bite (visible in per-day deltas: day-1 regresses ~$100 from tight-book ticks that widening hurts).
2. On those tight-book ticks, adversarial conditions (why is the book tight?) tend to correlate with unfavorable phase-3 direction.

Net: mechanism real, exploit-angle null.

## Composition with tb1

Can't cleanly decompose because K=1 IS tb1. All gains attributable to widening K=1 → K>1 sit within [−$131, +$17] noise band. tb1's own server-validated +$261/session gain came from a different mechanism (swapping `fv → dynamic_fv` on bid_pj/ask_pj in the +1-edge regime), not from K-widening.
