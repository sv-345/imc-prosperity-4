# Analysis — submission 305289 (iter 12)

Official: **profit 9,606.50** on 1 day × 1,000 ticks (R2 format). Strategy: direct port of R1 v82_hardened.

Tool used: `ROUND_2/ob/analyzer.py` to step through all 124 trades (103 ours + 21 bot-bot).

## PnL decomposition

| source | cash | MTM | total |
|---|---:|---:|---:|
| cash flow from all our fills | −251,978 | — | — |
| OSM inventory at close (−76 @ mid 10,003) | — | −760,228 | — |
| PEP inventory at close (+78 @ mid 13,100) | — | +1,021,800 | — |
| **total MTM** | | | **+9,594** |
| reported profit | | | 9,606.5 (−12 rounding) |

Back-of-envelope decomposition:
- **PEP contribution ≈ +7.7 k** (unrealized 78 × (13,100 − 13,028 avg) = 5,616 + realized 51 × (13,069 − 13,028) ≈ 2,091)
- **OSM contribution ≈ +1.9 k**

## Market conditions (vs R1)

| product | R1 start → end | R2 (305289) start → end | R1 FV used | R2 true mean mid |
|---|---|---|---:|---:|
| OSM | 10,007 → 10,001 (−6) | 10,008 → 10,003 (−5) | 10,001 | **10,004.19** |
| PEP | 12,998 → 13,999 (+1,001) | 13,000 → 13,100 (+100) | dynamic (auto-intercept) | matches slope 0.1/tick ✓ |

**R2 OSM market mean is 10,004**, not 10,001. 77 % of R2 OSM ticks had mid > 10,001; 45 % had mid ≥ 10,005. The strategy's hardcoded `OSM_FV = 10,001` is stale for R2.

## Inventory trajectory

| product | min | max | final | reached limit at |
|---|---:|---:|---:|---|
| OSM | **−80** | **0** | −76 | trade #118 (ts 95,900) |
| PEP | 0 | 80 | +78 | trade #36 (ts 25,500, tick 255) |

**OSM never went long the entire session.** In R1, OSM oscillated between ±80. In R2 with the same strategy, OSM flow is entirely one-directional (net short).

## Root cause — the `OSM_FV = 10,001` gate

The strategy's OSM take logic uses TWO FV references:

```python
# in _trade_osmium:
fv = OSM_FV  # 10001 — hardcoded gate
dynamic_fv = self._inner_mid(d)  # observed

# Take-ask branch:
for ap in sorted(d.sell_orders):
    if ap >= fv: break   # ← gate fires at 10001
    ...

# Take-bid branch:
for bp in sorted(d.buy_orders, reverse=True):
    if bp <= fv: break   # ← gate fires at 10001
    ...
```

In R2 the mean mid is 10,004. Consequences:

1. **BUY side starved.** Asks at 10,002–10,004 get skipped by `ap >= fv` before we even check edge. We cannot buy OSM even at prices below the true fair value.
2. **SELL side over-fires.** Bids at 10,002+ pass the gate. The fallback `vol <= 9` branch fires aggressively on small bids above the stale fv, even when `real_edge` (vs dynamic_fv) is near zero or negative.

**Evidence from the ledger:**

| OSM side | n fills | avg price | price vs FV=10,001 |
|---|---:|---:|---|
| BUY | 25 | 9,996 | **100 %** fills strictly below FV |
| SELL | 46 | 10,008 | **100 %** fills strictly above FV |

Every single one of our OSM fills sits on the expected side of the stale 10,001 boundary. The gate, not the market, is driving our direction.

## Concrete examples (from stepping through)

### Trade #1 — ts=400, OSM SELL 8@10,010 (mid=10,014.5)
```
ASK 10019  vol 25
─ mid  10014.5
BID 10010  vol 8   ← trade
BID 10000  vol 12
BID  9998  vol 25
```
We sold 4.5 below mid. The bid at 10,010 > `fv=10,001` passes the gate. dynamic_fv = inner_bid (10,000) + 8 = 10,008, so `real_edge = 10,010 − 10,008 = 2` → take fires. Hindsight: mid was 10,014.5, we gave up the upside.

