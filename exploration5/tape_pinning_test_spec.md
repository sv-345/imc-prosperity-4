# Tape-pinning falsification test — spec

## Hypothesis under test

**Claim:** On OSM, ~50% of taker qty (up to 97% in the 0–50K window of
day 0) is fired by a deterministic schedule at fixed timestamps with
fixed prices. An event-density signal that triggers an aggressive take
in those windows will fail to capture alpha because the taker prices
are tape-pinned — i.e., the asks we are about to lift are scheduled
bot offers, not misprices.

**Consequence if true:** an event-density-conditioned cross-the-book
trigger should either regress vs iter25_tb1, or be flat, concentrating
its net fills in the high-scheduled-% windows (0–50K and 50–100K).

**Consequence if false:** the trigger nets meaningful positive PnL,
which would mean either (a) scheduled fills are profitable to lift
anyway, (b) event-density predicts continuation outside the scheduled
tape, or (c) the scheduled classification is less binding than my
bucketed stats suggested.

## Trigger specification

### Signal

Per-tick rolling window over the last `W = 5` OSM `OrderDepth`
observations. For each tick, set two flags:
- `agg_bid` = any bid price at levels 1..3 is ≥ `OSM_FV` (10001)
- `agg_ask` = any ask price at levels 1..3 is ≤ `OSM_FV`

Signal at tick *t*:
```
S_t = (# of agg_bid in window_t) - (# of agg_ask in window_t)
```

Fire conditions:
- `S_t ≥ DENSITY_THRESH`  → upside-density → take asks up to `OSM_FV + BAND`
- `S_t ≤ -DENSITY_THRESH` → downside-density → take bids down to `OSM_FV - BAND`

Parameters: `DENSITY_THRESH = 3`, `BAND = 2`.

(With `W=5`, `|S|≥3` means at least 3 of the last 5 ticks leaned one
way with no counter-ticks. Genuine cluster.)

### Action

Up-density fire (`S ≥ +3`):
1. Sort asks ascending. For each ask price `ap` with
   `OSM_FV < ap ≤ OSM_FV + BAND`, lift `min(ask_vol, 10, remaining_buy_room)`.
2. Stops at position limit 80 or after `BAND` ticks of asks consumed.
3. Does not alter the normal fv-gated take-ask loop (which runs first
   for asks strictly below fv) and does not alter the maker-side quote
   layer. Only inserts additional orders in the narrow `(fv, fv+BAND]`
   band that tb1 explicitly refuses to take.

Down-density fire (symmetric on bids in `[OSM_FV - BAND, OSM_FV)`).

No explicit exit — rely on tb1's normal maker quotes to recycle the
inventory.

### Why this trigger

- It is a **pure event-density take-side** addition — nothing else in
  tb1 is touched. That isolates the effect of density-triggered
  crossing, which is exactly the mechanism claimed to be tape-pinned.
- It operates in the `(fv, fv+BAND]` price band, which is precisely the
  band where scheduled OSM asks cluster (OSM schedule has 178 ticks,
  mostly SELL, at prices slightly above fv — that is where bucket
  0–50K gets 97% of its qty from scheduled ts).
- It fires in the bucketed "cluster" regions by construction: those
  are where agg_bid / agg_ask events concentrate.

### Where it fires (predicted by the viz data)

Per `exploration/cluster_vs_schedule.py` day-0 buckets:

| window   | agg_bid evts | agg_ask evts | sched qty % |
|----------|-------------:|-------------:|------------:|
| 0–50K    | 6            | 10           | 97%         |
| 50–100K  | 3            | 16           | 79%         |
| 100–150K | 4            | 7            | 26%         |
| 150–200K | 18           | 0            | 58%         |

The trigger fires on **runs** of these events. Concretely the fire
rate should be highest in 50–100K (density on the ask side → take
downside) and 150–200K (density on the bid side → take upside).

## Predictions

**Primary prediction (tape-pinning real):**
- 3-day sum Δ vs tb1 ≤ 0 on prosperity3bt.
- At least two of three days show Δ ≤ 0.
- Bucketed PnL delta is most negative in the high-scheduled windows
  (0–50K, 50–100K).
- Trigger fires ≥ 20 times per day but nets ≤ $50/day per day.

**Secondary prediction (refinement):** if day-level regression is
small (|Δ| < $200), but fire count is high, that also confirms
tape-pinning — lots of fires, no alpha.

## Falsification criteria

The tape-pinned hypothesis is **falsified** if any of:
- 3-day sum Δ ≥ +$300 vs tb1, with ≥ 2 of 3 days positive.
- 3-day sum Δ ≥ +$500 vs tb1 even on just one day, provided the other
  days are not more than −$100.
- Positive per-bucket PnL in the 0–50K or 50–100K windows with fire
  count ≥ 5, which would mean lifting scheduled asks actually made
  money.

**Confirmed** if trigger fires frequently (≥ 20 fires per day) and
3-day Δ ≤ $0.

**Partial** if day-to-day sign differs (one day strongly positive, one
strongly negative), pointing to an instability in the tape-pinning
mechanism rather than an absolute block.

## Backtest protocol

- Baseline: `exploration4/iter25_tb1.py` (unchanged).
- Variant: `exploration5/iter26_tape_test.py` (tb1 + density trigger on OSM only; PEP untouched).
- Engine: `prosperity3bt` (full 1M-ts days) on R2 training days `2--1`, `2-0`, `2-1`.
- The user asked for "100K-tick scale" — I interpret this as running
  the full day (standard prosperity3bt length) and additionally
  reporting per-bucket OSM PnL over the first 200K timestamps, which
  is where the cluster_vs_schedule analysis lives. Full-day totals
  give the honest overall verdict; bucketed deltas reveal whether
  fires in tape-pinned windows are the ones responsible.

## Stop rule

Run once. Report the result. Do not tune `DENSITY_THRESH`, `W`, or
`BAND` after seeing the result — that would be p-hacking the
falsifier.
