# Phase 3 quantification (on iter25_tb1, 3-day R2 training)

## 2.1 Phase 3 share of iter25_tb1 fills

61.6% of fills, 62% of notional (see verification doc). Both products individually:

| product | P2 buy / sell qty (3d) | P3 buy / sell qty (3d) |
|---|---|---|
| OSM | 2148 / 1763 | 2915 / 3238 |
| PEP | 1420 / 0   | 610 / 1790 |

PEP has no P2 sell because the strategy is long-only (initial accumulate phase); sell fills only happen through the recycle ask, which is phase 3.

## 2.2 Phase 3 misses — tape coverage

Tape events per day:

| product | tape trades / day | tape qty / day |
|---|---|---|
| OSM | ~465 | ~2376 |
| PEP | ~332 | ~1678 |

iter25_tb1 phase-3 fills per day: OSM ~2050, PEP ~800. So we're already capturing **~86% of OSM tape qty and ~48% of PEP tape qty**. Headroom from additional capture is modest.

## 2.3 Directional asymmetry

OSM phase 3 over 3 days: buy-fills 2915 vs sell-fills 3238 → **ask-hit biased by 5%**. Small.

PEP phase 3: 610 vs 1790 → strongly sell-biased, but this is an artifact of iter25_tb1 being long-only on PEP (it rarely quotes a large bid, so bid-side tape has no outlet).

Tape-side inference (tape price vs current mid):
- OSM: 48.0% below mid-5, 47.3% above mid+5 → **symmetric**. No usable day-level directional bias.
- PEP: 31.9% below mid-5, 35.5% above mid+5 → 4% ask-hit bias. Modest.

**Conclusion:** No large directional bias exploitable at the day level. Per-window direction is predictable via `r2_deterministic_schedule.md` but prior work falsified widening-the-adverse-side as an exploit.

## 2.4 Window concentration (day 0, 100k-ts windows)

| window | P2 | P3 | P3 share |
|---|---|---|---|
| 0–100k  | 269 | 240 | 47% |
| 100–200k | 140 | 259 | 65% |
| 200–300k | 135 | 330 | 71% |
| 300–400k | 179 | 348 | 66% |
| 400–500k | 113 | 340 | 75% |
| 500–600k | 211 | 213 | 50% |
| 600–700k | 180 | 337 | 65% |
| 700–800k | 172 | 269 | 61% |
| 800–900k | 169 | 235 | 58% |
| 900–1000k | 232 | 295 | 56% |

Mild concentration between 100k–500k (70%+ P3 share) and 600–700k. No dramatic step-up — windows are roughly uniform. Doesn't cleanly match the leaderboard player's step-up windows (34K–41K, 76K–83K on the server timestamp system) at 100x smaller scale.

## The real alpha angle — captured-side widening

From the tape price distribution (vs mid):

| bucket | OSM qty | PEP qty |
|---|---|---|
| (-inf, -5) | 3297 (48.0%) | 1548 (31.9%) |
| [-5, -3) | 103 (1.5%) | 93 (1.9%) |
| [-3, -1) | 40 (0.6%) | 664 (13.7%) |
| [-1, 1]  | 0 (0.0%) | 291 (6.0%) |
| (1, 3]   | 88 (1.3%) | 513 (10.6%) |
| (3, 5]   | 91 (1.3%) | 18 (0.4%) |
| (5, inf) | 3245 (47.3%) | 1722 (35.5%) |

**OSM has a gap**: essentially all tape is at mid±5+, with only 1.3% in each of the (mid+1, mid+3] and (mid+3, mid+5] buckets.

Implication: widening OSM quotes from the current mid±1 placement to mid±3 or mid±5 would miss at most 2.6% of tape (above-mid and below-mid 1–3 buckets) while tripling or 5×-ing per-fill edge on the remaining 97%.

### Back-of-envelope edge gain on OSM

Current iter25_tb1 OSM ask ≈ max(ba−1, dynamic_fv+1). When book is tight, ask lands at dynamic_fv+1. Phase 3 ask-hit fills/day ≈ 1080 at edge ≈ +1 = 1080 edge/day.

Candidate — ask at max(ba−1, dynamic_fv+3):
- Miss the 88 qty at (1,3] → stay with 3245+91 = 3336 above-mid tape qty / 3-day ≈ 1112/day
- Edge +3 per fill
- Day edge ≈ 1112 × 3 = 3336/day. **Δ ≈ +2256/day vs baseline** (symmetric on bid ⇒ ~4.5k/day).

Multiply by 3 days: headline theoretical gain ≈ **+13.5k over 3 days**. Real-world gain will be lower because:
- Our quote often extends past dynamic_fv+1 already (when ba−1 > dynamic_fv+1, the max kicks to ba−1)
- Inventory friction: widening reduces fill frequency → position hold skew
- PEP has material volume inside (1,3] (10.6%) — widening PEP is costlier

For OSM specifically, the widening is cheap and high-value. Candidate for iter27_phase3.
