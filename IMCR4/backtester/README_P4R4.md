# IMC Prosperity 4 Round 4 — Backtester

Fork of [`jmerle/imc-prosperity-3-backtester`](https://github.com/jmerle/imc-prosperity-3-backtester) ported for **Prosperity 4 Round 4** ("The More The Merrier"). Branched from the local P4R3 fork on 2026-04-26 — the engine itself is product-agnostic, so the only delta vs the R3 fork is the data drop in `prosperity3bt/resources/round4/`.

## What's in this fork (vs upstream P3)

| Layer | Change | Where |
|---|---|---|
| Position limits | Replaced P3 product list with the 12 P4R4 products (HYDROGEL_PACK, VELVETFRUIT_EXTRACT, 10 VEV vouchers, all unchanged from R3) | `prosperity3bt/data.py:7-20` |
| Data | R4 prices + trades CSVs for days 1, 2, 3 | `prosperity3bt/resources/round4/` |
| Observations | None (P4R4 has no Macarons-style feed; the runner's `MAGNIFICENT_MACARONS` branch at `runner.py:60-62` is unreachable) | — |
| Counterparty names | **Already supported** by the engine — `data.py:139-140` reads buyer/seller from CSV columns 1,2; `runner.py:241,306` propagates them to `state.market_trades`. This is the new R4 mechanic. | — |

## Install

```bash
cd /Users/svelaga/Documents/IMCR4/backtester
uv pip install -e .
```

## Run

```bash
# All R4 days
uv run prosperity3bt path/to/trader.py 4

# Specific day (1, 2, or 3)
uv run prosperity3bt path/to/trader.py 4-1
```

Useful flags (verbatim from upstream):
- `--print` — stream Trader stdout
- `--no-out` — skip writing the visualizer log
- `--no-progress` — no tqdm bar
- `--match-trades {all,worse,none}` — control whether your orders get filled against historical market trades (default `all`)
- `--no-names` — anonymize buyer/seller (use to validate strategies that should NOT depend on counterparty info)

## Smoke test

`example/r4_counterparty_scan.py` is a no-op trader that aggregates counterparty flow per product and dumps a summary on the final tick. Use it to verify the data pipe and to spot informed-bot patterns.

```bash
uv run prosperity3bt example/r4_counterparty_scan.py 4-1 --print --no-out --no-progress
```

## R4 Day 1 — what the smoke test surfaces

Counterparty flow on day 1 (filtered to nonzero rows):

```
HYDROGEL_PACK            Mark 38, Mark 14 swap inventory; Mark 22 small
VELVETFRUIT_EXTRACT      Mark 55 net seller (-5347); Mark 14, Mark 67 net buyers; Mark 01/22/49 net sellers
VEV_4000                 Mark 38 ↔ Mark 14 swap; Mark 22 trivial
VEV_4500-5100            ALL flow: Mark 38 buys, Mark 22 sells (one-sided)
VEV_5200-5500            Mark 22 sells everything; Mark 14 + Mark 01 absorb
VEV_6000, VEV_6500       Mark 01 buys 34172, Mark 22 sells 34172 — perfectly matched 1:1
```

Highly suggestive observations to investigate:
- **Mark 22** is the universal voucher seller and never builds a long. Looks like a designated MM / inventory provider.
- **Mark 01** is the dominant buyer of OTM/deep-OTM vouchers (5300+, 6000, 6500). On the deepest strikes the entire flow is Mark 01 ⟵ Mark 22. If Mark 01 has informed signal, this is the Olivia-equivalent for vouchers.
- **Mark 38 / Mark 14** swap intraday — possibly noise traders.
- **Mark 55 / Mark 67** appear only on the underlying VELVETFRUIT_EXTRACT.

Next step: per-counterparty fwd-return analysis (do Mark 01's voucher buys precede underlying ups? does Mark 22's selling cluster at peaks?). The framework is ready — write the scan, point it at days 1/2/3.

## Caveats inherited from upstream
1. No bot-quoting model — market trades are replayed verbatim.
2. No hidden-FV liquidation — last-tick mark is `position * mid_price` (close enough on R3 empirically).
3. No queue-penetration penalty — orders match in full up to depth (PnL bias vs server can be material on thin books).
4. No fees / slippage.

See `NOTES_FORK.md` for the full upstream-engine audit.
