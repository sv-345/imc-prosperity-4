# Order-flow investigation — what I actually found

## The mechanism

**Specific timestamps have big bot-bot trades (6-14 qty) that iter23
completely misses but iter26 partially captures.** The gap between
iter23 and iter26 is explained by iter26 having more sell-capacity
available at these critical moments.

## Key example: ts=96900 OSM

Bot-bot trades: 6 qty @ 10010, 8 qty @ 10010 (total 14 qty at $8 over mid).

| strategy | trades at ts=96900 | our_q | explanation |
|----------|-------------------|------:|-------------|
| iter23-303257 | BOT 6@10010, BOT 8@10010 | **0** | iter23 at pos ≈ −80, sell_cap = 0 |
| iter23-303280 | BOT 6@10010, BOT 8@10010 | **0** | same |
| iter23-314059 | BOT 6@10010, BOT 8@10010 | **0** | same |
| iter23-314132 | BOT 6@10010, BOT 8@10010 | **0** | same |
| tb1-313880   | BOT 6@10010, BOT 8@10010 | **0** | same (tb1 doesn't change take-gate) |
| tb1-313935   | SELL 1@10009           | 1 | tb1 happens to have 1 unit of capacity |
| tb1-313995   | SELL 3@10009, BOT 8@10010 | 3 | 3 units of capacity |
| iter26-316156 | **SELL 6@10009, SELL 8@10009** | **14** | c4_best kept pos short by ~60, had capacity |
| iter26-316195 | **SELL 6@10011, SELL 8@10011** | **14** | same |
| iter26-316247 | **SELL 6@10009, SELL 8@10009** | **14** | same |
| iter26-316311 | **SELL 6@10009, SELL 8@10009** | **14** | same |

**iter26 captures 14 qty × $7-8 edge = ~$100 that iter23 misses entirely** at this single timestamp.

## Why the difference

iter23 accumulates OSM short over the session (ends around −76 to −80).
By ts=96900 it's pinned at −80 → `sell_cap = LIMITS + pos = 0` → no ask
posted. When the bot-bot taker arrives, no ask of ours is in the book.

iter26_c4_best's position-conditional take-gate relaxation at |pos| ≥ 40
actively unwinds inventory by taking asks at mid during elevated regimes.
This keeps pos at around −60 to −70 by late session, preserving sell
capacity for taker events.

## Other big bot-bot events we miss

Per iter23 sample (~5-7 events per 1K-tick session):

| ts | product | bot qty | iter23 our_q | iter26 our_q | price | est. edge |
|---:|---------|--------:|-------------:|-------------:|------:|----------:|
| 96900 | OSM | 14 | 0 | **14** | 10010 | $8 |
| 44700 | PEP | 8 | 0 | 0 | 13040 | +$1 |
| 52600 | PEP | 8 | 0 | 0 | 13056 | +$1 |
| 33300 | PEP | 7 | 0 | 0 | 13037 | +$1 |
| 83000 | PEP | 6 | 0 | 0 | 13086 | +$1 |
| 9100 | OSM | 9 | 4 (partial) | — | 10000 | $0 |
| 0 | OSM | 6 | 0 | 0 | 10000 | $1 |

Totals (OSM events only, where edge is big):
- iter23 misses ~14-20 qty × $6-8 edge = **$100-160 per session** in OSM bot-bot events
- iter26 captures the ts=96900 event (+$100). Still misses others if any.

PEP scheduled events (ts=44700, 52600, 33300, 83000) trade at inner-ask
price which is ~$1 over mid. Even if captured, edge per event is ~$8
total. Not a big alpha source.

## Why "$500+ in one tick" is misleading

The biggest single-tick bot-bot events are ~14 qty × $8 edge = $112
maximum. There is NO single tick in the server data with $500+ of
edge in bot-bot trades.

However, cumulatively:
- 5-7 bot-bot events per session × ~$50-100 each = $250-700 per session
- Leaderboard at +$2,852 over iter23 mean could mean they capture
  ALL these events AND have additional mechanism

Realistically achievable alpha on top of iter26 = maybe +$100-200 per session
if we captured the remaining PEP events. Not $500/tick.

## Failed attempt: iter28 extra wall-price quotes

Posted extra asks at wall price at scheduled ts. Result: **−$2,486 vs tb1, −$907 vs iter23**.

The extra quotes get filled in OTHER ticks (non-scheduled) adversely, overwhelming any scheduled-tick capture.

Specifically: on non-scheduled ticks, the extra wall-price quote may get hit by random takers (especially when book is one-sided or wall is tight), at prices that aren't favorable for us.

## What might actually be happening with the leaderboard

Hypothesis: **they trade with HIGHER turnover and avoid getting
position-pinned.** If they maintain |pos| ≤ 50 throughout the session
(vs iter23/iter26 going to ±80), they ALWAYS have sell AND buy capacity,
so they can fill EVERY favorable taker event — not just the ones where
position allows.

This would require a different inventory-management strategy, not a
quote-placement change. iter23's fast-accumulate + recycle structure
pushes pos to limits by design.

**Candidate hypothesis to test**: reduce iter23's pos limit target from
80 to 50 (keep LIMITS=80 for safety but actively target ≤50). This
sacrifices some drift capture but preserves fill capacity.

But this is speculation — not backtested.

## Recommendation

**iter26_c4_best is still the best validated strategy.** The order-flow
investigation confirms iter26's mechanism: position-aware logic
preserves sell-capacity at critical taker events.

If you want to chase another ~$100-200 per session:
1. Test a position-target cap at ±50 instead of ±80 (active inventory management)
2. Test pre-emptive short-covering before known scheduled PEP taker events

Neither has been backtested; both risk reducing the $80 of PEP drift
per session × 80 = $6400 possible drift capture. Needs careful design
to not regress.

**The $500+ one-tick alpha, as framed, does not exist in the server
data I can see.** The alpha is cumulative across multiple smaller
events. iter26_c4_best already captures part of this.
