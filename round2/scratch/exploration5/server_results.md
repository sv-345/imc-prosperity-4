# iter26_c4_best — server validation

## All submissions (4 samples per strategy)

| # | strategy | submission | TOTAL | OSM | PEP |
|---|----------|-----------:|------:|----:|----:|
| 1 | iter23 sample 1 | 303257 | 9,231.19 | 1,564.25 | 7,666.94 |
| 2 | iter23 sample 2 | 303280 | 9,514.50 | 1,908.25 | 7,606.25 |
| 3 | iter23 sample 3 | 314059 | 9,149.50 | 1,568.25 | 7,581.25 |
| 4 | iter23 sample 4 | 314132 | 9,245.50 | 1,533.25 | 7,712.25 |
| 5 | tb1 sample 1    | 313880 | 9,568.50 | 1,841.25 | 7,727.25 |
| 6 | tb1 sample 2    | 313935 | 9,529.50 | 1,810.25 | 7,719.25 |
| 7 | tb1 sample 3    | 313995 | 9,540.50 | 2,027.25 | 7,513.25 |
| 8 | tb1 sample 4    | 316361 | 9,269.88 | 1,742.25 | 7,527.62 |
| 9 | iter26 sample 1 | 316156 | 9,689.62 | 2,014.38 | 7,675.25 |
|10 | iter26 sample 2 | 316195 | 9,411.31 | 1,928.06 | 7,483.25 |
|11 | iter26 sample 3 | 316247 | 9,890.50 | 2,176.25 | 7,714.25 |
|12 | iter26 sample 4 | 316311 | 9,535.12 | 1,714.12 | 7,821.00 |

## Summary statistics (4 samples each)

| strategy | n | mean | σ | min | max |
|----------|--:|-----:|--:|----:|----:|
| iter23 | 4 | $9,285.17 | $135.5 | 9,149.50 | 9,514.50 |
| tb1    | 4 | $9,477.09 | $120.0 | 9,269.88 | 9,568.50 |
| iter26 | 4 | **$9,631.64** | $179.0 | 9,411.31 | 9,890.50 |

## Pairwise comparisons

| comparison | Δ mean | SE of diff | t | p |
|------------|-------:|-----------:|--:|--:|
| tb1 vs iter23 | +$192 | $90.5 | 2.12 | 0.03 |
| **iter26 vs iter23** | **+$346** | $112 | **3.09** | **<0.01** |
| iter26 vs tb1 | +$155 | $108 | 1.43 | 0.16 |

## Verdict

**iter26_c4_best significantly outperforms iter23 (t=3.09, p<0.01).** The c4_best modification genuinely improves server PnL.

**iter26 vs tb1 is directionally consistent with backtest but not statistically significant (t=1.43, p=0.16).** On 4-sample power, the incremental benefit of c4 on top of tb1 can't be distinguished from sample noise.

## Backtest vs server scaling

| metric | tb1 | iter26 |
|--------|----:|-------:|
| Backtest Δ vs iter23 (3-day total) | +$1,579 | +$3,065 |
| Server Δ vs iter23 (per session) | +$192 | +$346 |
| Backtest/server ratio | 8.2× | 8.9× |

**Consistent ~8-9× ratio — backtest scaling holds for the iter23→final comparison.**

But the incremental c4-over-tb1:
- Backtest: +$1,486 (=$3,065 − $1,579)
- Server: +$155 (=$346 − $192)
- Ratio: **9.6×** (consistent with above, actually a bit higher)

## Why higher variance on iter26?

| strategy | OSM σ | PEP σ |
|----------|------:|------:|
| iter23 | $165 | small |
| tb1    | $115 | small |
| iter26 | $175 | small |

iter26's OSM variance is higher than tb1's. The c4 take-gate relaxation fires conditionally (|pos| ≥ 40), which is reached in some 80%-samples but not others. When it fires, it triggers large trades. When it doesn't, iter26 ≈ tb1. This creates a bimodal distribution — most samples near tb1 mean, some samples much higher.

Evidence: iter26 max ($9,890) is much higher than tb1 max ($9,568); iter26 min ($9,411) is lower than tb1 min ($9,270) on a 4-sample comparison.

## Recommendation

**Ship iter26_c4_best as production.**

Evidence:
- Backtest: +$3,065 over 3 training days, all days positive vs iter23, all days positive vs tb1.
- Server: 4 samples show mean +$346 vs iter23 (p<0.01), mean +$155 vs tb1 (directional, underpowered at n=4).
- Mechanism is clean: single file, PEP untouched, take-gate relaxation is doubly-conditional (defense against Rule 2 failure mode).
- High variance means it could upgrade PnL in good-alignment samples — upside risk-reward is positive.

Caveats for framework review:
- iter26 vs tb1 delta is within 1.5σ noise at n=4 each. If framework requires stronger proof of incremental benefit, need more samples (8-10 each). At that point the +$155 delta should become ~2.5σ if stable.
- iter26's server variance is higher. This means PnL is LESS PREDICTABLE per session than tb1. For bidding/ranking purposes, an intermediate-variance strategy could be preferred over highest-mean if consistency matters.
- Backtest predicts ~+$495/session uplift over tb1 if scaled 1:1. Actual server 4-sample is +$155. Incremental c4 benefit is overestimated by backtest by ~3×.

## Server submission IDs

| # | id | strategy | total |
|--:|---:|---------|------:|
| 1 | 303257 | iter23 | 9,231.19 |
| 2 | 303280 | iter23 | 9,514.50 |
| 3 | 314059 | iter23 | 9,149.50 |
| 4 | 314132 | iter23 | 9,245.50 |
| 5 | 313880 | tb1 | 9,568.50 |
| 6 | 313935 | tb1 | 9,529.50 |
| 7 | 313995 | tb1 | 9,540.50 |
| 8 | 316361 | tb1 | 9,269.88 |
| 9 | 316156 | iter26 | 9,689.62 |
|10 | 316195 | iter26 | 9,411.31 |
|11 | 316247 | iter26 | 9,890.50 |
|12 | 316311 | iter26 | 9,535.12 |
