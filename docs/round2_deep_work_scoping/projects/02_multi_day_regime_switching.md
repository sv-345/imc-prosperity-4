# Project 02 — Multi-day regime-switching model

## Mechanism
Different training days may exhibit different market microstructures
(wall bot size distribution, taker aggression, inner spread width).
Fit a Markov-switching state-space model across days −1, 0, +1,
with latent regime `r(t) ∈ {1..K}` driving observed book/trade
statistics. Condition the trader's quote edge, take thresholds, and
recycle sizes on the current regime estimate. R2 trader blends params
per inferred regime at each server tick.

## Required data
**AVAILABLE.**
- R2 training books: `ROUND_2/prices_round_2_day_{-1,0,1}.csv` (3 × 10,000 ticks).
- R2 training trades: `ROUND_2/trades_round_2_day_{-1,0,1}.csv`.
- Cross-reference day-level MC per-tick from `r2_iter23q/session_summary.csv` already shows variability (-1 day mean differs from day 0 by ~0.5/tick in iter23).

## Effort
- **Phase A (infrastructure):** 8–12 h — build per-day feature extractor (mean spread, wall sizes, taker imbalance, tick volatility); build Markov-switching model fit harness (Baum-Welch or EM).
- **Phase B (analysis):** 10–15 h — fit K ∈ {2,3,4}; per-day held-out cross-validation; confidence intervals on regime parameters; show regime assignment stability.
- **Phase C (translation):** 4–6 h — online regime inference from first ~100 ticks of a server session; parameter blending code spec.
- **Total:** 22–33 h.

## Probability of producing ≥ $500/slice
**15 %.** Main risk: 3 days is a small N for regime-switching. Even if you find K=2 regimes fit well on 3 days, generalization to server day 4 is a coin flip. K=2 with 1,000 ticks of online warmup on the server is viable but noisy.

## Expected alpha conditional on success
**$400–$1,500** per server submission. Lower bound is "pick between two parameter sets based on first 100 ticks"; upper bound is "continuous blend with good online inference."

## Why fast iteration didn't capture this
Fast iteration tunes one global parameter set against 100 MC sessions,
which averages across day-level regime differences. iter10–26 params
are compromises. A regime model lets the server trader detect which
regime it's in and switch — impossible to do well without first
characterizing the regime structure, which requires sustained
analysis (Phase A/B depth).

## Failure modes
1. K=2 regimes correspond 1:1 to "day" rather than truly switching within a day — then regime inference during the 1,000-tick server run is pointless (the server is one continuous day).
2. Regime differences exist but don't map to actionable parameter deltas (i.e., optimal edge=12 vs 13 doesn't move PnL much across regimes).
3. 100-tick online warmup is too short to infer regime; strategy defaults to prior-mean and captures no alpha.
4. Overfitting on 3 days — model memorizes day-level identity.
