# Iter 15 Alpha Hypothesis — Top-of-book imbalance lean

## Hypothesis (one sentence)

Top-of-book imbalance `(bv1 − av1) / (bv1 + av1)` predicts the next 1–50 tick
mid move with slope ≈ +5 and R² ≈ 0.30 on both products across 4 independent
80%-randomized server slices — a signal my v82 port does not use.

## Specific quantified evidence

From `docs/round2_postmortem/features.md` (regression over 878 OSM + 881 PEP
ticks per slice × 4 slices):

| product | feature → target | slope | R² (avg) | R² (best) |
|---|---|---:|---:|---:|
| OSM | `top_imbalance` → `fwd_1`  | +4.85 | **0.33** | 0.34 |
| OSM | `top_imbalance` → `fwd_50` | +5.02 | 0.17 | 0.18 |
| PEP | `top_imbalance` → `fwd_1`  | +6.04 | **0.30** | 0.34 |
| PEP | `top_imbalance` → `fwd_50` | +5.88 | 0.30 | 0.33 |

An imbalance of +0.5 (bids twice asks at L1) predicts a mid move of +2.5 ticks
within 1 tick — and this holds across all 4 server slices with R² 0.28–0.34
per slice, not one lucky sample.

## Which ceiling assumption this breaks

My prior "ceiling ≈ $8,800" analysis treated OSM as a random walk with no
predictable component (mean mk50 ≈ 0 per bucket). That's wrong:
`top_imbalance` has R² 0.33 on fwd_1 OSM mid. The assumption that OSM mid is
unpredictable beyond spread capture was the binding constraint.

## Expected $/tick uplift (derived from data, not asserted)

- Per-tick mid-move signal: conditional expected move given imbalance = slope × imbalance. For tick events with |imbalance| > 0.5, expected move ≈ ±2.5 per tick in the signal direction.
- Fraction of ticks with |imbalance| ≥ 0.5: approximately 25 % based on L1 depth distribution (imbalance is bounded ±1, typical L1 bid vol 10–30, ask 10–30 → imbalance 0 to ±0.6 common).
- If we lean 40 extra units in the signal direction for each high-signal tick: expected gain per high-signal tick = 40 × 2.5 = $100/event with 25% of 1000 ticks = 250 events → $25 000 gross.
- Discount for: imperfect capture (not holding 40 units instantly), offsetting signal reversals (ACF-1 of returns is −0.47 — favorable), adverse selection from other players doing the same, MC-vs-server divergence. Realistic capture: **20–30 % of gross = $5–7k server uplift per slice**.

If the hypothesis is correct, server PnL moves from current $9.47k to ≈ $14–16k. If the hypothesis is wrong (MC gate passes but server shows no lift), the leaderboard-proven $13 k+ frontier must come from a different signal I haven't identified yet.

## Minimum viable implementation

In iter12's `_trade_osmium` and `_trade_pepper`, before computing quote prices:

1. Compute `imbalance = (bv1 − av1) / (bv1 + av1)` where bv1/av1 are the top-of-book sizes.
2. If |imbalance| ≥ 0.4 (threshold chosen to capture the strong-signal 25 % of ticks), add an inventory lean:
   - Target inventory shift = sign(imbalance) × min(20, 40 × |imbalance|)
   - Express this as additional quote-size skew on the side matching the signal direction
3. Quote layering, take logic, and PEP drift logic unchanged.

Single new parameter: `IMB_THRESHOLD = 0.4`. Justifiable from the feature distribution; one tuned parameter added → within budget.

## Pre-submission gates

- **MC per-tick ≥ $3.32** (iter13) — the imbalance-lean feature should at worst be neutral in MC (MC has similar book structure) and possibly positive. If MC drops by > 10 %, something is broken.
- **P05 ≥ 0** on --heavy.
- **Std / mean ≤ 0.2** — imbalance lean shouldn't blow up variance.
- **Sensitivity**: threshold of 0.3 and 0.5 should bracket 0.4 within ±20 % mean.

## Falsification

- If server PnL lands in the $9.2–9.6k band again (no change), hypothesis is
  wrong — the imbalance signal doesn't convert to real fill PnL (maybe because
  the book reacts faster than our order placement).
- If MC per-tick rises but server doesn't, the signal is an MC-simulation artifact of the deterministic bot structure, not a server feature. Abandon and move to lag-1 mean-reversion (next-largest signal, R² 0.22).
- If the change destabilises anything (P05 < 0, std blows up), skew is too strong — reduce the max lean from 20 units to 10 and retry.