### Trade #40 — ts=32,800, OSM BUY 9@9,998 (mid=9,994)
```
ASK 10011  vol 24
ASK 10008  vol 12
ASK  9998  vol 9   ← trade
─ mid  9994
BID  9990  vol 24
```
We paid 4 above mid on this BUY. `ap=9,998 < fv=10,001`, `vol=9 ≤ 9` fires. Forward markout was positive (OSM mean-reverts after dips), so this worked out — but it's an example of the dynamic_fv being ignored in the gate decision.

### Worst PEP fill — ts=3,400, PEP BUY 12@13,010 (mid=13,003)
Paid 7 above mid. Fast-accumulate branch: `buy_limit = fv_int + 6`, we crossed up to that cap. Intended behavior; cost ≈ 84 but paid for by 100-point drift that followed.

## Side-channel observations

1. **Lambda logs empty.** `tick_logs` count is 0 — R2 server's sandboxLog/lambdaLog fields are empty strings. We cannot see what quotes we submitted each tick (unlike R1). Analyzer's "our orders this tick" view is blank for this submission. **Observation**: either the Logger was stripped (docstring confirms: "Logger ... stripped") or the R2 server doesn't surface print output. Tradable for post-mortem diagnostics.
2. **Bot-bot share much lower** than R1 (17 % vs 25 %). We're capturing a larger share of visible flow, likely because the R2 market is smaller (fewer participants in the simulated tape).
3. **PEP fast-ramp to +80** took 255 ticks (vs R1's 202). Strategy had the same fast-accumulate path, but R2 PEP book has smaller inside volumes at the start, so we saturate slower.

## Actionable findings, ranked by $ impact

### 1 (biggest): Make OSM_FV dynamic, or remove the hardcoded gate
- **Change**: replace `if ap >= fv: break` with `if ap >= dynamic_fv: break` (and mirror for bids). Or calibrate `OSM_FV` per-round from training data's mean mid.
- **$ impact (hindsight)**: if the gate had been at 10,005 instead of 10,001, we would have opened up ~40 additional buy opportunities at 10,002–10,004 and cut ~20 SELL mis-takes at 10,002–10,005. Rough estimate: **+2 – 4 k** on this day, closing ~50 % of the OSM PnL gap vs expected.
- **Risk**: different calibration per round is required — the `knowledge` folder likely has this per R2 training data.

### 2: Guard aggressive take with signed `real_edge`, not `vol ≤ 9` fallback
- **Change**: drop `vol <= 9 OR real_edge >= 2` to `real_edge >= 1` (remove the vol-only trigger). Prevents taking tiny bids above a stale fv where real_edge is 0 or negative.
- **$ impact**: ~15 of the 46 OSM SELLs had sub-zero real_edge computed from dynamic_fv. Skipping them saves on adverse-selection. **+500 – 1.5 k**.

### 3: Logging is broken on server — instrument via traderData instead
- Server shows empty lambdaLog. For future diagnostics, serialize our per-tick quotes into `traderData` (capped at ~3 kB) so the analyzer's "our orders this tick" lane works.
- $ impact: indirect. Makes future post-mortems possible.

## What 305289 did right

- PEP drift capture works as intended (≈ 7.7 k).
- OSM markouts are positive (+888 SELL, +827 BUY on 50-tick horizon) — the fills themselves are decent; only the direction gate is biased.
- Fast-accumulate got to +78 PEP with no manual override.

## Summary

The strategy is competent at PEP and market-structure reads, but **inherited an R1-specific OSM_FV constant that's 4 points too low for R2**, causing a one-sided OSM inventory buildup. Fix the gate to use observed mean mid or dynamic_fv and the OSM contribution plausibly doubles.
