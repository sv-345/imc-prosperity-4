# Round 1 — Trade Ledger

Official data: submission `273632` (id `ef8579f4-4f32-44bb-9169-c616a8e3c583`), strategy `v82_hardened`.

Session: 1 day × 10,000 ticks (server runs R1 as a single day on the final scoreboard).
Official profit: **101,199.69**.

Raw ledger: `scripts/postmortems/round1/artifacts/ledger.csv` (890 rows — one per fill).

## Columns

| column | meaning |
|---|---|
| timestamp | server ts, step=100 (tick = ts/100) |
| product | `ASH_COATED_OSMIUM` or `INTARIAN_PEPPER_ROOT` |
| side | BUY/SELL |
| size | qty (positive) |
| price | fill price |
| mid_at_fill | mid at same timestamp (nearest ≤ ts fallback) |
| edge_at_fill | mid − price (BUY) or price − mid (SELL); positive = good |
| mid_plus_10 | mid 10 ticks (1000 ts) forward |
| mid_plus_50 | mid 50 ticks forward |
| mid_plus_200 | mid 200 ticks forward |
| realized_pnl_fifo | PnL booked when this row closes an earlier lot (opening fills = 0) |
| adverse_N4_M20 | 1 iff price moved ≥4 against us within 20 ticks |
| adverse_N2_M10 | 1 iff price moved ≥2 against us within 10 ticks (stricter detector) |
| adverse_N6_M50 | 1 iff price moved ≥6 against us within 50 ticks (looser / longer) |
| inv_before / inv_after | per-product signed position around the fill |

## Summary

| metric | OSM | PEP | total |
|---|---:|---:|---:|
| fill count | 610 | 280 | 890 |
| BUY / SELL count | 317 / 293 | 158 / 122 | 475 / 415 |
| BUY / SELL qty | 1,570 / 1,490 | 689 / 611 | 2,259 / 2,101 |
| avg size | 5.0 | 4.6 | 4.9 |
| avg edge_at_fill | +3.69 | +3.64 | — |
| realized PnL (FIFO) | 18,316 | 76,356 | 94,672 |
| unrealized MTM end | +547 | +6,565 | +7,112 |
| MTM total | 18,863 | 82,921 | **101,784** |
| official profit | — | — | 101,200 |
| MTM vs official gap | — | — | +584 (0.6%; rounding / end-tick definition) |

## Adverse-selection flag counts

| configuration | fills flagged | % of 890 | Σ realized_pnl on flagged | Σ markout+50 on flagged |
|---|---:|---:|---:|---:|
| N=4, M=20 | 240 | 27.0% | 14,409 | 71,670 |
| N=2, M=10 (stricter) | 270 | 30.3% | 18,753 | 2,179 |
| N=6, M=50 (looser) | 284 | 31.9% | 22,382 | 161,512 |

**Note — adverse ≠ unprofitable here.** Most "adverse-flagged" fills are PEP SELLs: PEPPER drifts deterministically upward at +0.1/tick, so any SELL is guaranteed to be adverse-selected on any window, yet the overall strategy books positive PnL on them because the SELLs come after the accumulated long position has already captured the drift. The real decomposition is below.

## Edge-at-fill distribution (bimodal)

| bucket | count | % |
|---|---:|---:|
| edge ≥ +5  (deep-edge passive fills) | 531 | 59.7% |
| edge ∈ [+2,+5) | 22 | 2.5% |
| edge ∈ [0,+2) | 15 | 1.7% |
| edge ∈ [−2,0) | 71 | 8.0% |
| edge < −2    (aggressive takes, spread-crossing) | 251 | 28.2% |

Our strategy is **bimodal**: ~60 % of fills are deep passive ticks from the `fv±20` quoting, and ~28 % are crosses where we paid up for inventory. There is almost no "normal MM" fill activity in the [0, 5) edge band.

Σ (edge × size) on the 251 negative-edge fills: **−5,409** — this is the gross spread we paid for the aggressive takes. Their forward markouts on 50 ticks are still positive in aggregate, so crossing was net profitable — but the negative edge itself is a line item worth tracking.

## Inventory trajectory

Tick-fractions spent at each boundary:

| product | at +80 | at −80 | never went |
|---|---:|---:|---|
| OSM | 19.9 % | 7.5 % | — |
| PEP | **50.5 %** | 0.0 % | — |

**PEP sat at the +80 engine limit for half the session.** OSM oscillated between ±80 as the strategy intended.

## Drift capture

Path integral `∑ inv(t) × Δmid(t)` over the full session:

| product | drift capture | mid move | comment |
|---|---:|---:|---|
| OSM | +12,967 | −6 | Mostly MM wedges — mid barely moved; this tracks round-trip oscillation pnl. |
| PEP | **+76,560** | +1,001 | Bulk of total pnl comes from sitting long during the deterministic uptrend. |

**Ceiling given the +80 engine cap** (permanently +80 for the entire session):

| product | perfect-long PnL (drift only) | we captured | gap |
|---|---:|---:|---:|
| PEP | +80,080 | +76,560 | **−3,520** |

So within the engine's own constraints, PEP drift capture was 95.6 % of the hindsight ceiling.
