# Round 1 — ideas (archive)

Compiled 2026-05-15 from `ROUND_1/` before pruning.
Products: **ASH_COATED_OSMIUM** (OSM, mean-reverting, FV ≈ 10001) and
**INTARIAN_PEPPER_ROOT** (PEP, drift FV: day_start + 0.10·tick, day_start
∈ {11000, 12000, 13000}).

## Best performing strategies

| File | Server PnL | Notes |
|---|---:|---|
| `strategies/244644.py` (v82_hardened) | **$10,859** on 1d × 1k ticks | End-of-round preserved submission. OSM $3,279 + PEPPER $7,580 (PEP ≈ 70%). Log + tradeHistory preserved in `244644.log` / `244644.json`. |
| `strategies/trader_safe_10721.py` (sub 127989) | $10,721 | Training-data champion. Multiple submissions confirmed the server market is deterministic across submissions; only PnL differs. |

An earlier scoring run on v82_hardened (sub 273632, not preserved on
disk) reportedly produced $101,199.69 on a 1-day × 10k-tick session.
The 10× ratio matches the tick-count ratio against the preserved
1k-tick log; use the 1k figure when comparing across R2–R4.

### Trade breakdown — sub 244644

- **OSMIUM:** 92 fills, 270 bought / 231 sold over the day. Net long
  ~39 going into the close. PnL = $3,279 from passive MM net of
  the deterministic OSM taker schedule.
- **PEPPER:** 41 fills, 120 bought / 40 sold. Net long ~80 — the
  drift position is the position, not a by-product of MM. PnL = $7,580.

Counterparty fields (`buyer` / `seller`) are blank in R1, so post-hoc
counterparty analysis is not possible on this log. The R4 retroactive
disclosure should populate them in the R1 Data Capsule if revisited.

The local MC backtester lives in `ROUND_1/mc/` — calibrated to ρ=1.0
Spearman rank vs server across 4 submitted strategies.

## Bot models (verified, R1)

### OSMIUM
- **Outer wall**: ±10/±11 (97.1% of ticks `spread=21`, random −10/+11 or
  −11/+10). 100% presence.
- **Inner wall**: ±8 symmetric (95.3% match in data).
- **Bot 3**: rare near-mid noise, ±2 from FV. Rate 2.5% (bid 2.60%, ask 2.49%). 759 events at exactly ±2.
- **Taker flow**: 100%-sell on OSM (verified). Multi-trade fraction
  observed. Qty distribution {2..10} weighted from 1,265 trades.
- **FV**: random walk, σ=0.31171/tick. Hard-coded anchor 10001 — using
  empirical mean 10003 hurts PnL by 26% because ask_ep=10013 lands on the
  ask wall behind the bot queue.
- **3-phase taker schedule** (deterministic across days): qty 6 → 10 → 4.
  Not exploitable via MM quote placement — tape-fixed prices kill the
  widens that would benefit.

### PEPPER
- **Outer wall**: scales with FV level (±8 at 10K, ±10 at 12K). Approx
  `wall_offset = round(FV × 0.0008)`.
- **Inner wall**: offset C varies by FV level (6–8). Vol U(8,12).
- **Bot 3**: rate 1.5% (bid 1.48%, ask 1.56%).
- **FV**: Gaussian walk, drift = 0.10/tick, σ = 0.496.
- Direction autocorrelation ρ = 0.85 (strong trending).
- **Taker qty**: {3..8} weighted from 1,011 trades.

## Key calibration bug: the PnL double-count

Original backtester added BOTH per-tick mark-to-market (`pos × ΔFV`) AND
final position value (`pos × final_FV`). With PEP 80-unit position and
100-point FV drift this added ~8,000 phantom PnL.

**Fix**: track cash flows only during simulation; compute
`PnL = cash + pos × final_FV` at the end (matches the chrispyroberts Rust
sim). PEPPER error dropped from +117% to +0.2%. **Apply this pattern to
any backtester rewrite.**

Other calibration fixes that mattered:
- Trade rate per tick: not 12% across both — OSM 4.2%, PEP 3.4% on 10k
  data. Effective per-tick rate higher on 1k server window. Grid-search
  OSM to 18%/tick against server PnL.
- Bot price-priority at same price: bots at owner=0 fill before player at
  owner=1. Model explicitly or strategy PnL overstates.
- One-sided book fallback exploit: when recorded book is one-sided, the
  strategy's fallback at `fv ± edge` becomes the only level. MC takers
  hit it at absurd prices. **Fix**: clip taker fill prices to ±5 ticks of
  recorded L1.

