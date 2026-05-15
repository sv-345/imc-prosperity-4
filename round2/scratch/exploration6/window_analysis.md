# Precise-window verification (server-scale ts 34.3K-48.1K, 76.1K-90.1K)

## Phase 3 volume concentration in windows

Runs iter25_tb1 × 3 R2 training days, tallies phase 3 fills in:
- server-scale windows (ts 34.3K-48.1K, 76.1K-90.1K — 2.78% of each day)
- day-scale windows (×10: 343K-481K, 761K-901K — 27.8% of each day)
- outside both

**Result: no concentration.**

| product | server_window share | concentration vs uniform |
|---|---|---|
| OSM | 2.65% of qty | **0.95×** |
| PEP | 2.92% of qty | 1.05× |
| OSM day_window | 27.32% | 0.98× |
| PEP day_window | 25.87% | 0.93× |

All ratios are ~1.0× (uniform). No volume concentration at either scale on training data. Phase 3 flow is distributed evenly across the training day.

## Directional bias in windows

| bucket | OSM buy/sell split |
|---|---|
| inside server_windows | 37% buy / 63% sell — **sell-biased by +13pp vs outside** |
| inside day_windows | 42% buy / 58% sell — sell-biased by +8pp |
| outside both | 50% buy / 50% sell |

Mild real asymmetry: phase 3 takers sell more often during these windows, hitting our bid more. Small sample (163 qty in server_windows) so noisy.

## Variant A (window-aware K) backtest

| variant | 3-day Δ vs tb1 |
|---|---|
| A: widen INSIDE windows (OSM_K_win=3, out=1) | **+$0 exactly** |
| A: widen INSIDE windows (OSM_K_win=5, out=1) | **+$0 exactly** |
| B: always-on (OSM_K=3) | +$17 |
| B: always-on (OSM_K=5) | −$104 |
| A inverse: widen OUTSIDE (OSM_K_out=3) | +$17 (= B) |
| A inverse: widen OUTSIDE (OSM_K_out=5) | −$104 (= B) |

**Result: Variant A adds nothing.** Widening inside the server-scale windows on training has exactly zero effect; all effect comes from outside-window ticks. Inside-window ticks on training don't contain the tight-book state where K-widening bites.

## Interpretation

The server step-up windows at ts 34.3K-48.1K and 76.1K-90.1K are likely:
1. A feature specific to the server book regime (not reproducible on training), OR
2. Driven by mid-path events (PEP drift, OSM regime transitions) that happen at those timestamps on the server but not consistently on training days.

Phase 3 tape concentration is NOT the mechanism. The previous `step_up_windows.md` analysis (exploration4) pointed at OSM regime transitions + PEP drift during those windows as the mid-level driver — not phase 3 concentration.

## Decision

Do not submit Variant A. Zero expected delta from backtest. Window-awareness is not the alpha angle.

The K=5 result on server ($9,788, 2nd-best session) was primarily about outside-window behavior. The +$341 vs tb1 mean is either real (from always-on widening capturing something on server books that training doesn't reveal) or single-session noise.

Recommend: one more K=5 server sample to pin down whether the +$341 is real before committing.
