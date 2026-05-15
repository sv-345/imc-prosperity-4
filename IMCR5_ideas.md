# IMC Prosperity 4 — Round 5 ideas (archive)

Compiled 2026-05-15 from `IMCR5/` before the working tree was deleted.
Round 5 produced **no robust strategies**. Submission shipped (sub `570453`)
but the alpha cluster failed multiple-comparisons correction and the
deployed strategies relied on relative ranking + walk-forward sharpe rather
than statistical guarantees. This file preserves the ideas catalogue and
caveats for future rounds; the runnable code was discarded.

---

## 1. Round 5 dataset structure (what future-you needs to know)

- **3 days** (numbered 2, 3, 4) × **50 products in 10 themed families of 5**.
- Day-2 starts every product at mid = 10000. Day boundaries are real
  discontinuities — overnight gaps; never compute returns across them.
- **L3 depth is ~98.5% NaN** — exclude L3 from depth metrics.
- **Counterparty fields (`buyer`/`seller`) are 100% NULL** across all 35,385
  trades. Round 5 was expected to expose counterparty IDs; it did not. Any
  R5-style "per-counterparty profiling" plan must first verify the field is
  populated.
- **Position limit assumed ±10 per product** — not actually confirmed from a
  brief; backtest sweep over {25, 50} was identical because no strategy hit
  the cap.
- **Spreads 3–18 ticks per product** → round-trip aggressive cost = 2× spread
  per leg. This kills most microstructure signals before they trade.

Families observed (5 products each):
PEBBLES (XS/S/M/L/XL), SNACKPACK (5 flavours), UV_VISOR (5 colours),
PANEL (1X2/1X4/2X2/2X4/4X4), MICROCHIP, GALAXY_SOUNDS, TRANSLATOR,
ROBOT, OXYGEN_SHAKE, SLEEP_POD.

---

## 2. The alpha catalogue (10 candidates discovered, ranked by priority)

### A1 — PEBBLES constant-sum basket (HARD arbitrage, NOT TRADEABLE)
- Identity: `XS + S + M + L + XL = 50000 ± 3` across all 30k ticks
  (in-sample + OOS identical, ADF p < 1e-12, residual std 2.81, half-life
  < 1 tick).
- **Why it died:** 5-leg basket spread cost ≈ 30 ticks round-trip,
  exceeds any reachable mid-deviation (basket std = 2.81). Useful only as
  a risk-management filter ("if sum drifts, one leg is mispriced").

### A2–A4 — SNACKPACK pair MR (CHOC+VAN, RASP+STRAW, PIST+RASP)
- Daily-refit rolling z on `mid(L1) + mid(L2)`; entry |z|>2, exit z=0.
- Estimated 60 PnL/day per pair under aggressive fills.
- Reformulated for the final submission as **h=1 imbalance passive MR**
  (entry @ 0.65 / 0.35, exit band 0.05) — see §3.

### A5 — Cross-family coint: GALAXY_SOUNDS_DARK_MATTER × TRANSLATOR_SPACE_GRAY
- Spread = log(GSD) − α − β·log(TSG), β=−0.652, α=15.21 (day-2 OLS).
- Most durable cross-family signal: train Sh 3.87 / val 0.40 / test 1.02.
- β flipped sign on full-sample fit (−0.65 → +0.19) → regime-dependent.

### A6 — PEBBLES_XL × UV_VISOR_AMBER (DEPLOYED)
- β=−2.45, α=31.73; train 2.69 / val 1.70 / test 0.73 (only top-20 pair
  with positive val + test).
- Hedge-ratio fix needed at ±10 limit: scale = limit/|β| → PXL=4, UVA=10
  (not 10:10).

### A7 — MICROCHIP_OVAL leads CIRCLE by 50 ticks
- The ONLY genuine non-zero-lag pair in the universe.
- Lag −50 corr = 0.051, t = 8.9, R² = 5%.
- Strategy: OVAL move > 2σ → buy/sell CIRCLE same direction, exit after 50
  ticks. Small R² → small sizing (±2).

### A8 — MICROCHIP_SQUARE spread mean-reversion
- h=500 IC = −0.22, t = −7.20. **Spread IS the cost** → aggressive trade
  loses money. Would need a passive-fill MM module.

### A9 — PEBBLES h=500 directional momentum
- PEBBLES_M / BV_1000 / h=500: IC = +0.32, t = 2.72.
- PEBBLES_XL / RV_200 / h=500: IC = +0.27, t = 5.84.
- Looks like real persistence in basket-volatility regimes.

