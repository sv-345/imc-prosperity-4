# Three-phase tick structure verification

## Result: VERIFIED (mechanism is as hypothesized)

## Direct evidence

The prosperity3bt runner (`chrispyroberts-imc-prosperity-4/backtester/prosperity3bt/runner.py`) implements the tick loop as:

```
for each timestamp t:
    1. prepare_state(state, data)    # builds order book from data.prices[t]  ← Phase 1
    2. trader.run(state) → orders    # trader sees book, emits orders        ← Phase 2
    3. match_orders(state, data, orders, ...)                                ← Phase 3
       ├── match against state.order_depths (resting book)   [Phase 2 take]
       └── match against data.trades[t] market_trades         [Phase 3 tape]
```

`match_buy_order` / `match_sell_order` do a **two-stage match**: first your orders cross the resting book; then your remaining quantity is matched against recorded tape trades at the same timestamp. The tape-match loop is literally "orders that arrive after your Trader.run() returns", which is the phase 3 the community hint described.

## Test 1.1: Does phase 3 exist? YES.

Instrumented iter25_tb1 over 3 R2 training days (runner.match_buy_order / match_sell_order monkey-patched to tag each fill by phase):

| phase | fill count | qty | notional |
|---|---|---|---|
| PHASE2_BOOK (take resting book) | 5,331 | 5,331 | 56.7M |
| PHASE3_TAPE (match vs recorded tape) | 8,553 | 8,553 | 91.6M |

**Phase 3 accounts for 61.6% of iter25_tb1 fills by count and 62% of notional.** The hypothesis is not subtle — it's where most of the fills come from.

## Test 1.2: Market orders vs limit orders? EFFECTIVELY MARKET.

The Prosperity CSV tape does not label aggressor (buyer/seller columns are all blank on both products across all 3 days — `buyer_named=0, seller_named=0`). Direct market-vs-limit classification is not possible from the data.

Indirect evidence points strongly at market-order/sweep behavior:

| product | tape price vs current mid | share of tape qty |
|---|---|---|
| OSM | ±5 ticks or more | **95.3%** (48.0% at ≤mid−5, 47.3% at ≥mid+5) |
| OSM | inside ±5 | 4.7% |
| PEP | ±5 ticks or more | 67.4% (31.9% below mid-5, 35.5% above mid+5) |
| PEP | inside ±5 (incl. the ±1 "zero-dev" bucket) | 32.6% |

On OSM, 95% of tape trades occur at prices ≥5 ticks from current mid — these cross multiple book levels in one trade and are consistent with aggressive takers sweeping the book, not passive limits resting. The backtester's tape-match loop models them as fills against our limits at our price (conservative to us) — exactly the hypothesis's signature.

## Test 1.3: Directionally predictable? YES (already established).

Prior memory (`r2_deterministic_schedule.md`): 50% of OSM taker qty and 31% of PEP taker qty fire at seeded timestamps with identical qty + direction across all 3 training days. So direction IS predictable; the previously-failed exploitation angle was quote widening on adverse side, which fails because the tape prices are fixed far from mid and widening just misses the fill without improving edge.

The previous memory's falsification applies to **widening the adverse side**. It does not apply to **widening the captured side**, which this study shows is the actionable angle — see Step 2.

## How this reframes prior findings

- **iter25_tb1's win over iter23**: iter25_tb1 swapped `fv → dynamic_fv` in bid_pj/ask_pj. This shifts the ask by +1 when dynamic_fv is 1 above OSM_FV (which is the common regime). That +1 tick of extra edge is applied to the 62% of iter25_tb1's notional that comes from phase 3 tape — validates the mechanism.
- **iter24's dynamic-gate failure**: iter24 widened the phase-2 take threshold. That removed passive collection at the asks resting at 10002–10007 which were being hit by phase-3 tape. The explanation in memory ("tape fills at deep prices") is confirmed.

## Non-obvious surprises worth flagging

1. **Phase 3 is quantitatively larger than phase 2**, not a small add-on. The old mental model of "take opportunities against resting book with MM quotes as a defensive layer" was inverted.
2. **Tape price is nearly bimodal at mid±5+**. This is a strong structural fact: quote placement between mid+1 and mid+5 loses almost no tape fills, because the tape is either at mid±(0..1) or mid±5+, with a near-empty gap between.
3. **Backtester fills us at OUR price, not tape price.** Of 1,714 phase-3 fills we logged, 1,703 had `tape_worse_than_our_quote<0` — tape was further from mid than our quote. The edge captured per fill = our_quote - mid.
