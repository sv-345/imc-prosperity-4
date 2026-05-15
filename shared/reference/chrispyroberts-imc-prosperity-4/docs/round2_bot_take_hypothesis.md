# Iter 20 — Bot-take direction-aware inventory lean

## Hypothesis

When the most recent tick's `market_trades` contain a net BUY-side bot take
on product X, the next-tick mid for X will rise by ≈+5 ticks (PEP) or +1
tick (OSM), with z-scores of 19.5 and 2.76 respectively on 395 measured
bot-bot takes. Conditioning inventory skew on this event-driven signal
(instead of aggregate imbalance) should convert to server PnL because it
uses the causal trigger rather than a transient proxy.

## Specific evidence

From `docs/round2_bot_take_extraction.md` (ledger on 395 takes combining R1
+ R2):

| product | side | n | fwd_1 mean | fwd_10 mean |
|---|---|---:|---:|---:|
| OSM | buy | 57 | +1.02 (z=+2.76) | +1.20 (z=+3.60) |
| OSM | sell | 72 | −0.97 (z=−3.73) | −0.82 (z=−2.93) |
| PEP | buy | 60 | +5.38 (z=+19.5) | +6.06 (z=+21.0) |
| PEP | sell | 164 | −2.15 (z=−7.3) | −1.44 (z=−5.0) |

**PEP buy-take z=19.5 on fwd_1 is 5× larger than any aggregate-book signal
I've measured.** This is the causal chain; imbalance R²=0.33 was the shadow.

## Which ceiling assumption this breaks

My earlier rounds implicitly assumed mid-move signal was measurable only
from book-state snapshots (imbalance, spread, momentum). The actual stream
of taker events is a higher-quality signal on precisely the moments when
mid is about to move. iter15-19 never read `state.market_trades`.

## Expected $/tick uplift (from data)

PEP: fwd_10 for buy-take = +$6.06, sell-take = −$1.44. If I lean +10 PEP
for each buy-take event (17 events/slice avg) and short 10 for sell-takes
(41 events/slice)... but capped at ±80 position, plus drift-long already at
+80 most of the slice, short is effectively prohibited.

More realistic: during the PEP accumulation phase (pos 0..80), an observed
buy-take signal means "buy MORE aggressively this tick — mid about to rise."
A sell-take means "defer buying — mid about to drop, entry price will be
better in 1-10 ticks."

Quantitative estimate:
- 17 PEP buy-takes per slice. If each makes me buy 5 extra units at fair
  instead of waiting 1 tick and paying fair+5.38: saves 5 × 5.38 = $27/event.
- Total: 17 × $27 = **$460 per slice on PEP alone**.

OSM signal is weaker (fwd_1 = ±$1) but still tradable: 13 takes/slice × 5
units × $1 = $65/slice extra.

**Total conservative estimate: +$500/slice**. Aggressive estimate (fully
exploiting the magnitude via larger position changes): +$1500/slice.

## Minimum viable implementation (iter 20)

1. Track recent `market_trades` — per-tick, classify each trade by side
   (price vs best bid/ask), sum into `net_take[product]` over a sliding
   3-tick window.
2. In `_trade_osmium` and `_trade_pepper`, compute `take_shift` from
   `net_take` signal. For |net_take| ≥ 2 units net direction:
   - Positive: shift bid_pj +1 (more aggressive buying), widen ask_pj +2
     (defer selling — we'll sell at better price after up-move).
   - Negative: mirror.
3. No new tracking for "who did the take" — just direction from price.

Single conceptual parameter: `NET_TAKE_THRESH = 2` (units of net take to
trigger skew). All other constants trace to existing v82 values.

## Pre-submission gates

- **MC per-tick ≥ $3.32** — iter12 baseline. Bot-take signal might or might
  not appear in MC (Rust sim has independent bot takers). If MC drops > 5%,
  abandon. Bot-take signal on server is confirmed at z=20; server
  improvement doesn't require MC confirmation.
- P05 ≥ 0 on --heavy.
- Stability: std/mean ≤ 0.2.

## Falsification

- If server PnL doesn't move by ≥ +$200/slice, the take-event feature
  doesn't convert to fills faster than the signal decays. In that case,
  the signal is measurable but not tradable via quote-shift (too slow).
- If server PnL moves down by more than −$200, the "shift quote on take
  signal" is actively harmful — maybe takers ARE informed and we're now
  selling into buy-take signals (wrong sign).
