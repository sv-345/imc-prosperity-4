# Project 01 — L3 order book reconstruction with order ID tracking

## Mechanism
Reconstruct the sub-level-1 (L3) order book by linking each trade to
the specific resting order it filled, using order IDs. Once you have
the L3 book, you can model queue priority, cancellation behavior per
participant, and individual-order lifetime distributions — all of
which help you infer adverse selection at the order level and place
your own quotes more intelligently.

## Required data
**UNAVAILABLE.** Cross-reference `data_inventory.md`:

- Trade CSV columns: `timestamp; buyer; seller; symbol; currency; price; quantity` — **no order ID field**.
- Server submission log trades: same schema, no order IDs.
- Book snapshots are aggregated per price level (bid_volume_1/2/3), not per-order.

There is no mechanism in the exposed data to tie a trade to a specific resting order.

## Effort
N/A — project is infeasible.

## Probability of producing ≥ $500/slice
**0 %.** No order IDs exist; everything downstream fails.

## Expected alpha conditional on success
Hypothetical only: $1,500–$4,000 if order IDs existed and we could
model queue priority per bot. Comparable literature suggests L3
modeling adds 10–30 bp, but this is moot.

## Why fast iteration didn't capture this
Fast iteration skipped queue priority. If L3 data existed, queue-aware
quoting would likely require 40+ hours of ETL + modeling that the
fast-iter cycle cannot accommodate. But since the data doesn't exist,
the technique is impossible, not slow.

## Failure modes
The project fails at data ingestion, day zero.

## Recommendation
**KILL at scoping.** Archive this doc for reference. If IMC discloses
order IDs in a future round or data release, revive.
