# Round 2 — server log analysis

Automated parser + leak detector for Prosperity 4 server submission logs.
Every log in `/tmp/prosperity_logs/<submission_id>/<run_id>.log` is processed
by the same pipeline, so metrics are comparable across iterations and
regressions are caught without eyeballing.

## One-command workflow (after every submission)

```bash
scripts/log_analysis/analyze.sh <submission_id>
```

This:
1. Parses the log → `docs/round2_log_analysis/parsed/<sub>.json`
2. Detects leaks → `docs/round2_log_analysis/leaks/<sub>.md`
3. Refreshes the comparison table → `docs/round2_log_analysis/submissions_table.md`

Backfill everything (cheap; parser output is cached):

```bash
scripts/log_analysis/analyze.sh all
```

## What to read first after a submission

1. **`leaks/<sub>.md`** — top 3 leaks by estimated $ impact. This is the
   signal for what to change in the next iteration.
2. **`submissions_table.md`** — the `Δ$/tick` column vs previous row tells
   you whether the last change helped or regressed.
3. **`parsed/<sub>.json`** — raw metrics if the markdown hides detail.

## Scripts (see each file's docstring for args)

| Script | What it does |
| --- | --- |
| `parse_log.py` | Parse one log → JSON metrics. |
| `compare_submissions.py` | Merge many parsed logs into the comparison table. |
| `detect_leaks.py` | Flag inventory runaway / position limit / toxic fills / idle runs. |
| `analyze.sh` | Wrapper: parse + leak-detect + refresh table. |

## Log format

Detailed in [`log_format.md`](log_format.md). Summary: each `.log` is a
single-line JSON document with four top-level keys — `submissionId` (UUID,
not the server id), `activitiesLog` (semicolon-CSV of per-tick market state
with cumulative per-product PnL), `logs` (per-tick sandbox + trader
messages), `tradeHistory` (fills where `SUBMISSION` is buyer or seller).

## Metrics surfaced

Per submission:

- `total_pnl`, `per_tick_pnl`, `total_ticks`
- `fill_rate` = fills / ticks
- `any_errors` = unique sandbox errors (requestId stripped for dedup)

Per product:

- `pnl`, `per_tick_pnl`, `num_fills`, `avg_fill_size`
- `buy_qty`, `sell_qty`, `net_qty`, `num_buys`, `num_sells`
- `position_limit_hits` (sandbox breach message count)
- `largest_single_tick_loss` (most-negative PnL delta between consecutive ticks)
- `largest_adverse_move_after_fill` (mean mid-move N=5 ticks after each
  SUBMISSION fill; positive = toxic/adverse selection)

## Leak patterns detected

1. **`inventory_runaway`** — fills heavily one-sided, large |final net|, or
   running |position| touched the 80-unit limit. Estimated cost =
   `|net_qty| × (session mid range) / 2`.
2. **`position_limit_hits`** — sandbox rejected orders because position
   would exceed ±80. Cost = `hits × 0.1 × avg_$_per_fill` (10% of rejected
   ticks assumed to convert to fills if uncapped).
3. **`toxic_fills`** — mean adverse mid-move after fill exceeds threshold.
   Cost = `adverse_move × num_fills × avg_size`.
4. **`long_idle_run`** — ≥200-tick run with no SUBMISSION fill on this
   product. Cost = `gap_ticks × per_tick_pnl_of_product`.
5. **`runtime_errors`** — `[ERROR] …` lines in sandbox log. Cost
   proportional to missed ticks.

Thresholds are tuned at the top of `detect_leaks.py`. Leaks with estimated
impact below `MIN_IMPACT_TO_REPORT` ($50) are dropped to cut noise.

## Caveats

- **$ impact estimates are heuristics**, not P&L measurements. Use them to
  rank leaks, not to predict exact improvement.
- **Position limit is assumed to be 80** for both products (observed in
  sandbox `"limit of 80 set"` messages). If server configs change, update
  `DEFAULT_POSITION_LIMIT` in `detect_leaks.py`.
- **`largest_adverse_move_after_fill` uses N=5 tick lookahead**. Fills in
  the last N ticks of the session are skipped.
- **`day` field** in activitiesLog varies (observed 0 and 1). The parser
  doesn't distinguish; per-tick comparisons across days are still fair
  but absolute PnL isn't.
- **The `logs` array is empty for some submissions** (e.g., 294069).
  Position-limit-hit detection returns 0 in that case — not an absence of
  breaches, just an absence of logs. Cross-check with fill patterns.
- **Parser is tolerant**: missing fields are omitted rather than causing
  errors. If a parse fails entirely, the cached JSON will contain
  `{"any_errors": ["parse_failure: …"]}` and the comparator shows a
  `(no log)` row.

## Extending

- New metric: add extraction in `parse_log.py::_parse_one` and surface in
  `compare_submissions.py::render_table`.
- New leak pattern: add a block to `detect_leaks.py::detect_leaks` that
  returns a `Leak(...)`.
- New product: nothing to change; the parser discovers products from the
  activities-log header.
