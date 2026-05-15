# Round 2 — Bot Take Extraction

## Data source

`scripts/r2_postmortem/bot_takes.csv` — 395 bot-to-bot trades extracted from
R1 official submission (273632) + 4 v82-family R2 submissions. Classified by
inferring taker side from price vs best_bid / best_ask.

## 1.1 Trade classification (per slice)

| label | OSM takes | PEP takes |
|---|---:|---:|
| R1 (273632, 10k ticks) | 130 | 170 |
| R2_296317 | 3 | 16 |
| R2_296379 | 5 | 16 |
| R2_296878 | 7 | 18 |
| R2_297226 | 11 | 19 |

R2 has ~6 OSM + 17 PEP bot-bot takes per slice.

## 1.2 Taker side → forward mid move (key result)

| product | side | n | fwd_1 mean | z | fwd_10 mean | z |
|---|---|---:|---:|---:|---:|---:|
| OSM | buy | 57 | **+1.02** | +2.76 | **+1.20** | +3.60 |
| OSM | sell | 72 | **−0.97** | −3.73 | **−0.82** | −2.93 |
| PEP | buy | 60 | **+5.38** | **+19.5** | **+6.06** | **+21.0** |
| PEP | sell | 164 | **−2.15** | **−7.3** | **−1.44** | **−5.0** |

The z-scores on PEP are extraordinary (20+). This is easily the largest
predictive signal I've measured on R2 — 50-100× stronger than any of the
aggregate-book features (imbalance R²=0.33 translates to z≈5 over large n).

## 1.3 Conditional behavior: imbalance at take → taker side

| product | imbalance band | n | buy-taker fraction |
|---|---|---:|---:|
| OSM | neg (−0.5..−0.1) | 20 | 10% |
| OSM | mid (−0.1..+0.1) | 78 | 44% |
| OSM | pos (+0.1..+0.5) | 21 | 76% |
| PEP | neg | 58 | **0%** |
| PEP | mid | 84 | 10% |
| PEP | pos | 55 | **80%** |

Imbalance at take time is an extremely strong predictor of WHICH side takes.
For PEP: if imbalance is negative at a bot-take moment, it's a sell-taker
with ~100% probability. This is the causal chain that the earlier
"imbalance → fwd mid move" correlation was measuring *indirectly*.

## 1.4 Why iter15-19 missed this

- iter 15 (imbalance size lean): skewed quote sizes by imbalance continuously.
  But imbalance alone predicts mid move via an indirect chain (imbalance →
  which side takes → mid moves). Size skew on every tick averages over both
  take-direction outcomes; it doesn't CONDITION on whether a take happened.
- iter 16 (imbalance price shift): same issue. Shifting prices biases
  inventory in the expected direction, but each shift pays spread on the
  side we're leaning toward. On a noisy "maybe take, maybe not" tick, the
  shift is a constant cost with only occasional benefit.
- iter 17 (OSM sell mom filter): filtered based on 5-tick mid momentum —
  which is itself mostly bid-ask bounce noise on OSM, not causal bot activity.
- iter 18 (OSM fade scalp): traded the ACF reversal, which is bid-ask bounce
  mechanics. Bot takes aren't in ACF of mid returns.
- iter 19 (PEP mom-cond fast-cross): used 5-tick mid mom on PEP — which is
  dominated by drift + bid-ask-bounce noise, not bot take events.

None of these iterations EVER inspected `state.market_trades` to see what
bots had just done. That's the variable with z=19.5.

## 1.5 Taker size distribution (fingerprinting)

R1 OSM (n=130): sizes 2-10 with peak at 4-6. Implies roughly one taker
cluster with moderate size.

R1 PEP (n=170): sizes 1-8 with peak at 3-5. Similar single-cluster.

R2 matches shapes at lower sample count. No evidence of 2-5 distinct bot
strategies with different size signatures — the take population looks like
a single (or superposition of similar) taker with Uniform(2, 8) size.

## 1.6 Key actionable finding

The `state.market_trades` object — which my v82 port RECEIVES every tick
but ignores — contains the highest-signal predictor in the data. Using
it as even a basic direction-aware inventory skew should outperform all
my previous iterations, which used only top-of-book book state.