### A10 — PEBBLES_XS VPIN regime (anonymous flow)
- VPIN per trade, h=1000: IC = −0.21, t = −5.23. Lower priority; weak after
  red-team.

---

## 3. The submitted cluster (sub `570453`, v0.8 + hedge fix)

### Algo: 9 modules

**Cointegration pair MR (aggressive fills, 4 pairs)**

| Pair | β | α | sz1 | sz2 | entry / exit / stop |
|------|--:|--:|---:|---:|------:|
| PXL × UV_VISOR_AMBER | -2.4536 | 31.7318 | **4** | 10 | 2.0 / -1.5 / 4.0 |
| GSD × UV_VISOR_YELLOW | +0.3394 |  6.0703 | 10 | 3 | 2.0 / -1.5 / 4.0 |
| GSD × PEBBLES_XL | +0.1700 |  7.6322 | 10 | 2 | 2.0 / -1.2 / 4.0 |
| GSD × OXYGEN_SHAKE_EVENING_BREATH | -0.3476 | 12.3920 | 10 | 3 | 2.0 / -1.5 / 4.0 |

PXL_AMBER sz1=4 enforces the hedge ratio at the ±10 limit
(`scale = limit / max(1, |β|)`).

**SNACKPACK h=1 imbalance MR (passive fills, 5 modules)**

| Product | Feature | Entry-high | Entry-low | Exit band |
|---------|---------|----------:|---------:|---------:|
| SNACKPACK_PISTACHIO  | depth_imbalance | 0.65 | 0.35 | 0.05 |
| SNACKPACK_CHOCOLATE  | top_imbalance   | 0.65 | 0.35 | 0.05 |
| SNACKPACK_VANILLA    | depth_imbalance | 0.65 | 0.35 | 0.05 |
| SNACKPACK_RASPBERRY  | top_imbalance   | 0.65 | 0.35 | 0.05 |
| SNACKPACK_STRAWBERRY | depth_imbalance | 0.65 | 0.35 | 0.05 |

Microstructure signals at h=1 had sign-cons = 1.00, |IC| = 0.10–0.13,
t = 17–29. Aggressive-fill backtest lost money (spread > alpha); a
queue-aware passive-fill harness changed the verdict.

### Backtest PnL (local replay, 30k ticks)

| Component | 3-day total | Day 4 OOS |
|---|---:|---:|
| Pairs only (hedge-fixed) | +94,363 | +14,093 |
| SNACKPACK passive (PORT harness) | +123,708 | +42,660 |
| **Expected combined** | **~+218,000** | **~+56,750** |

Per-strategy:

| Strategy | 3-day | d4 OOS | Sharpe/tick |
|----------|-----:|------:|------:|
| coint_PXL_UVA_v3 (e=1.5, x=0.25) | +30,536 | +7,490 | +0.0095 |
| coint_GSD_UVY_v3 (e=2.0, x=0.5)  | +13,517 | +2,492 | +0.0064 |
| coint_GSD_PXL_v3 (e=1.5, x=0.25) | +29,001 | +6,111 | +0.0109 |
| coint_GSD_TSG_v3 (e=2.5, x=0.25) | +20,617 |   +340 | +0.0103 |

(Actual server result was not durable — Round 5 strategies did not perform
well in production, which is why this archive exists.)

### Manual puzzle (frozen, FYI)

9-product allocation, closed-form `x_i = clip(50 · r̂_i, ±100)`,
Σ|x| = 70.5 / 100 (under budget — extra 29.5 expires worthless).

| # | Product | Direction | x (%) | r̂ |
|---|---|---|--:|--:|
| 1 | Obsidian cutlery | SELL | 6.0 | -0.12 |
| 2 | Pyroflex cells | SELL | 12.5 | -0.25 |
| 3 | Thermalite core | BUY | 12.5 | +0.25 |
| 4 | Lava cake | SELL | 19.0 | -0.38 |
| 5 | Magma ink | BUY | 5.0 | +0.10 |
| 6 | Scoria paste | NONE | 0.0 | 0.00 |
| 7 | Ashes of the Phoenix | SELL | 4.0 | -0.08 |
| 8 | Volcanic incense | SELL | 2.5 | -0.05 |
| 9 | Sulfur reactor | BUY | 9.0 | +0.18 |

Mean E[PnL] across 9 worlds = **$128,243**; worst-world EV = **+$16,072**
(always positive). Selected from 24 candidate portfolios × 3,072 grid points
on composite score (0.6·mean + 0.4·worst).

