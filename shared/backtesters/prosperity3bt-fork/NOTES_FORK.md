# prosperity3bt → P4R3 Fork Notes

Audit of the upstream `prosperity3bt` (jmerle) codebase before patching for IMC Prosperity 4 Round 3. Source commit: master @ clone time 2026-04-25, branch `prosperity4-round3`.

## TL;DR

The upstream engine is **product-agnostic**. The only product-specific surface is the `LIMITS` dict in `prosperity3bt/data.py`. Listings, order matching, position tracking, and CSV ingestion are all data-driven from whichever products appear in the prices CSV. Porting to P4R3 is therefore primarily:
1. Replace `LIMITS` with the P4R3 product list and limits.
2. Drop P4R3 CSVs into `resources/round3/` (or `--data /path/to/...`).
3. Optionally remove the dead MAGNIFICENT_MACARONS branch in `runner.py:61`.

The CSV schema for P3 round 3 is **byte-identical** to our local P4R3 data — same separator (`;`), same columns, same headers. **No conversion script is required.**

## File map

| File | Role | Patch needed? |
|---|---|---|
| `__main__.py` | Typer CLI entry; argument parsing, day discovery, run loop, output writing | No (engine-agnostic) |
| `runner.py` | Backtest loop, prepare_state, match_buy/sell_order, enforce_limits | Optional cleanup at line 61 (MACARONS observation key) |
| `data.py` | LIMITS dict, CSV parsing, BacktestData container | **Yes** — replace LIMITS |
| `models.py` | Result row types, TradeMatchingMode enum | No |
| `file_reader.py` | Abstract FileReader (package vs filesystem) | No |
| `datamodel.py` | Trader-facing types (Order, OrderDepth, TradingState, etc.) | No |
| `open.py`, `parse_submission_logs.py`, `__init__.py` | Utility | No |

## Hardcoded product references

Full grep for the P3-specific product names:

```
data.py:8     "RAINFOREST_RESIN": 50,
data.py:16    "VOLCANIC_ROCK": 400,
data.py:17–21 "VOLCANIC_ROCK_VOUCHER_{9500,9750,10000,10250,10500}": 200,
data.py:22    "MAGNIFICENT_MACARONS": 75,
runner.py:61  conversionObservations={"MAGNIFICENT_MACARONS": conversion_observation}
```

Other limits in `data.py`: KELP=50, SQUID_INK=50, CROISSANTS=250, JAMS=350, DJEMBES=60, PICNIC_BASKET1=60, PICNIC_BASKET2=100. These are P3 products that have no analogue in P4R3.

## CSV schema (verified identical to our P4R3 data)

**Prices**: `prices_round_<R>_day_<D>.csv`, separator `;`, header:
```
day;timestamp;product;bid_price_1;bid_volume_1;bid_price_2;bid_volume_2;bid_price_3;bid_volume_3;ask_price_1;ask_volume_1;ask_price_2;ask_volume_2;ask_price_3;ask_volume_3;mid_price;profit_and_loss
```

**Trades**: `trades_round_<R>_day_<D>.csv`, separator `;`, header:
```
timestamp;buyer;seller;symbol;currency;price;quantity
```

P3 uses `currency=SEASHELLS`; P4R3 uses `currency=XIRECS`. The engine never reads the currency column (verified in `data.py:131-146`) — it splits on `;` and indexes by position only. The currency string is opaque to the matcher; it just gets re-emitted in the output `Trade History` block.

**Observations** (optional): `observations_round_<R>_day_<D>.csv`, separator `,`, with macaron-specific columns. P4R3 has no observations; the file just won't exist, which `read_day_data` handles gracefully (line 149: `if file is not None`).

## Day discovery / CLI

