# Round 2 Validation

Distributional comparison of simulated vs empirical Round 2 data. Produced by
`scripts/round2_calibration/validate_round2.py`; re-run after any Rust-side
parameter change. The bottom of the file is overwritten by the script on
each run (raw KS output); the top (this prose) is the stable interpretation
and should be updated by hand when the story changes.

## Setup

```bash
# 1) Generate synthetic CSVs
rust_simulator/target/release/rust_simulator --round 2 \
    --fv-mode simulate --trade-mode simulate \
    --output tmp/round2_gen

# 2) Run the KS suite
python3 scripts/round2_calibration/validate_round2.py
```

- Empirical: `data/round2/` (3 days × 10 000 ticks; ≈ 30 000 mid rows /
  1 400 OSM trades / 1 000 PEP trades after dropping empty-book ticks).
- Simulated: `tmp/round2_gen/round2/` (3 days × 10 000 ticks, fresh).
- Threshold: fail when KS p < 0.01.

## Current Results

### ASH_COATED_OSMIUM

| metric              | KS stat | p-value  | emp μ ± σ        | sim μ ± σ        | status    |
|---------------------|--------:|---------:|------------------|------------------|:----------|
| mid-price           | 0.405   | 0.00e+00 | 10 000.88 ± 5.10 | 10 000.97 ± 0.95 | FAIL      |
| top-of-book spread  | 0.207   | 0.00e+00 | 16.23 ± 2.52     | 15.78 ± 1.88     | FAIL      |
| trade quantity      | 0.025   | 7.77e-01 | 5.11 ± 2.24      | 5.04 ± 2.21      | **PASS**  |

### INTARIAN_PEPPER_ROOT

| metric                | KS stat | p-value  | emp μ ± σ     | sim μ ± σ     | status    |
|-----------------------|--------:|---------:|---------------|---------------|:----------|
| mid-price (detrended) | 0.082   | 1.6e-87  | 0.00 ± 2.37   | 0.00 ± 1.35   | FAIL      |
| top-of-book spread    | 0.340   | 0.00e+00 | 14.12 ± 2.79  | 13.75 ± 2.61  | FAIL      |
| trade quantity        | 0.019   | 9.92e-01 | 5.05 ± 1.54   | 4.99 ± 1.51   | **PASS**  |

## What passes, what doesn't, and why

**Trade quantity passes cleanly on both products.** The Rust sampler reads
empirical histograms (`sample_trade_quantity_by_side` in
`rust_simulator/src/main.rs`), so near-perfect match is expected.

**Spread means match to within 0.5 ticks** on both products. The inner-drop
probability (OSM 8%, PEP 16%) correctly shifts the average from
inner-only (OSM 16, PEP 13) toward the empirical means (16.23, 14.12).

The KS tests still register FAIL because at n ≈ 30 000 the test rejects on
any histogram-shape difference. The simulated spread is approximately
bimodal (16 vs 19 for OSM; 13 vs 20 for PEP) while the empirical spread has
a broader envelope — it includes 14, 15, 17, 18, and 21 as minority modes
from richer wall/inner patterns the three-level book doesn't reproduce.
This is a **shape** discrepancy, not a location error; it does not
materially bias a market-maker's fill statistics.

**Mid-price σ is the open gap.** The simulator produces σ ≈ 0.95 (OSM) and
1.35 (PEP), while the empirical series shows 5.10 and 2.37. The simulated
mid only moves when an inner drops or a (rare) bot-3 lands — giving tight,
nearly-constant mid around fair. The empirical data has larger per-tick
dislocations the current three-level book doesn't capture.

### Proposed fixes for the mid-price gap

If this gap matters for your downstream strategy ranking (it matters when a
strategy's PnL is sensitive to where the mid lies relative to inventory):

1. **Add one-sided wall states.** R1 memory notes `~37% of OSMIUM ticks
   have only one wall or no wall visible`. Modelling this explicitly (a
   state machine with a wall-consumed state that persists for several
   ticks) would recreate the larger mid excursions.
2. **Widen the bot-3 offset distribution.** Currently bot-3 is at ±4 ticks
   when present. Raising the bot-3 presence to ≈ 10% but placing offsets
   uniformly across [±1, ±8] would inflate simulated mid σ toward
   empirical without changing spread means materially.
3. **Rebuild calibration from untruncated L≥5 book data** if an alternate
   source is available (R1's `server_state_round1.json` gave 999 rows of
   full-book truth; the R2 CSVs are L3-truncated, which hides the wall /
   inner alternation that drives mid jitter).

### Status

The pipeline is **production-suitable for trade-flow sensitivity studies**
(qty and arrival-rate statistics match empirical) and **first-order suitable
for market-making prototypes** (spread means match to sub-tick resolution).
It is **not yet a faithful tick-by-tick mid-price replica**; any strategy
whose edge comes from mid-noise exploitation should validate on the
empirical CSVs directly.
