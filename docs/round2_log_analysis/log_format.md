# IMC Prosperity 4 — server log format (Round 2)

Each submission in `/tmp/prosperity_logs/<submission_id>/<run_id>.log` is a
**single-line JSON document** (`wc -l` returns 0 — there are no newlines at
the top level, but embedded strings contain `\n`).

Inspected submissions (for reference): 108517 (oldest w/log), 113554 (position
limit spam), 161831 (runtime error), 236359, 241224, 241988, 294069 (newest,
day=1 instead of day=0).

## Top-level JSON schema

```json
{
  "submissionId": "<uuid>",          // UUID, NOT the server submission_id
  "activitiesLog": "<semicolon-csv string with \\n separators>",
  "logs":         [ { "sandboxLog": "...", "lambdaLog": "...", "timestamp": N }, ... ],
  "tradeHistory": [ { "timestamp": N, "buyer": "...", "seller": "...",
                      "symbol": "...", "currency": "XIRECS",
                      "price": F, "quantity": N }, ... ]
}
```

- `submissionId` in the JSON is a UUID and is **not** the server submission_id.
  The server submission_id is the directory name (`294069`). The `run_id` is
  the log filename stem (`302973`).
- `logs` array has exactly 1000 entries (one per tick). Timestamps run 0 →
  99900 step 100.

## `activitiesLog` — per-tick market snapshot CSV

Semicolon-separated. Header:

```
day;timestamp;product;bid_price_1;bid_volume_1;bid_price_2;bid_volume_2;bid_price_3;bid_volume_3;ask_price_1;ask_volume_1;ask_price_2;ask_volume_2;ask_price_3;ask_volume_3;mid_price;profit_and_loss
```

- One row per product per tick → 2000 data rows (1000 ticks × 2 products:
  `ASH_COATED_OSMIUM`, `INTARIAN_PEPPER_ROOT`).
- `day` varies per submission: observed values `0` and `1`.
- `timestamp` is integer 0 … 99900 step 100 (1000 ticks).
- `profit_and_loss` is **cumulative PnL for that product up to that tick**.
  Total PnL = sum of last-tick PnL across products. Per-tick PnL delta per
  product = `pnl[t] − pnl[t−100]`.
- Bid/ask price-volume columns 2 and 3 are often empty (book has fewer levels).
  Columns 2/3 empty means `''` between semicolons, not a zero.

## `tradeHistory` — fills visible to us (ours + bot↔bot for our symbols)

```json
{ "timestamp": 3600, "buyer": "", "seller": "SUBMISSION",
  "symbol": "ASH_COATED_OSMIUM", "currency": "XIRECS",
  "price": 10008.0, "quantity": 3 }
```

- `buyer == "SUBMISSION"` → we bought (we're long by `quantity`).
- `seller == "SUBMISSION"` → we sold.
- Neither is SUBMISSION → bot↔bot trade visible because it's in a product we
  trade (useful for adverse-selection analysis, ignored for our fill stats).
- `currency` is always `XIRECS` in every log inspected.
- `quantity` is always positive; the side is encoded via buyer/seller.

## `logs` — per-tick trader & sandbox messages

Array of 1000 entries, one per tick:

```json
{ "sandboxLog": "...string...", "lambdaLog": "...string...", "timestamp": 0 }
```

### `sandboxLog` — platform messages (errors, limit breaches)

Two message types observed:

1. **Position limit breach** (appears as tick-level warning, order was rejected
   but strategy kept running):
   ```
   Orders for product INTARIAN_PEPPER_ROOT exceeded limit of 80 set
   Orders for product ASH_COATED_OSMIUM exceeded limit of 80 set
   ```
   Can contain either or both products per tick. Limit is 80 for both
   observed products.

2. **Runtime errors** (strategy still runs on subsequent ticks unless fatal):
   ```
   [ERROR] TypeError: unsupported operand type(s) for +: 'NoneType' and 'int'
   {"errorMessage": "...", "errorType": "...", "stackTrace": [...]}
   ```

Most submissions have empty `sandboxLog` for every tick. Count submissions
with any non-empty sandboxLog: 6 out of 270 (as of 2026-04-18).

### `lambdaLog` — the trader's own log output

Custom to the strategy. Observed formats:

- **jsonl/jsonifier-compressed** (108517): per-tick bracketed arrays holding
  trader state + orders, consumable by Prosperity visualizer.
- **empty** (294069): when the strategy chooses not to log.

Because content is strategy-dependent, the parser treats `lambdaLog` as
opaque text — it is not used for any metric, just surfaced if the user
wants to inspect.

## Derivable metrics

| Metric                         | Source                                            |
| ------------------------------ | ------------------------------------------------- |
| `total_ticks`                  | unique timestamps in activitiesLog (expect 1000)  |
| `per_product.pnl`              | last-row profit_and_loss per product              |
| `total_pnl`                    | sum of per-product pnl                            |
| `per_tick_pnl`                 | total_pnl / total_ticks                           |
| `per_product.num_fills`        | tradeHistory rows w/ SUBMISSION for symbol        |
| `per_product.avg_fill_size`    | mean quantity of those rows                       |
| `per_product.position_limit_hits` | sandboxLog substring counts per product        |
| `fill_rate`                    | total SUBMISSION fills / total_ticks              |
| `per_product.largest_single_tick_loss` | min(pnl[t]−pnl[t−100]) per product        |
| `per_product.largest_adverse_move_after_fill` | see below                          |
| `any_errors`                   | sandboxLog lines matching `[ERROR]` / `errorType` |

### Adverse-move-after-fill (toxic-fill proxy)

For each of our fills at price `p` and timestamp `t` on symbol `s`:
1. Look up mid price of `s` at `t + N*100` (N=5 ticks later by default).
2. If we bought: adverse move = `mid_future − p` (negative = price dropped
   after we bought = toxic). We invert so positive = adverse.
3. If we sold: adverse move = `p − mid_future`.

Report the mean across all fills for that product. Positive number =
on-average we got filled right before the price moved against us.

## Format drift handled by parser

- Truncated `activitiesLog` (incomplete session) → `total_ticks` reflects
  actual count; PnL still read from the last row seen.
- Missing keys (`tradeHistory`, `logs`) → treated as empty.
- Future product names → parser discovers products from the CSV, not
  hard-coded.
- Different `day` values → recorded but not used in metrics.
- Non-JSON or truncated JSON → parser returns `{"error": "..."}` and sets
  other fields to None. Comparator filters those out.