`__main__.py:parse_days` iterates `range(-5, 100)` calling `has_day_data(file_reader, round_num, day_num)`, which checks for `prices_round_<R>_day_<D>.csv`. So:
- Filename format: `prices_round_3_day_0.csv`, `prices_round_3_day_1.csv`, `prices_round_3_day_2.csv` ✓ matches our P4R3 layout.
- Negative day numbers (`-2, -1, 0`) are supported but P4R3 only ships 0/1/2.
- CLI accepts `3` for "all days in round 3" or `3-0` / `3-1` / `3-2` for specific days.

## How `TradingState` is built (`runner.py:prepare_state`)

For each timestamp:
1. For each product in `data.products` (the set derived from prices CSV):
   - Build `OrderDepth` with `buy_orders[price]=volume` (positive) and `sell_orders[price]=-volume` (negative).
   - Add `Listing(product, product, 1)` — denomination=1 is hardcoded but unused by the engine.
2. Build `Observation` from `data.observations[timestamp]` if present, else empty `Observation({}, {})`.
3. Position is carried across timestamps via mutation of `state.position`.

Match priority (per `match_orders`):
1. Order depth first (sorted ascending for buys, descending for sells, prices ≤/≥ trader quote).
2. If quote not fully filled and `--match-trades != none`, match against market trades. Trade quantity is bookkeeping-tracked separately for buy/sell sides via `MarketTrade(buy_quantity, sell_quantity)` so the same market trade can be filled twice (once on each side).

## Limit enforcement (`runner.py:enforce_limits`)

Per-product check **before** order matching. If `position + total_long > LIMIT` OR `position - total_short < -LIMIT`, **all** orders for that product get cancelled (not just the over-limit ones) and a sandbox log line is emitted: `"Orders for product {product} exceeded limit of {LIMITS[product]} set"`.

This is the official-environment behavior and aligns with what GeyzsoN's rust_backtester does.

## What's NOT in the engine

- **No bot pricing model.** Market trades come straight from the CSV; the backtester does not simulate counterparty quoting.
- **No conversion mechanic** (relevant for P4R4 Macarons, not P4R3).
- **No hidden FV / end-of-round liquidation.** The activity log records `position * mid_price` at each tick as mark-to-market, but there's no sudden liquidation event at the final tick. **Trader code that relies on closing positions before tick N to capture hidden FV must do its own liquidation.**
- **No queue penetration / size penalty.** Orders match at full size up to available depth, regardless of where they sit in queue. (Contrast: GeyzsoN's rust_backtester defaults to `--queue-penetration 1.0` which gives ~5× upward PnL bias.)
- **No fees / slippage.** Matched at the better of the trader's quote and the resting price.

## Implication for v83 fidelity

v83's strategy assumes a hidden-FV close at tick 690/590. The upstream engine does NOT model this — at the last tick of each day, position simply gets marked at the final mid_price. **This means v83 may show a different PnL in `prosperity3bt` than on the server**, depending on whether v83 explicitly liquidates or relies on the implicit close mechanic. To investigate in Phase 4.

## Patch plan summary (Phase 3)

1. Edit `data.py:LIMITS` — remove all P3 products, add P4R3:
   - VELVETFRUIT_EXTRACT, HYDROGEL_PACK (limits TBD via Notion / wiki sweep — Phase 1)
   - VEV_4000, VEV_4500, VEV_5000, VEV_5100, VEV_5200, VEV_5300, VEV_5400, VEV_5500 (limit=80 per memory; verify)
   - VEV_6000, VEV_6500 (per wing-voucher memory, limit=300; verify)
2. Optional: remove `runner.py:61` observation key (cosmetic — code path is unreachable when no observations file).
3. Drop P4R3 CSVs into `prosperity3bt/resources/round3/` (overwrite existing P3 ones in the fork). Or pass `--data /path/to/IMCProsperityR3/ROUND_3/` if structure matches.

The data dir structure expected by `--data` is `<root>/round<N>/prices_round_<N>_day_<D>.csv`, so we can NOT point `--data` at `IMCProsperityR3/ROUND_3/` directly — there's no intermediate `round3/` subdir. Either move the files or create that subdir as a symlink.
