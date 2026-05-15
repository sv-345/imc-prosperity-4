# Step 2-3 — Event type hypothesis & validation

## Candidate mechanisms examined

### (1) Directional mid move iter23 doesn't capture — REJECTED
Window 2 has essentially flat OSM mid (start=end=10007). Not a directional move.
The leaderboard can't be winning via a directional trade that iter23 misses,
because there's no sustained direction to ride.

### (2) Volatility regime shift — PARTIAL
Both windows have elevated mid (Window 1 mid 9992-10010, Window 2 10007±stdev 2).
Window 2 is SUSTAINED elevated (vs spiky in Window 1). iter23 deals with this
differently — Window 1 gains normally, Window 2 gains flat on OSM. This hints at
a mechanism that needs SUSTAINED elevation, not transient spike.

### (3) Position limit pressure — REJECTED
iter23 OSM pos limit is 80. Ending position is -76 (full short) at EOD. iter23
uses its short capacity — not limit-pressured.

### (4) Bot appearance patterns — PARTIAL (schedule)
R2 has a deterministic bot-taker schedule (52.5% of OSM taker qty, 31% of PEP).
But no MM-style exploitation of the schedule passed backtest (exploration3
session fully tested). Probably not the mechanism here.

### (5) Cross-product coordination — REJECTED
OSM and PEP events are independent across days (session 3 finding).

### (6) Time-of-day effects — PRESENT but not directly exploitable
The 5K-ts buckets show OSM mid gradually rises 10000→10007 over the day,
with volatility clusters. Both claimed step-up windows fall in elevated-mid
buckets.

### (7) **MM quote anchor misalignment — CONFIRMED MECHANISM**
iter23 posts bid/ask anchored on static `fv = OSM_FV = 10001`:
- bid_pj = `min(bb + 1, fv - 1)` = **max 10000**
- ask_pj = `max(ba - 1, fv + 1)` = min 10002

During elevated regimes (mid ~10007), iter23's bid is at 9999-10000 —
7-8 ticks below mid. That's TOO WIDE to catch sell-takers near mid.
The leaderboard likely posts bids closer to actual mid (e.g., mid-2 = 10005),
catching sell-taker flow that iter23 misses, accumulating long, profiting
on reversion.

## Validation — Mechanism (7) ACROSS the 100K-tick run

Mid spends 52.5% of the day ≥ 10004. During those 525 ticks, the
"quote anchor misalignment" condition is present. This happens across
the full run, not just in step-up windows — so the mechanism is
detectable repeatedly.

iter23's PnL shape shows:
- Small losses in SUSTAINED elevated sub-periods (bucket 55K-60K: -$156;
  65K-70K: -$51; 50K-55K: -$12)
- Big gains when sustained elevation REVERTS (bucket 60K-65K: +$171;
  80K-85K: +$286; 85K-90K: +$211)

Net positive but with volatility. A fix that posts bids closer to mid
during elevation should:
- Accumulate long position during sustained elevation
- Profit on reversion (bigger than iter23 currently does)
- Not harm normal regimes (quote anchor reverts to ~10001 when mid is ~10001)

This is the mechanism we'll test in step 4.