---

## 4. What did NOT work (avoid in future rounds)

1. **PEBBLES sum=50000 basket arbitrage** — perfect identity, but 5-leg
   spread cost (~30) >> tradable deviation (max ~10).
2. **SNACKPACK h=1 imbalance under aggressive fills** — alpha real
   (sign-cons=1, t=17–29) but spread eats it. Needs queue-aware passive.
3. **MICROCHIP_SQUARE spread mean-reversion** — IC = −0.22 real, but the
   spread IS the cost.
4. **PANEL family area-arithmetic** ("1X2/1X4/2X2/2X4/4X4") — labels do
   NOT encode area ratios; all area-ratio cointegrations FAIL. Treat
   PANEL as 5 independent random walks.
5. **`micro_PEBBLES_XL_RV200`** — day-4 OOS = **−27,696**; max DD −45,071
   (4× total PnL); top-1% concentration 60%; 1-tick execution lag costs
   −62%. Looked great in-sample, dropped post-red-team.
6. **Per-counterparty profiling** — `buyer`/`seller` fields were all NULL
   despite the round preamble suggesting otherwise. Sub-Agent D had to
   reformulate to anonymous order-flow microstructure (weak signals).

---

## 5. Red-team caveats (apply to any future round)

1. **Multiple comparisons.** With a 1,225-pair search universe, Bonferroni
   threshold @ α=0.05 is p < 4.08e-05. Smallest pair p observed was
   0.00144 — fails strict correction. Deploys were ranked on relative
   walk-forward sharpe, not statistical proof.
2. **Strategy-level selection bias.** Testing 14 strategies → 6 positive
   PnL is binomial p=0.79 vs. a 50/50 null. The "menu" is itself a
   biased filter.
3. **β instability across days.** GSD/TSG: β flipped sign day-2 → full
   sample (−0.65 → +0.19). PXL/UVA: −2.45 → −0.89. Cointegration is
   regime-dependent — **refit β daily on prior day's data** if round
   runs > 3 days.
4. **Tick-cluster concentration.** All 4 surviving strategies had top-5%
   PnL share > 60%. A single bad cluster wipes a strategy → drawdown
   stops are essential.

Recommended drawdown stops (if anything resembling this cluster is ever
re-deployed):

| Strategy | Observed max DD | Hard stop |
|----------|----------------:|---------:|
| coint_PXL_UVA | -19,725 | -30,000 |
| coint_GSD_UVY | -6,501 | -15,000 |
| coint_GSD_PXL | -7,542 | -20,000 |
| coint_GSD_TSG | -12,154 | -25,000 |
| Aggregate | -45,922 | **-90,000** |

---

## 6. Lessons for future rounds

- **Backtester realism dominates alpha discovery.** The strongest
  microstructure signals (SNACKPACK imbalance, sign-cons=1.00) were
  un-deployable under aggressive-fill, deployable under queue-aware
  passive. Build the passive-fill harness FIRST in future rounds; many
  "killed" signals will come back to life.
- **Verify counterparty fields are populated before promising any
  per-counterparty alpha** — Round 5 promised them and delivered NULLs.
- **Hedge-ratio fix at position cap**: `scale = limit / max(1, |β|)`,
  applied so the larger leg saturates exactly. Don't naively clip both
  legs to ±limit — it breaks the hedge and adds unintended directional
  exposure.
- **`GALAXY_SOUNDS_DARK_MATTER` was a "factor hub"** — appeared in 3 of
  4 deployed pairs. Family-overload risk is real; cap GSD-paired
  strategies at 2 in any future cluster.
- **Run a final red-team pass before submit.** It dropped 1 strategy
  (`micro_PEBBLES_XL_RV200`) and reparam'd 2 others. The version that
  shipped was demonstrably better than the v1 pre-review version.

---

## 7. Sub-agent topology (for future end-to-end runs)

The R5 process used Claude Opus 4.7 with 7 sub-agents (A through G):

- **A**: Plotly+Dash interactive visualizer (Phase 1)
- **B**: Single-product microstructure sweep (4,745 cells, 603 real signals)
- **C**: Cross-product cointegration / baskets / factors (1,225 pairs)
- **D**: Anonymous order-flow microstructure (reformulated after NULL counterparties)
- **E**: Adversarial red team — verdicts per signal
- **F**: Queue-aware passive-fill harness (rescued SNACKPACK imbalance)
- **G**: Manual puzzle freeze + verification

Worth repeating in future rounds.
