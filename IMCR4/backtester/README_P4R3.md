# prosperity3bt — IMC Prosperity 4 Round 3 Fork

This fork of jmerle's [`prosperity3bt`](https://github.com/jmerle/imc-prosperity-3-backtester) is patched for IMC Prosperity 4 Round 3 (VELVETFRUIT_EXTRACT, HYDROGEL_PACK, VEV_4000..6500). It runs as a third independent reference for v83-class strategies, alongside GeyzsoN's `rust_backtester` (deterministic 10k-tick replay) and chrispyroberts' Rust simulator (Monte Carlo synthetic days).

Branch: `prosperity4-round3`.

## What's patched

1. `prosperity3bt/data.py:LIMITS` — replaced with the 12 P4R3 products and their position limits (HYDROGEL=200, VELVETFRUIT=200, all 10 vouchers=300). See `P4R3_SPEC.md` for sources.
2. `prosperity3bt/resources/round3/*.csv` — replaced with P4R3 historical data (10k ticks/day × 3 days), copied from `/Users/svelaga/Documents/IMCProsperityR3/ROUND_3/`.
3. `example/starter.py`, `example/oversized_trader.py` — minimal traders for smoke testing.

Engine internals are untouched. The match-orders semantics, position-limit enforcement, and TradingState construction all carry over from the upstream P3 backtester unchanged. CSV schema between P3 round 3 and P4R3 is byte-identical (only `currency` column value differs, and the engine doesn't read it).

See `NOTES_FORK.md` for the upstream-source audit and `P4R3_SPEC.md` for the locked spec.

## Setup

```sh
cd "/Users/svelaga/Documents/IMC Prosperity/prosperity3bt-fork"
uv venv
uv sync
```

Trader files at `/Users/svelaga/Documents/IMCProsperityR3/trader_r3_v*.py` use the bare `from datamodel import ...` style required by the IMC server. For the backtester to resolve that import, a copy of the engine's datamodel is placed at `/Users/svelaga/Documents/IMCProsperityR3/datamodel.py`. The backtester adds the trader's parent directory to `sys.path`, so the bare import resolves there.

## Usage

```sh
# Backtest v83 across all 3 R3 days (recommended)
uv run prosperity3bt /Users/svelaga/Documents/IMCProsperityR3/trader_r3_v83.py 3 --merge-pnl --no-out --no-progress

# Single day
uv run prosperity3bt <trader.py> 3-0   # day 0 only

# With trade-matching mode (default 'all' matches the upstream behavior;
# 'worse' matches GeyzsoN's rust_backtester exactly; 'none' disables step-in)
uv run prosperity3bt <trader.py> 3 --match-trades worse

# Open results in jmerle's visualizer
uv run prosperity3bt <trader.py> 3 --vis
```

## Fidelity validation (Phase 4 result)

v83 (`trader_r3_v83.py`) PnL across the three R3 days, per engine:

| Engine | Mode | Day 0 | Day 1 | Day 2 | Total |
|---|---|---:|---:|---:|---:|
| **prosperity3bt (this fork)** | `--match-trades all` (default) | 198,214 | 175,725 | 192,049 | 565,988 |
| **prosperity3bt (this fork)** | `--match-trades worse` | 198,319 | 175,596 | 191,492 | 565,407 |
| **prosperity3bt (this fork)** | `--match-trades none` | 195,692 | 172,891 | 190,316 | 558,899 |
| **GeyzsoN rust_backtester** | (deterministic, no flag) | 198,319 | 175,602 | 191,492 | 565,413 |
| **Server (1k tick test)** | n/a | n/a | n/a | n/a | 35,927 |

**Cross-engine agreement:**
- prosperity3bt `--match-trades worse` vs GeyzsoN: **byte-identical on day 0 (198,319) and day 2 (191,492); off by 6 on day 1 (175,596 vs 175,602, ~0.003%)**.
- prosperity3bt default `all` vs GeyzsoN: agreement within 0.3% per day, 0.1% on total.
- Both far inside the user's ±20% cross-check bar.

**Key inference:** GeyzsoN's rust_backtester implements "strict-better" (`worse`) step-in semantics — i.e., a market trade fills the trader's order only if the trader's price is strictly better than the trade price. This is consistent with the [Linear Utility P2 writeup](https://github.com/ericcccsliu/imc-prosperity-2). prosperity3bt's default `all` mode also fills at price equality, which is why it gives a slightly higher PnL.

**Server vs backtester:**
- Server (1k ticks): $35,927 (deterministic across submissions 380720, 381510, 381880).
- Backtester (10k ticks): ~$565k → ~$192k median per-day, ~$566k total.
- Ratio ~16x. This is structural to the session-length difference (1k vs 10k ticks) and v83's session-fraction-coupled close logic, **not** a backtester bug. Confirmed by the rust_backtester showing the same 5.3x median-per-day vs server ratio.
- The user's Phase 4 acceptance bar of ±30% vs server is **not directly applicable** because of the tick-count mismatch. The 3-engine cross-check at 10k ticks (the apples-to-apples comparison) passes overwhelmingly.

## Limitations

The engine does not model:

1. **Hidden FV liquidation at end of round.** The wiki states "any open positions are automatically liquidated against a hidden fair value at the end of the round," but the engine just marks open positions at the final tick's `mid_price`. v83 explicitly closes at tick 690/590 to capture this. Backtester results for traders that rely on the hidden-FV close mechanic may diverge if `final_tick_mid != hidden_FV`. Empirically (per `WIKI_NOTES.md` R4.1) they agree within ~$0.20 per voucher on probe data.
2. **Bot pricing model.** Counterparty quotes and trades come straight from the CSV; no synthetic counterparty behavior. Same as GeyzsoN. (Contrast: chrispyroberts' MC sim *does* model counterparties.)
3. **Queue penetration.** Orders match at full size up to available depth, irrespective of queue position. GeyzsoN's `--queue-penetration 1.0` default behaves identically; this is why both engines overshoot the 1k server PnL by ~5x.
4. **Conversions.** Not relevant for R3 (the manual Bio-Pods challenge isn't a runtime API).
5. **1k-tick test mode.** The server clips to 1k ticks during dev submissions; this fork always replays the full 10k-tick CSVs.

## When to trust this backtester

- ✅ Cross-validating that v83-class strategies have the correct *structure* (per-product PnL signs, voucher distribution, day-to-day stability). Two-engine agreement on these is a strong signal.
- ✅ Catastrophic-regression detection — if a code change tanks per-day PnL by 30k+, it's a real regression, both engines will see it.
- ❌ Predicting absolute server PnL from a single backtester run. The 1k-vs-10k ratio is not a stable multiplier.
- ❌ Tuning size / edge / close-tick parameters that depend on session length. v85_local_optimum.md already established that those are saturated on the 1k server format and the backtester is insensitive to them.

## Files

- `NOTES_FORK.md` — upstream-source audit, identifies what was patched and why.
- `P4R3_SPEC.md` — locked product spec with citations to Notion wiki.
- `scripts/smoke_test.sh` — runs noop + oversized + v83, asserts expected PnL signs.
- `example/starter.py` — minimal trader for sanity checks.
- `example/oversized_trader.py` — posts orders above position limits, verifies cancellation.
