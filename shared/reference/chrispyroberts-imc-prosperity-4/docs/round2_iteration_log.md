# Round 2 Strategy Iteration Log

Target: mean total PnL ≥ 13,000 on `prosperity4mcbt --heavy --round 2` with all
overfit gates passing (P05 ≥ 0, std/mean ≤ 1.0, per-product positive rate ≥ 80%,
±20% param sensitivity ≥ 10,000, held-out seed ≤ 15% drop, ≤ 3 tuned params per
product).

---

## Iter 0 — 2026-04-18 — Setup

**Products and bot behavior** (from `docs/round2_model.md`):

- **ASH_COATED_OSMIUM (OSM)** — fair = 10001 (constant). Wall at ±10, inner at ±8,
  bot-3 noise at ±1..±4 with 4% per-side presence. Takers 4.6%/tick, qty in [2,10].
  60% of taker volume hits the inner level, 20% wall, 12% bot-3, 8% other.
- **INTARIAN_PEPPER_ROOT (PEP)** — fair drifts +0.10/tick from day-start
  {−1: 11000, 0: 12000, 1: 13000}. Wall at ±10 (symmetric), inner at −6/+7
  (asymmetric), bot-3 at ±3/±4 (bid-heavy at 54%, ask-light at 7.5% before
  L3-truncation correction; code uses 3% / 1.5%). Takers 3.3%/tick, qty in [3,8].
  48% of taker volume hits bot-3 prices, 29% inner, 1% wall.

**Planned strategy family per product:**

- OSM: bot-aware market-making. Fair is static, so quote tightly inside the
  inner level on both sides. The calibration says 60% of takes hit the inner —
  owner priority means we need to be *one tick inside* the bot's inner to win
  the queue. Position skew to stay under the ±80 cap; no adverse-selection
  filter needed in iter 1 because OSM fair doesn't drift.
- PEP: drifting market-making. Quote around the per-tick deterministic fair
  with a symmetric spread. Skew on inventory. The PEP inner is asymmetric
  (bid@−6, ask@+7) so the symmetric strategy quote should be placed at
  ±5 or ±6 from fair. Takers are 50/50 despite the drift so inventory turn
  should stabilise on average.

Starting strategy: mirror this plan with a minimum-parameter version. The
existing `example_trader_round2.py` already does inside-inner MM but has
several free parameters — I'll rewrite it with 1 spread parameter per product
for iter 1.

**Infrastructure checkpoint:** strategy runner is now wired for `--round 2`
end-to-end; debug trader earns +4,065 in a single session (sanity fixed
baseline). Time to benchmark the real example trader.

---

## Iter 1 — 2026-04-18 — baseline `example_trader_round2.py`

Hypothesis: the existing R2 example trader (inside-best-bid/ask MM with a
hardcoded `pep_fair` using day 0 start) is a reasonable baseline. Measure and
identify the single biggest leak.

Change: none (baseline run).

Result (--quick, 100 sessions):
```
Mean total PnL:     4,466.40    Std:   69,337.53    P05: -63,078.95
OSM: mean 18,848  std 901     p05 17,433  +rate 100%
PEP: mean -14,382 std 69,236  p05 -80,712 +rate 34%
```

Biggest leak: PEP fair-value is hardcoded to day-0 start (12 000). On days
−1 and +1 the fair is off by ±1 000 ticks, so every PEP quote is systemically
mispriced. Sessions are bimodal (some days right, some wrong) → huge std.

Next: replace hardcoded day-start with `mid_of_book` as a per-tick fair
proxy.

---

## Iter 2 — 2026-04-18 — book-mid as PEP fair

Hypothesis: top-of-book mid tracks fair within ±0.5 ticks because the book
is centered on fair. This removes the wrong-day misprice.

Change: `fair = mid_of_book(depth)` for PEP; OSM unchanged.

Result (--quick):
```
Mean: 24,425    Std: 26,047    P05: -13,376
OSM: 18,718 / +rate 100%
PEP:  5,707 / +rate 58%
```

Over 13k mean but P05 < 0 (FAIL), PEP +rate 58% (FAIL), std/mean 1.07 (FAIL).
PEP is still the leak. Biggest remaining issue: bot-3 crossing bids
(54% per-tick presence) inflate top-of-book mid by 4-5 ticks, so `mid_of_book`
over-estimates fair in more than half of ticks.

Next: compute fair from the *deepest* visible levels instead of the top —
walls are symmetric so the deepest-mid is robust against crossing bot-3.

---

## Iter 3 — 2026-04-18 — deepest_mid for PEP fair

Hypothesis: `(min(bids) + max(asks)) / 2` returns the wall-mid when both
walls are present (the usual case) = floor(fair). Robust against crossing
bot-3.

Change: `fair = deepest_mid(depth)`.

Result (--quick):
```
Mean: -25,800    Std: 6,120    P05: -33,579
OSM: 18,718 / +rate 100%
PEP: -44,518 / +rate 0%
```

