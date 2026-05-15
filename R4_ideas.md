# Round 4 — ideas (archive)

Compiled 2026-05-15 from `IMCR4/` before pruning.
Theme: "The More The Merrier" — counterparty disclosure mechanic was added.
Products unchanged from R3: **HYDROGEL_PACK**, **VELVETFRUIT_EXTRACT** +
10 VEV vouchers (TTE = 4 days at start of R4).

## Best performing strategy (preserved)

- **Strategy**: `IMCR4/submission/trader_r4_n24.py`
- **Backtester**: `IMCR4/backtester/` (8.9 GB — custom sim with cached data)

## What changed in R4

### Counterparty disclosure (new mechanic)

- `Trade.buyer` and `Trade.seller` now populated with **participant names**
  (NULL in R1–R3).
- IMC framing: "having insight into your counterparties could shift the
  balance for teams that know how to separate profit from pretense."
- IMC retroactively added counterparty IDs to the **historical
  Data Capsule** trade data → backtest counterparty signals on R1–R3
  logs **before** the live R4 sim runs.

### Manual challenge — "Vanilla Just Isn't Exotic Enough"

Standalone, no interaction with algo. Underlying = `AETHER_CRYSTAL`:
- GBM, **zero risk-neutral drift**, σ = **251% annualized**.
- Discrete grid: 4 steps/day, 252 trading days/year. "1 week" = 5 days = 20 steps.
- Tradable: underlying, vanilla calls + puts (2w / 3w expiries), chooser
  (3w, picks call/put at 2w), binary put, knock-out put (discrete obs).
- Scoring = mean PnL across **100 sims**. Contract size 3000 (flat
  multiplier). Price column is **cosmetic** — does not affect PnL.

## R4 exploit hypotheses (the alpha-discovery brief)

### A. Algo — copy-trade the omniscient bot ("Olivia")

**Background**: P3 ran "Olivia" who bought at daily low / sold at daily
high on certain products. Top P3 teams jumped huge by tagging Olivia's
fills in `market_trades` and copy-trading (max long when she buys, max
short when she sells). Reports of baskets going 50k → 120k per day.

**P4 R4 hypothesis** (IMC moved disclosure forward by one round):

1. Pull historical R1–R3 Data Capsule with the freshly-added counterparty
   IDs.
2. For each named counterparty, compute per product:
   - Fill-time vs intraday min/max (Olivia metric: fraction of buys
     within ε of daily low, sells within ε of daily high).
   - Average forward return over next N timestamps after their trades.
   - Net inventory drift (omniscient bots round-trip; predators
     accumulate).
3. Whichever name has near-perfect timing on HYDROGEL or VELVET → mirror
   them at max position-limit conviction.
4. Vouchers: an Olivia signal on VELVET is a directional signal on every
   voucher (delta-scaled). Use to bias voucher quoting / IV thresholds.
5. Secondary patterns from P3 wiki:
   - "Noisy" bot picked off by Olivia (P3 had Caesar) → trade with
     Caesar's loss-direction (against him, with Olivia).
   - Bot always quoting around mid → market-make against it.

**Risk**: IMC may have renamed Olivia or added decoys precisely because
the P3 exploit is famous. Always validate with backtest before sizing.

### B. Manual — exotics under 251% vol

σ√T over 3 weeks ≈ 0.612 → underlying ranges roughly ×0.55 to ×1.84.
Edges:

1. **Discrete-monitoring knock-out put** is *more valuable* than naive
   intuition suggests. With 4 obs/day × 15d ≈ 60 obs, paths can dip
   below the barrier between checks without triggering. Discrete-KO > continuous-KO.
2. **Chooser put-call parity**: under zero drift / no carry, simple
   chooser = `C(K,T) + P(K,t1)`. Compute fair value vs vanilla
   combinations; any portfolio of {C, P, chooser} that's
   net-positive-EV / net-zero-price is free money.
3. **Binary put**: under GBM zero-drift, `P(S_T < K) = N(-d2)` with
   `d2 = ln(S0/K)/(σ√T) − (σ√T)/2`. EV = payout × P. Compare against
   displayed price and vanilla put with same K.
4. **100-sim fragility**: IMC marks PnL using the mean payoff across
   exactly 100 underlying paths. With σ=251%, sample-mean of non-linear
   payoffs has high variance vs true expectation. If **the IMC seed is
   fixed**, the realized 100-path mean is deterministic but not the true
   fair value. **Build a 1M-sim MC; instruments where your mean is
   significantly above the implied IMC mark = long; below = short.**
   *Highest-EV move in the manual leg if seed is fixed.*
5. **Skew / put-call asymmetry under zero drift**: log-normal underlying
   → calls worth more than puts of same strike. Asymmetry is huge at
   σ=251%. If displayed prices treat them symmetrically, long calls /
   short puts (same strike) is structural alpha.
6. **Portfolio optimization with position caps**: since price is
   cosmetic, maximize `Σ units_i × E[payoff_i]` under per-product caps.
   Run MC, rank by EV/unit, fill highest-EV first. Hedge tail with
   underlying.

## Action items (the original R4 brief)

- [ ] Download R4 Data Capsule (now with counterparty IDs).
- [ ] Run Olivia-detection on HYDROGEL + VELVET trade history.
- [ ] Build a Trader scanning `state.market_trades` for the omniscient
      name → ride the signal at limit.
- [ ] Build AETHER_CRYSTAL MC (GBM, σ=2.51, 4 steps/day, 252/year, zero
      drift) — get true FVs of every listed exotic.
- [ ] Compare IMC displayed prices vs your FVs; rank EV / position-cap unit.
- [ ] Sanity-check chooser via put-call parity.
- [ ] Hedge unhedged-loss warning with underlying + vanilla offsets.

## Position limits

| Symbol | Limit |
|---|--:|
| HYDROGEL_PACK | 200 |
| VELVETFRUIT_EXTRACT | 200 |
| VEV_4000 … VEV_6500 (10 vouchers) | 300 each |

## Final result

Submitted `trader_r4_n24.py`. PnL not recorded in memory; consult
submission history if needed. Preserved alongside the local backtester
for any future re-run.
