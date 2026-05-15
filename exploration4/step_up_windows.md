# Step 1 — Step-up window characterization

## Data source

iter23 baseline submission 303257 (full 1000-tick / 100K-ts day-1 server
run). PnL = $9,231.19. Full PnL trajectory in `iter23_pnl_303257.csv`.

## Claimed step-up windows (from leaderboard comparison)

| window | ts range | leaderboard gain (from image) | iter23 gain | gap |
|--------|----------|------------------------------:|------------:|----:|
| 1      | 34,000-41,000 | ~$1,000 | $955.75 | ~$45 (minor) |
| 2      | 76,000-83,000 | ~$1,000 | $546.81 | **~$450** |

iter23 sample 2 (303280) for robustness:
- Window 1: $792.66 (similar)
- Window 2: $580.91 (similar)

## Product-level breakdown (sample 303257)

**Window 1** (ts=34,000-41,000):
- OSM gain: +$297.75, mid range 9992-10010, mid drift -1.5 (mild)
- PEP gain: +$658.00, mid range 13031-13049, mid drift -3
- Dominant driver: PEP (69% of window gain)

**Window 2** (ts=76,000-83,000):
- OSM gain: -$13.19 (essentially flat)
- PEP gain: +$560.00 (100% of window gain)
- OSM mid: 10007.0 → 10007.0, range 9997-10015 (volatile but no net drift)
- PEP mid: 13078.0 → 13088.0 (steady +10 drift)
- Dominant driver: PEP drift. OSM is flat.

## iter23's own biggest gain window

The 4K-ts window with highest iter23 gain is **ts=83,500-87,500** (+$570 on OSM
alone, +$903 total). This is where OSM mid drops from 10015 → 9998 (big
mean reversion). iter23 captures the reversion.

## Regime classification

OSM mid distribution in the 1000-tick session:
- 52.5% of ticks: mid ≥ 10004 ("elevated" regime)
- 43.2%: 9999-10003 ("normal")
- 4.3%: mid ≤ 9998 ("deflated")

iter23 PnL per regime:
- Elevated (525 ticks): total +$1,188 ($2.26/tick) — gains the most here
- Normal (432 ticks): total +$256 ($0.59/tick)
- Deflated (43 ticks): total +$120 ($2.78/tick)

## Contiguous elevated segments and reversions

23 contiguous elevated-regime onsets. 14 revert within 50 ticks, 9 don't.
Of the 14 that revert:
- Avg peak mid: 10006.14 (only +5 above static FV)
- Avg duration: 13 ticks to revert
- Avg reversion magnitude: 3.79 ticks
- Avg iter23 PnL gain during event: $29.58
- Total iter23 gain across reversion events: $414.11

## Key observation

Window 2 overlaps contiguous elevated segments:
- 75100-77000 (peak 10008, post 10007 — partial reversion only)
- 77900-80300 (peak 10012, post 10007 — partial)
- 81200-83000 (peak 10015, post 10006)

iter23's quote placement is anchored on the static `OSM_FV = 10001`.
During these elevated regimes, iter23's inner bid is at `min(bb+1, fv-1) = 10000`
which is **7-8 ticks below actual mid** (10007). Iter23 doesn't post
competitive bids near the actual mid, so it misses sell-taker fills
that the leaderboard may be capturing.
