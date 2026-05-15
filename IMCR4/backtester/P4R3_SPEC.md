# IMC Prosperity 4 Round 3 — Product Spec

Locked spec for porting the prosperity3bt engine to P4R3. All values verified against authoritative sources.

## Sources

1. **IMC official wiki** — Notion page "Round 3 — Gloves Off" (id `d80b2b2a-5e49-821a-bef6-8160c1d8ae49`), fetched 2026-04-25 via Notion MCP. Direct quotes preserved below.
2. **`IMCProsperityR3/WIKI_NOTES.md`** — internal compilation of verbatim wiki + discord text, R2.2 / R3.1 / R6 sections.
3. **`prosperity_rust_backtester` patch** — GeyzsoN's R3 limits patch in `src/runner.rs::position_limit()` (recorded in memory `rust_backtester.md`) — independent confirmation.

The Notion wiki is authoritative; the other two corroborate.

## Products

Three "asset classes":

### Delta-1 underlyings

| Symbol | Description | Position limit |
|---|---|---:|
| `VELVETFRUIT_EXTRACT` | Underlying for the voucher options | **200** |
| `HYDROGEL_PACK` | Independent delta-1 product | **200** |

### Vouchers (call options on `VELVETFRUIT_EXTRACT`)

10 strikes, each with the same position limit. Verbatim from wiki:

> The vouchers are labeled `VEV_4000`, `VEV_4500`, `VEV_5000`, `VEV_5100`, `VEV_5200`, `VEV_5300`, `VEV_5400`, `VEV_5500`, `VEV_6000`, `VEV_6500`, where VEV stands for **V**elvetfruit **E**xtract **V**oucher, and the number represents the strike price.

| Symbol | Strike | Position limit |
|---|---:|---:|
| `VEV_4000` | 4000 | 300 |
| `VEV_4500` | 4500 | 300 |
| `VEV_5000` | 5000 | 300 |
| `VEV_5100` | 5100 | 300 |
| `VEV_5200` | 5200 | 300 |
| `VEV_5300` | 5300 | 300 |
| `VEV_5400` | 5400 | 300 |
| `VEV_5500` | 5500 | 300 |
| `VEV_6000` | 6000 | 300 |
| `VEV_6500` | 6500 | 300 |

Verbatim from wiki: "`VELVETFRUIT_EXTRACT_VOUCHER`: 300 for each of the 10 vouchers."

**Note:** the prompt's "voucher limit was found to be 80, not 20" was incorrect / stale. The wiki, internal `WIKI_NOTES.md` R2.2, and the GeyzsoN rust_backtester patch all agree on 300.

## Time-to-expiry (TTE)

Verbatim from wiki:

> They all have a 7-day expiration deadline starting from round 1, where each round represents 1 day. Thus, the 'time till expiry' (TTE) is 7 days at the start of round 1 (TTE=7d), 6 days at the start of round 2, 5 days at the start of round 3, and so on.

For **historical CSV data** in `ROUND_3/`:

> - TTE=8d at the start of historical day 0 (coinciding with the tutorial round)
> - TTE=7d at the start of historical day 1 (coinciding with Round 1)
> - TTE=6d at the start of historical day 2 (coinciding with Round 2)

For the **R3 server submission**: TTE = 5d at start of round.

The backtester engine itself does not need to know TTE — it just replays order books. TTE only matters to the trader (e.g., for Black-Scholes).

## Session length

Verbatim from `WIKI_NOTES.md` R3.1 (quoting the wiki via dam4709):

> The simulation consists of a large number of iterations (1_000 during testing when you develop your algorithm on historical data; 10_000 for the final simulation that determines your PnL for the round).

- **Historical CSV days** (in `ROUND_3/`): 10,000 ticks each, timestamps 0..999900 step 100.
- **Test submissions** (manual upload): 1,000 ticks (timestamps 0..99900 step 100). The server clips the run.
- **Final round eval**: 10,000 ticks.

This matters for fidelity comparison: v83's $35,927 server PnL was on a 1k test. Running v83 on a full 10k day in the local backtester is **not** an apples-to-apples comparison against $35,927.

## Tick mechanics

From `WIKI_NOTES.md` R6:

- Tick step: 100 timestamp units
- Currency: `XIRECs` (P3 used `SEASHELLS`; cosmetic only — the engine treats it as opaque)
- Trader timeout: 900ms per tick
- traderData budget: < 50,000 chars
- Allowed imports: `pandas`, `numpy`, `statistics`, `math`, `typing`, `jsonpickle`, plus stdlib

## Conversions

From `WIKI_NOTES.md` R6: **conversions not supported on any R3 product**. The wiki page does describe a manual challenge involving "Ornamental Bio-Pods" / Celestial Gardeners' Guild, but that is a one-time manual bid submission outside the algorithmic trading loop — **not** a runtime conversion API call. The `Trader.run` return triple's `conversions` value should always be 0 for R3.

## End-of-round liquidation (hidden FV)

Verbatim from wiki:

> Any open positions are automatically liquidated against a hidden fair value at the end of the round.

The exact FV formula is not stated in the wiki. From `WIKI_NOTES.md` R4.1, empirical evidence from prior probes suggests:
- Voucher hidden FV ≈ final-tick mid (within $0.20 on 4 active strikes — v41b probe).
- HYDROGEL/VELVET hidden FV ≈ final-tick mid (NOT a hardcoded anchor — v53 reconciliation).

The prosperity3bt engine does **not** model this. Its activity log records `position * mid_price` at each tick as a running mark-to-market, but there is no special liquidation event at the final tick. Trader code that wants to capture hidden-FV PnL must explicitly close positions before the last tick (which is what v83 does at tick 690/590).

This is a **fidelity gap** to track in Phase 4: if the server liquidates open inventory at hidden FV, but the local backtester just marks at last-tick mid, both should agree as long as final-tick mid ≈ hidden FV. Empirically this holds.

## Available historical data

`/Users/svelaga/Documents/IMCProsperityR3/ROUND_3/`:
- `prices_round_3_day_0.csv`, `trades_round_3_day_0.csv` (TTE=8d data)
- `prices_round_3_day_1.csv`, `trades_round_3_day_1.csv` (TTE=7d data)
- `prices_round_3_day_2.csv`, `trades_round_3_day_2.csv` (TTE=6d data)

CSV schema (verified): identical to upstream `prosperity3bt/resources/round3/`. Same columns, same `;` separator, same `prices_round_3_day_<N>.csv` / `trades_round_3_day_<N>.csv` naming. The only schema-level difference vs P3 is `currency=XIRECS` instead of `currency=SEASHELLS` in the trades file — engine doesn't read that column.

No observations file is provided for R3 (no Macarons-style external observation feed in this round).

## LIMITS dict (drop-in for `prosperity3bt/data.py`)

```python
LIMITS = {
    "VELVETFRUIT_EXTRACT": 200,
    "HYDROGEL_PACK": 200,
    "VEV_4000": 300,
    "VEV_4500": 300,
    "VEV_5000": 300,
    "VEV_5100": 300,
    "VEV_5200": 300,
    "VEV_5300": 300,
    "VEV_5400": 300,
    "VEV_5500": 300,
    "VEV_6000": 300,
    "VEV_6500": 300,
}
```

Total: 12 products. All P3 products (RESIN, KELP, SQUID_INK, CROISSANTS, JAMS, DJEMBES, basket1/2, VOLCANIC_ROCK, voucher 9500–10500, MACARONS) are removed.
