# Round 2 Data Inventory

Snapshot: 2026-04-18. Purpose: record which Round 2 days are available for
out-of-sample replay, and flag the overfit risk the validator must cover.

## CSVs on disk

`data/round2/` contains three contiguous days:

| day | prices rows | trades rows | ticks | last timestamp |
|----:|------------:|------------:|------:|---------------:|
| -1  | 20,000 (10,000 ticks × 2 products) | 790  | 10,000 | 999,900 |
|  0  | 20,000                              | 803  | 10,000 | 999,900 |
|  1  | 20,000                              | 798  | 10,000 | 999,900 |

Products: `ASH_COATED_OSMIUM` (OSM), `INTARIAN_PEPPER_ROOT` (PEP). Tick cadence:
100. Price schema matches the standard Prosperity `prices_round_*.csv` format;
trades schema matches `trades_round_*.csv`. Position limit 80 per product
(`prosperity3bt.data.LIMITS`).

Confirmed via `prosperity3bt.data.has_day_data(FileSystemReader("data"), 2, d)`
for `d ∈ {-1, 0, 1}`; each day loads 10,000 timestamp rows per product.

Also present but out of scope for this validator: `data/round0/` (tutorial
round, EMERALDS/TOMATOES) and `data/round0_bt/` (Round-0 backtest outputs).

## Overfit risk the validator addresses

The Rust Monte Carlo simulator (`rust_simulator/`) calibrates its OSM/PEP
parameters from `data/round2/` via
`scripts/round2_calibration/calibrate_round2.py`, and the IMC server scores
submissions on ~1,000 ticks of day 0. The calibration uses all three days
(per-day means are averaged into the JSON constants in
`docs/round2_params.json`), but the dominant signal is day 0 because:

1. Per-day fair values for OSM differ by < 1.5 ticks, so OSM book statistics
   are effectively shared across days — no OOS lift possible.
2. PEP fair is a hard-coded linear drift anchored at the three known day
   starts (11,000 / 12,000 / 13,000). Any strategy that reads fair directly
   inherits this anchoring; any strategy that infers fair from the book is
   what we actually want to stress.
3. The server's 1,000-tick slice is drawn from day 0 (confirmed in the
   Round 1 write-ups and repeated in `docs/round2_model.md`), so a strategy
   tuned against day-0 book snapshots can look good in MC and on the
   server while leaking on days -1 or +1.

With three days available, the validator can replay strategies on days -1
and +1 as genuine out-of-sample checks, with day 0 as the in-sample
sanity baseline. If a strategy's per-tick PnL on day -1 or +1 differs
from day 0 by more than ~30%, that's the overfit signal the main agent
needs to see.

## Data used by MC calibration vs. available for OOS

| days                  | used by MC fit | available for validator |
|-----------------------|:--------------:|:-----------------------:|
| round 2 / day -1      | ✓ (mean only)  | ✓ — primary OOS target  |
| round 2 / day  0      | ✓ (mean only)  | ✓ — in-sample baseline  |
| round 2 / day  1      | ✓ (mean only)  | ✓ — primary OOS target  |

No additional Round 2 days exist. The validator does not fabricate data.
Out-of-sample coverage is the two days (-1 and +1) on which the MC
calibration uses only *aggregated* statistics and on which the server does
not score — a strategy can genuinely overfit day 0's exact book sequence
while still passing MC gates. Those two days plus the in-sample day 0
give the validator three points of day-to-day variation, which is
sufficient for the > 30% overfit flag.
