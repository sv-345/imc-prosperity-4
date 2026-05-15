# Round 2 Simulation Model

Round 2 adds two products to the Monte Carlo backtester:

- **`ASH_COATED_OSMIUM`** (OSM) — stationary, constant fair value.
- **`INTARIAN_PEPPER_ROOT`** (PEP) — deterministic linear drift.

All parameters are derived from the CSVs in `data/round2/` by
`scripts/round2_calibration/calibrate_round2.py`, which writes
`docs/round2_params.json` and a human-readable
`docs/round2_calibration_summary.txt`. Re-running the script after any
data refresh regenerates both files; no parameters in the Rust or Python
code are magic — each literal has a comment pointing to the JSON key it
came from.

The methodology mirrors the Round 0 playbook: three pieces per product —
a fair-value process, an order-book placement model, and a taker-flow
model — each calibrated from the empirical CSVs.

## 1. Fair value

### OSM — constant

| quantity | value | source |
|---|---|---|
| Model | constant | `OSM.fv.model` |
| Fair value | **10001** | `OSM.fv.fair_value` (per-day means 10000.8 / 10001.6 / 10000.2) |
| Tick-to-tick mid-price σ | 3.69 | `OSM.fv.tick_diff_sigma` |
| Tick-diff ACF(1) | −0.50 | `OSM.fv.tick_diff_acf1` — strong mean reversion, which is the bid-ask-bounce signature, not true FV noise |

The 3.69 σ is mid-price volatility, dominated by bot-3 quotes flipping
the top-of-book tick. The latent FV noise is near zero — the simulator
uses `F_t = 10001` and lets the book-placement model inject the
observed oscillation.

### PEP — deterministic drift

| quantity | value | source |
|---|---|---|
| Model | linear drift | `PEP.fv.model` |
| Drift per tick | **+0.10000** | `PEP.fv.drift_per_tick` |
| Day-start fair | 11000 / 12000 / 13000 | `PEP.fv.per_day_start` (rounded from 10999.98 / 12000.01 / 12999.92) |
| Residual σ after detrending | 2.37 | same bid-ask-bounce artifact as OSM |

PEP is effectively deterministic: `F_t = day_start + 0.10·t`. The
simulator hard-codes the three day starts and extrapolates linearly for
synthetic day numbers outside {−1, 0, 1}.

## 2. Order-book placement bots

The book is generated per tick from three independent bot-like sources:

- **Wall**: outer-most level on each side, near-permanent during normal
  market conditions.
- **Inner**: one tick inside the wall, frequently present.
- **Bot-3**: a near-mid noise quote that appears on some ticks. It can
  be "passive" (on its own side of fair) or "aggressive" (crossing
  into the opposite side's territory).

### OSM

| slot | offset from floor(F) | volume range | presence rate (per side) |
|---|---:|---:|---:|
| bid wall | −10 | U(20, 30) | (always, subject to L3 truncation) |
| ask wall | +9 | U(20, 30) | (always) |
| bid inner | −8 | U(10, 15) | (always) |
| ask inner | +8 | U(10, 15) | (always) |
| bid bot-3 | passive at -{1,2,3,4}, aggressive at +{1,2,3,4} (mode at ±4) | U(2, 15) | 0.41 |
| ask bot-3 | passive at +{1,2,3,4}, aggressive at -{1,2,3,4} (mode at ±4) | U(2, 15) | 0.41 |
| passive fraction | 0.83 | | (`OSM.book.bot3_passive_frac`) |

Round-1 (same product) had walls at bid@−10 / ask@+11 (spread 21); R2
tightened the ask wall by 1 tick to +9 (spread 19). All other slots
match R1 within noise.

### PEP

| slot | offset from floor(F) | volume range | presence rate (per side) |
|---|---:|---:|---:|
| bid wall | −10 | U(15, 25) | (always) |
| ask wall | +10 | U(15, 25) | (always) |
| bid inner | −6 | U(8, 12) | (always) |
| ask inner | +7 | U(8, 12) | (always) |
| bid bot-3 | mode at +4 / −3 | U(3, 12) | 0.54 |
| ask bot-3 | mode at −4 / +3 | U(3, 12) | 0.075 |
| passive fraction | 0.31 (bot-3 is *predominantly aggressive*) | | |

R2 PEP is structurally symmetric at the wall (R1 had asymmetric −9/+10).
The asymmetry in bot-3 presence rates (bid 54% vs ask 7.5%) is a new R2
finding — presumably market-makers are systematically more willing to
lift PEP than to hit it, consistent with the upward drift pulling fair
through resting asks each tick. The simulator models this directly.

## 3. Taker flow

Takers are IID Bernoulli arrivals with 50/50 side mix and uniform
quantity within the product's support. No Hawkes clustering, no regime
switching — the Round-1 PHASE2 profile confirmed this for the same
products and R2 reproduces it.

| quantity | OSM | PEP | source |
|---|---:|---:|---|
| Rate per tick | 0.046 | 0.033 | `{OSM,PEP}.taker.taker_rate_per_tick` |
| Second-trade prob | 0.013 | 0.005 | `{OSM,PEP}.taker.multi_trade_tick_frac` |
| Buy-side fraction | 0.490 | 0.506 | `{OSM,PEP}.taker.side_buy_frac` |
| Qty support | [2, 10] | [3, 8] | `{OSM,PEP}.taker.qty_support` |
| Level split (inner / wall / bot-3) | 60 / 20 / 12 % | 29 / 1 / 48 % | `{OSM,PEP}.taker.level_split` |

The level-split figures are informational; the Rust sampler currently
fills against the visible book's best level(s) rather than explicitly
routing takers to a level band. A future refinement is to bias the
sampler toward the empirical split (matters most for PEP, where 48% of
takes land at near-mid bot-3 prices rather than the inner).

## 4. What's wired, what's not

**Wired (`cargo build && ./target/release/rust_simulator --round 2 …`)**:
- 3-day synthetic CSV generation (prices + trades) that reproduces the
  empirical OSM/PEP book and trade distributions.
- Deterministic PEP per-day starting fair and drift.
- Round-aware IO paths (`data/round2/`, `prices_round_2_day_*.csv`).
- `--round` CLI flag in `prosperity4mcbt` that short-circuits with a
  clear message directing the user to the raw Rust binary for data
  generation.

**Not yet wired** (explicit scope cut for this port):
- The Monte Carlo strategy runner (`run_backtests` in `rust_simulator/src/main.rs`).
  Its session accounting uses named fields (`emerald_pnl`, `tomato_pnl`)
  in the serialized CSV schema, which the Python dashboard builder
  consumes. Generalizing these to a per-product map is the next refactor
  before `prosperity4mcbt --round 2 <trader>.py` can run end-to-end.
- The visualizer's hard-coded product labels / color map
  (`visualizer/src/pages/montecarlo/MonteCarloPage.tsx`). Making the
  histogram series, band picker, and table headers data-driven is
  cosmetic once the dashboard bundle carries OSM/PEP stats.

The intermediate state is still useful: you can generate Round 2
synthetic CSVs, drop them into the Round-1-style MC toolchain in
`ROUND_1/mc/`, and iterate on strategies there.

## 5. Re-running the calibration

```bash
cd chrispyroberts-imc-prosperity-4
python3 scripts/round2_calibration/calibrate_round2.py
# writes docs/round2_params.json and docs/round2_calibration_summary.txt
```

If any parameter changes, update the matching constant in
`rust_simulator/src/main.rs` — every literal has a `docs/round2_params.json
-> ...` comment pointing to its JSON key. Then `cargo build --release`.