Regressed. With a now-accurate PEP fair, the `our_bid <= fair <= our_ask`
guard kills our bid in 54% of ticks (the crossing bot-3 bid inflates
best_bid above fair). We end up ask-only → systematic short drift → MTM
blow-up as PEP drifts up.

Next: stop anchoring quotes to best_bid/best_ask; anchor directly to
`floor(fair) ± inner_offset − 1` using the measured inner offsets from the
calibration.

---

## Iter 4 — 2026-04-18 — explicit inner-inside offsets

Hypothesis: Quote at `floor(fair) − (inner_bid − 1)` / `floor(fair) +
(inner_ask − 1)`. These don't depend on the current book top, so crossing
bot-3 can't break placement.

Change: parametric offsets via `OSM_QUOTE_OFFSET=7`, `PEP_QUOTE_OFFSET_BID=5`,
`PEP_QUOTE_OFFSET_ASK=6`. Keep `take_mispricing` for now.

Result (--quick):
```
Mean: -32,088    Std: 6,347    P05: -39,543
OSM: 17,720 / +rate 100%
PEP: -49,808 / +rate 0%
```

Worse. `take_mispricing` is firing on the crossing bot-3 levels (which look
"mispriced" relative to fair but are transient noise). Selling into every
crossing bot-3 bid ramps position to the −80 short limit within a few
hundred ticks, then PEP's +0.1/tick drift marks us down for the rest of
the day (~ −80×1000 = −80k MTM).

Next: drop `take_mispricing` entirely — there's no durable alpha in taking
bot-3 transients.

---

## Iter 5 — 2026-04-18 — passive-only quoting

Change: remove `take_mispricing`; passive quotes only at inner-inside
offsets.

Result (--quick):
```
Mean: 17,519    Std: 25,560    P05: -19,066
OSM: 15,539 / +rate 100%
PEP:  1,979 / +rate 50%
```

Mean again above 13k but still fails gates: P05 < 0, std/mean 1.46, PEP
+rate 50%. Inventory drifts and MTM-risk on PEP's drift dominates PEP's
variance. The passive quotes fill at roughly equal rates on both sides but
with no inventory control the terminal position has a heavy-tailed
distribution.

Next: add a single inventory price-skew term that shifts both quotes
against the position sign.

---

## Iter 6 — 2026-04-18 — inventory price-skew (current best)

Hypothesis: shift both bid and ask down by `position / SKEW_SCALE` ticks.
When long, lower ask makes us more eager to sell; lower bid makes us less
eager to buy. Net: drives position toward zero.

Change: add `OSM_SKEW_SCALE=40` and `PEP_SKEW_SCALE=20`. Heavier PEP skew
because PEP's drift punishes inventory harder.

Result (--quick):
```
Mean: 29,824    Std: 2,323    P05: 25,851
OSM: 14,060 / +rate 100%
PEP: 15,765 / +rate 100%
```

Result (--heavy, 1 000 sessions):
```
Mean: 29,631    Std: 2,397    P05: 25,528
OSM: 13,949 / +rate 100%
PEP: 15,683 / +rate 100%
```

All quick and heavy gates pass. Sensitivity sweep (`docs/round2_sensitivity.md`):
every ±20% / ±1-tick perturbation of the 4 tuned parameters keeps total mean
≥ 10 000. Held-out seed (99999) heavy sweep: 29,796 (+0.6% vs 29,631, well
inside the 15% tolerance).

Parameter budget:
- OSM: `OSM_EDGE=1`, `OSM_SKEW_SCALE=40` → 2 tuned (budget ≤ 3 ✓)
- PEP: `PEP_EDGE=1`, `PEP_SKEW_SCALE=20` → 2 tuned (budget ≤ 3 ✓)

All other constants (inner offsets, fair value, taker-quantity ranges) are
direct readouts from `docs/round2_params.json`.

### Overfit-gate summary

| Gate                               | Required | Actual | Pass |
|---|---|---|---|
| Mean total PnL ≥ 13 000 (heavy)    | ≥ 13 000 | 29 631 | ✓ |
| P05 ≥ 0                            | ≥ 0      | 25 528 | ✓ |
| Std / Mean ≤ 1.0                   | ≤ 1.0    | 0.081  | ✓ |
| OSM positive-rate ≥ 80 %           | ≥ 80 %   | 100 %  | ✓ |
| PEP positive-rate ≥ 80 %           | ≥ 80 %   | 100 %  | ✓ |
| ±20 % param sensitivity → mean≥10k | ≥ 10 000 | 17 506 | ✓ |
| Held-out seed drop ≤ 15 %          | ≤ 15 %   | +0.6 % | ✓ |
| ≤ 3 tuned params per product       | ≤ 3      | 2      | ✓ |
| No unjustified hardcoded literals  | —        | —      | ✓ |

Strategy: `iter6_trader.py`. Target achieved.

