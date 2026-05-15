# Round 2 Out-of-Sample Validator

Local replay harness that runs a trader against **all three Round 2 days of
historical CSVs** — not just day 0. Its purpose is to catch strategies that
look good in the Monte Carlo simulator (calibrated on day 0) and in the server
score (also day 0) but leak on days -1 or +1.

## One-command invocation

```bash
python3 scripts/validator/validate.py <trader>.py
```

Replays on days -1, 0, +1; writes per-day JSONs to `tmp/validator/` and a
markdown report to `docs/round2_validation/<trader_stem>.md`.

Example output:

```
$ python3 scripts/validator/validate.py iter6_trader.py
day=-1  ticks=10000  total=+24,379.50  (ASH_COATED_OSMIUM=+10,250, INTARIAN_PEPPER_ROOT=+14,130)
day= 0  ticks=10000  total=+15,756.00  (ASH_COATED_OSMIUM=+9,923,  INTARIAN_PEPPER_ROOT=+5,833)
day= 1  ticks=10000  total=+14,639.50  (ASH_COATED_OSMIUM=+9,410,  INTARIAN_PEPPER_ROOT=+5,230)

Report: docs/round2_validation/iter6_trader.md
```

Then open the report and read the verdict section. **PASS** = day-to-day
variation looks like noise. **FLAG** = at least one OOS day's per-tick PnL
rate differs from day 0 by more than 30% (tunable via
`--overfit-threshold`) or flips sign.

## What the validator is actually doing

1. Loads `data/round2/prices_round_2_day_*.csv` and
   `trades_round_2_day_*.csv` via the stock `prosperity3bt.file_reader`.
2. Calls `prosperity3bt.runner.run_backtest` with `TradeMatchingMode.all` —
   the same fill logic as `prosperity3bt <trader> 2-<day>`. Resting orders
   stay, your orders cross the visible book, and market trades from the
   CSV can match against quotes that were inside the print price. No
   synthetic bots; the "other side" is the real recorded market.
3. Reconstructs cash and position from `result.trades` and marks to
   market each tick with a forward-filled mid (some R2 ticks have
   `mid_price=0.0` in the CSV because the book was momentarily empty —
   we sanitize these rather than let them corrupt per-tick PnL stats).
4. Emits a per-tick PnL series per product into a JSON bundle.
5. `report.py` aggregates one or more bundles into a markdown report
   with per-day totals, per-product breakdowns, per-tick distributions
   (P05/P50/P95), the worst single-tick loss, and the overfit verdict.

## Files

| path | role |
|---|---|
| `scripts/validator/replay.py` | replays one trader on one day → JSON |
| `scripts/validator/report.py` | aggregates JSONs → markdown report |
| `scripts/validator/validate.py` | one-shot wrapper (all three days + report) |
| `docs/round2_validation/data_inventory.md` | what R2 data exists, and why OOS matters |
| `docs/round2_validation/<trader>.md` | per-trader report (generated) |
| `tmp/validator/<trader>_day<N>.json` | per-day replay bundles (generated) |

## Handling traders with either import style

IMC server submissions use `from datamodel import ...` because the sandbox
exposes `datamodel` at top-level. Local research files typically use
`from prosperity3bt.datamodel import ...`. `replay.py` aliases the former
to the latter before importing the trader, so both forms work untouched —
no need to rewrite the import before validating.

## Split commands (if the wrapper does not fit your workflow)

```bash
# Replay each day separately
python3 scripts/validator/replay.py iter6_trader.py -1
python3 scripts/validator/replay.py iter6_trader.py  0
python3 scripts/validator/replay.py iter6_trader.py  1

# Aggregate into a report
python3 scripts/validator/report.py \
    tmp/validator/iter6_trader_day-1.json \
    tmp/validator/iter6_trader_day0.json \
    tmp/validator/iter6_trader_day1.json
```

## Interpreting the verdict

The report flags on **per-tick rate**, not absolute totals — a strategy
that scores $30k/day (day 0) vs $45k/day (day -1) is flagged even though
both are positive, because a 50% shift in earn rate means day-dependent
behavior. Read the per-product breakdown: if **OSM** is flat across days
but **PEP** swings wildly, the day-dependence lives in the PEP side of
the strategy.

Known patterns surfaced so far:

- `example_trader_round2.py` — FLAGs both OOS days with sign flips
  because it hard-codes PEP fair to the day-0 start (12,000), so on day
  -1 it systematically over-bids PEP and on day +1 it systematically
  over-asks. Classic MC/server overfit.
- `iter6_trader.py` — FLAGs day -1 at +55% (earns more OOS), passes day
  +1. The day -1 PEP rate is 2.4× the day 0 PEP rate, meaning iter6's
  inventory-skew stabiliser behaves differently depending on drift
  direction/starting fair. Not broken, but not stationary either — worth
  a follow-up if the main agent wants genuine day-agnostic behavior.
- `iter7_trader.py` — PASS. All three days within 5% of each other at
  $7.0/tick, reflecting that the PEP drift-capture mechanism works
  uniformly regardless of which day 0 slice the server happens to score.

## Data coverage

Only three Round 2 days exist (`-1`, `0`, `1`), with 10,000 ticks each.
The MC calibration uses aggregate statistics from all three so day 0 is
not uniquely "in-sample" in a bookkeeping sense — but the server scores
on day 0 only, so day 0 is the de-facto in-sample baseline for ranking
purposes. Days -1 and +1 are the real OOS coverage this validator
provides. See `data_inventory.md` for details.
