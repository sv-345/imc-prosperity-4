# Round 2 — Self Post-mortem

Applies the docs/round1_postmortem methodology to my own R2 submissions.
Four v82-family submissions (iter 12 × 2, iter 13 CF3, iter 14 wider PEP).
Raw per-fill ledger: `scripts/r2_postmortem/ledger_all.csv` (367 fills).

See sibling documents:
- `docs/round2_postmortem/leaks.md` — leak-category breakdown with $ cost
- `docs/round2_postmortem/features.md` — regression of tick features on forward mid moves

## Headline findings

### The largest *leaks* are small ($100–400 per slice each)
From leaks.md:
- Adverse-selection flagged fills (N4, M50): -$421/slice (48 fills, 13% of total)
- OSM wrong-direction fills (mk50 ≤ −5): -$227/slice
- R1-CF3 weak OSM crosses (mk50 ≤ +5): -$28/slice direct, roughly break-even forward
- OSM deep-passive adverse drift: -$193/slice (155 fills slightly adverse on 50-tick horizon)
- PEP SELL wrongs: -$778 total (drift arithmetic, not a leak)

**Sum of actionable leaks across all categories: ~$600/slice if every one could be perfectly filtered.** That closes half the $3.5k gap at best. Leak hunting alone does not reach $13k/slice.

### The largest *feature signals* are **orders of magnitude bigger**
From features.md:
- **`top_imbalance` → fwd_50 mid move**: OSM slope +5.02, R² **0.17**; PEP slope +5.88, R² **0.30**
- **`top_imbalance` → fwd_1 mid move**: OSM slope +4.85, R² **0.33**; PEP slope +6.04, R² **0.30**
- **Lag-1 mid-return autocorrelation**: OSM **−0.47**, PEP **−0.50** (R² ≈ 0.22). Strong mean reversion.
- **`bot3_ask` indicator → fwd_50**: OSM slope +4.32, R² 0.09. PEP similar.

These are large, robust, present on both products, and my v82 port **uses none of them**.

## Why this is different from prior analyses

Previous attempts assumed "ceiling = analytical spread × taker rate × position". That framing treats the strategy as exploiting pre-known bot mechanics. But top leaderboard PnL (admin-confirmed to exist ≥ $13k) implies someone is trading a *predictive* edge, not just mechanics. The R² 0.30 imbalance → fwd_1 regression is the first evidence I've produced of a direct predictive signal in the R2 data that I haven't implemented.

## Decomposition of what v82 captures vs misses

| source | $/slice captured by iter12 | $/slice ceiling (measured) | gap |
|---|---:|---:|---:|
| PEP drift × inventory | +7 400 | +8 000 (80 × $100) | +600 |
| OSM wide-snipe + inside MM | +1 800 | ~$2 000 (R1 scaled) | +200 |
| OSM cross-edge capture | included | +$918 forward markout on crosses | partly already |
| **Imbalance-driven mid prediction** | **0** | **$3–6k estimated** | **-3000 to -6000** |
| Mean-reversion (ACF-1) | 0 | $1–2k estimated | -1 000 to -2 000 |
| Bot-3 presence signal | 0 (implicit in quoting) | $0.3–0.7k | -300 to -700 |

**Total missing alpha from unused features: $4–9k per slice.** That matches the ≥$3.5k gap needed to hit 13k.

## Data quality notes

- R² values of 0.30 are out-of-sample in the sense that each submission is an
  independent 80%-randomized slice; the same feature has the same predictive
  power across 4 different slices.
- The mean-reversion ACF is partly inflated by the bid-ask bounce: when mid
  jumps up because bot-3 ask arrives, it jumps back down when bot-3 leaves.
  That's a real, tradable mean-reversion but the true fair may be stable. The
  imbalance feature captures the underlying book-state mechanic more directly.
- Fill density matches R1 scaled within 10–15 %, so strategy is not fill-starved
  or overfilling. The improvement must come from *better fills*, not more fills.
