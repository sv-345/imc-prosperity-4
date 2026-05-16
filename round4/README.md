# Round 4 — ideas (archive)

Compiled 2026-05-15 from `IMCR4/` before pruning.
Theme: "The More The Merrier" — counterparty disclosure mechanic was added.
Products unchanged from R3: **HYDROGEL_PACK**, **VELVETFRUIT_EXTRACT** +
10 VEV vouchers (TTE = 4 days at start of R4).

## Best performing strategy (preserved)

- **Strategy**: `round4/submission/532407.py` (nN33_voucher_imb_skip)
- **Server PnL**: **$67,193** (sub 532407, 1 day × 1k ticks)
- **Log / trades**: `532407.log` / `532407.json`
- **Backtester**: `round4/backtester/` (custom sim with cached data)

### PnL attribution — sub 532407

| Product               | Server PnL | Notes                                                                  |
| --------------------- | ---------: | ---------------------------------------------------------------------- |
| VEV_5000              |    $11,396 | Counterparty-aware delta-1 voucher MM.                                 |
| VEV_5100              |    $10,899 | Same.                                                                  |
| VEV_4500              |    $10,066 | Same.                                                                  |
| VEV_4000              |     $9,595 | Same.                                                                  |
| VEV_5200              |     $8,723 | Same.                                                                  |
| VELVETFRUIT_EXTRACT   |     $7,649 | Mark 14 / 22 / 55 / 67 counterparty signals — 3× R3's VELVET take.     |
| VEV_5300              |     $5,273 | Counterparty-aware.                                                    |
| VEV_5400              |     $2,148 | Counterparty-aware.                                                    |
| HYDROGEL_PACK         |     $1,445 | **Collapsed from $21,685 in R3.** See failure note below.              |
| VEV_5500 / 6000 / 6500|        $0  | Wings still produce nothing — same as R3.                              |
| **Total**             | **$67,193** |                                                                        |

### Counterparty signals that worked

The R4 disclosure populated `Trade.buyer` / `Trade.seller`. Three named
participants carried the round:

- **Mark 67 — directional prophet.** 95.4% H = 1 hit rate on VELVET and
  vouchers. When Mark 67 buys, set a 10-tick cross-bias bid on the
  underlying and on positive-delta voucher strikes; symmetric on sells.
  This is the signal that tripled voucher PnL relative to R3.
- **Mark 14 — maker queue reference.** Mark 14 quotes the inside on
  HYDROGEL and VEV_4000 heavily. "Be like Mark 14" became the
  make-side rule: MM at `bb` / `ba` (not `bb + 1` / `ba − 1`) on
  deep-ITM vouchers. Backtest +$7,248 vs the wider quote.
- **Mark 22 — sell anticipation.** When Mark 22 sells a voucher this
  tick, post bid at `bb + 1` for queue priority on the recovery flow.

Counterparty IDs were used as *signals into existing edges* (queue
placement, take sign, cross-bias duration), not as standalone
trade triggers. Naive copy-trading of Mark 67 at market would not have
placed; biasing existing quotes by 1–3 ticks on his prints did.

### HYDROGEL collapse — what failed

HYDROGEL produced $21,685 in R3 (anchor-relative take, anchor = 9991,
edge = 28) and only $1,445 in R4 against essentially the same logic.

Trade tape: 43 fills, **200 HYDROGEL sells with 0 buys**. The
counterparties on those sells were Mark 01 (98), Mark 14 (92), and
Mark 38 (10). Once counterparties are disclosed, the anchor-relative
take gets one-sidedly run over — we sell at `anchor + edge` and the
named makers immediately re-quote at or above that price, eliminating
the convergence premium that worked in R3.

The R4 trader did not adapt HYDROGEL anchor-take to the new regime.
Plausible fixes for a future round with the same structure:

- Throttle the anchor sell when Mark 01 / Mark 14 are net buyers of
  HYDROGEL in the same tick.
- Widen the edge when counterparty composition suggests adverse
  selection.
- Or accept that anchor-take is fragile under disclosure and shift
  HYDROGEL into pure passive MM as in earlier R3 iterations.

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

Submitted `532407.py` (nN33_voucher_imb_skip). Server PnL **$67,193** on
1 day × 1k ticks. Full attribution above; counterparty-aware voucher MM
on the 4000–5300 strike band carried the round. HYDROGEL is the major
regression from R3 and the most informative failure of the season.