## Validated alpha and dead alphas

| Alpha | Result | Notes |
|---|---|---|
| Penny-jump + edge dominates plain MM | **+36%** on OSM | inside quote captures small takers cheap; wall captures large takers at edge |
| OSM edge=10 vs 14–16 | edge=12 better (DRO), but plateau 10–16 within 1σ | pick mid, don't chase across plateau |
| PEP trending sq=4 | DRO winner | aligns with drift direction |
| Buy-only on trending PEP | misses MM edge ~330/seed | trending captures MTM but loses spread |
| OSM wall_offset=10 | optimal | walls are asymmetric −9/+10 |
| Wall-aware OSM (v15) | **regressed −161 on server** | beat 127989 on 8/8 training-replay seeds; lost on real server. Memory was wrong about net benefit. |
| Wall-FV alpha (v17 wall_fv variants) | **regressed −204 on server** | DEAD. Do not submit. |
| Dynamic OSM gate (iter24, R2-era) | −$829/day in backtest | trap |
| Wider OSM Bot-3 offset distribution | ruled out | all 759 events at exactly ±2 |

## 4-phase methodology (the reusable playbook from R1)

This is the playbook that delivered ρ=1.0 ranking validation and matched
the DRO-optimal config (OSM edge=12, PEP trending sq=4) with submission
127989.

### Phase 1 — Hint extraction (half-day)
Read every `.md` / README / inline comment in the shipped Prosperity repo.
Extract product names, base prices, inventory limits, trade structure,
scoring formula, any hint of bot count/types. Don't over-invest — 60%
gets overwritten by Phase 2.

### Phase 2 — Data-first statistical profile (1–2 days)
- FV process per product: σ/tick, drift, quantization. Don't assume GBM;
  look at empirical increments.
- Bot quote identification: cluster quoted levels by FV offset; identify
  wall / inner / Bot3 archetypes. Fit `price = f(fv)`, vol dist, presence
  rate per bot.
- Taker flow: per-tick Bernoulli, qty dist, side-buy frac, level weights.

**Rule**: every number in the MC must trace to Phase 2. If you can't
justify a constant, you haven't profiled enough.

### Phase 3 — Three-level MC validation (1–2 days)
1. **Book-replay**: replay strategy against recorded server book with MC
   takers. Pass: within ±3σ of server PnL (PEPPER 100.15%, OSMIUM 70.55%
   but +3σ on N=1 server obs).
2. **Ranking preservation**: port 3–4 submitted strategies, compute
   Spearman ρ vs server ranking. Pass: ρ ≥ 0.9 total, ≥ 0.8 per-product.
3. **Parameter sensitivity**: sweep one parameter, check monotonicity.
   Plateaus are OK (edge 12–20 was flat in R1).

### Phase 4 — DRO (1 day)
Uncertainty set Ξ (6 scenarios works): baseline, taker_rate × {0.7, 1.3},
taker_qty extended, first/second half of session. Grid θ × Ξ × seeds.
Report mean per scenario, min-scenario mean (DRO objective), CVaR@5%.

**Choice rule**: if EV-optimal == DRO-optimal → ship. If differ → prefer
DRO unless EV gap > 10% AND min-scenario gap < 5%.

## DRO sweep finding (Phase 4)

- OSMIUM: edge=12 wins by a hair; plateau edge=10–16 within 1σ. min
  scenario tie at 1071.
- PEPPER: trending sq=4 dominant.
- MC bug patched mid-sweep: taker-band ±5 ticks around L1 (kills
  one-sided book exploit).
- Synthetic MC diverges from book-replay when training session has
  correlated regimes — use book-replay as primary; synthetic for stress
  only.

## R1 official result

Final submission **273632** (v82_hardened) = **$101,199.69** on 1 day ×
10k ticks server eval. ~81% PnL from PEPPER drift. ~$1–2k recoverable
from tightening OSM weak crosses but wasn't pursued.

In MC, **127989 (10,721)** was still the durable champion. v100_scratch
hit 10,732.47 server (+11) but the gap is sub-noise. ~13k unreachable
via pure MM tuning.

## Gotchas to remember

1. **Single-session baseline is weak.** Server PnL is 1 sample — within
   ±3σ = unfalsified, not validated.
2. **MC overpredicts book-structure changes.** Wall-FV variants looked
   great in MC, regressed on server.
3. **Parameter plateaus are real.** Don't chase 1% across a plateau;
   pick the middle and stop.
4. **Don't "correct" the strategy's anchor** if it's a hard-coded input
   (OSMIUM fv_anchor=10000 wins despite empirical 10003).
