# Candidate bot-behavior rules — R2 exploration

Session date: 2026-04-18. Data: `ROUND_2/prices_round_2_day_{-1,0,1}.csv` + trades.

---

## Candidate rule 1 — PEP aggressive bot-3 one-tick reversion — HIGH CONFIDENCE

### Observation

On PEP (INTARIAN_PEPPER_ROOT), every 10k-tick training day contains ~160
"aggressive-bid" events (a bid quote appears at floor(FV) or above) and
~150 "aggressive-ask" events (an ask appears at floor(FV) or below),
where FV = day_start + 0.1·(ts//100).

Example (day 0, ts=2900, floor(FV)=12002):

```
t-1 (ts=2800):  bid@11996(-6)  ask@12009(+7)   mid=12002.5  (normal)
t+0 (ts=2900):  bid@12006(+4)  ask@12009(+7)   mid=12007.5   <-- agg_bid appears
t+1 (ts=3000):  bid@11996(-7)  ask@12010(+7)   mid=12003.0   <-- snapped back
```

The aggressive quote sits on the book for **exactly one tick** — a
visible, resting bot-3 quote. Next tick it's gone and the book returns
to the normal wall/inner structure.

### Hypothesized rule

> *Bot-3 on PEP occasionally places aggressive quotes one tick inside
> FV (bid at F+{1..4} or ask at F-{1..4}). These quotes rest unmatched
> for exactly one tick, after which they disappear and the book
> normalizes. A sell (buy) submitted against an aggressive bid (ask) at
> that price fills at a price structurally above (below) fair value.*

Equivalent succinct form: "PEP aggressive bot-3 quotes are free money
on the far side — hit them."

### Confidence

**HIGH** for PEP, **MEDIUM** for OSM.

- 490 agg_bid and 451 agg_ask events across 3×10k-tick training days.
  Consistent 160/day count (day −1: 160, day 0: 164, day 1: 166) —
  this is a structural bot behavior, not a one-off.
- Forward detrended-mid change at k=1 tick: mean = −5.30 (t=−64) for
  agg_bid, +5.82 (t=+95) for agg_ask. Huge effect, exactly consistent
  with the one-tick reversion mechanism (bid at +4 disappears, mid drops
  by roughly (4 − (−6))/2 ≈ 5).
- Persists at k=10 ticks with essentially no decay (−5.24 vs −5.30),
  meaning the effect is not a fleeting burst — it's a genuine price
  level shift.
- On OSM, same pattern but smaller: agg_bid k=1 → −1.26 (t=−18),
  agg_ask k=1 → +1.36 (t=+22). Effect is ~5× smaller but still huge
  relative to baseline (bl mean = +0.008).

### Falsification test

1. Run a simulated strategy that, on every tick with an aggressive PEP
   bid at price p, submits a sell order at p for `min(bid_volume, cap)`.
   Mirror for agg_ask (submit buy). Measure captured PnL on training
   data.
2. Verify that when we hit the aggressive quote, we get a fill at price
   p (not rejected), and the next-tick book is at the normal level so
   we can offset.
3. Prove that this isn't captured by iter23 currently.

### Why iter23 misses it (verified by reading code)

`_trade_pepper` (lines 428-484) has **no symmetric take-bid loop**:

- Take-ask branch: `for ap in sorted(d.sell_orders): if ap >= fv_int: break` — this captures agg_ask (ask < fv_int). ✓
- **No take-bid loop at all.** The "sell 8 at ba-1" recycle branch only sells at `max(ba-1, fv_int+1)` which is typically ~F+6, not hitting the F+4 aggressive bid.

So agg_bid on PEP is entirely uncaptured by iter23.

(On OSM, iter23 _does_ have a symmetric take-bid loop at lines 368-377,
so OSM agg_bid is captured — matching the small remaining OSM signal
coming from the `vol<=9 or real_edge>=2` gate being imperfect.)

### Exploitation idea

Add to `_trade_pepper` a take-bid loop analogous to `_trade_osmium`:

```python
for bp in sorted(d.buy_orders, reverse=True):
    if bp <= fv_int: break           # only cross bids ABOVE our FV
    vol = d.buy_orders[bp]
    fill = min(vol, LIMITS[product] + pos)   # capped by short side
    if fill > 0:
        orders.append(Order(product, bp, -fill))
        pos -= fill
```

Subtlety: iter23's PEP is in "fast accumulate" mode (pos < 70 → buying
aggressively). Hitting an aggressive bid when we're trying to _build_
a long position is counter-productive inventory-wise. The rule needs
to gate by pos:
- If `pos >= some_threshold` (say 50): take aggressive bids.
- If `pos < threshold`: pass (accumulation more important than $3 edge).

Another subtlety: PEP has +0.1 drift. An aggressive bid at F+4 rests
for 1 tick. During that tick, FV moves +0.1. So our sell at F+4 is vs
a tick-later FV of F+0.1. The edge is effectively +3.9, not +4. Minor.

### Expected uplift

Per 10k-tick training day:
- ~163 agg_bid events × typical qty 5 × edge +3 = ~$2,400/day.
- ~150 agg_ask events — mostly already taken by existing ask-cross
  logic; marginal capture $200-500/day.
- Gross: $2,500-3,000 per 10k-tick day.

Server-session ratio (1k ticks): ~$250-300/session.

At a baseline of $9,641/session, this is **~3% server-session uplift
or ~25-30% on a full 10k-tick training day equivalent**. The community
hint's "20% = $1,500-2,000" lands in-between these two scales.

Note: the 80% quote randomization means we see only ~130/day not 163
(expected value 163 × 0.8 = 130). Adjusted: ~$2,000/day or ~$200/session.
Still significant relative to the community's $1,500-2,000 claim when
aggregated over a 1M-tick final round.

---

## Candidate rule 2 — OSM aggressive bot-3 already mostly captured — LOW priority

### Observation

OSM has similar structure (~500 agg_bid, ~680 agg_ask per day), but
the per-event signal is only −1.26 / +1.36 mid ticks (much smaller
than PEP's ±5.3-5.8).

### Why the signal is smaller

OSM has `F=10001` constant. The "aggressive" threshold `bid >= 10001`
catches bids at offsets +0, +1, +2, +3, +4 — but many of these are
low-edge cases (a bid at 10001 has +0 edge if FV=10001.0, compared to
PEP's bid at 12006 with +4 edge against FV=12002.6).

### Status

iter23 already implements the symmetric take logic on OSM. The
remaining signal is noise/gate-tuning, not a missed rule.

### Confidence

**MEDIUM**. Effect is real (t=−18, +22), but small. Marginal tuning of
the `vol<=9 or real_edge>=2` gate might capture a few hundred $/day, but
this isn't the $1,500-2,000 alpha.

---

## Candidate rule 3 — PEP passive-ask bot-3 at offset +1..+5 — MEDIUM

### Observation

"pass_ask" events on PEP (ask at offset +1..+5, not inner) → forward
detrended-mid rises by +2.6 ticks at k=1 (t=+29).

Much smaller than agg_ask (+5.8), but still a real forward signal.

### Hypothesized rule

When a passive bot-3 ask at offset +1..+5 appears, the ask side is
"tighter than normal" for one tick. The next tick the ask returns to
its normal +7 offset, so mid rises.

### Exploitation idea

Similar to rule 1 but with smaller edge. Would buy at the tight ask
(offset +1..+5 below normal inner at +7) for ~+2 edge per unit.

### Confidence

MEDIUM. Signal is real but effect is smaller. Prioritize rule 1.

---

## Candidate rule 4 — OSM passive bot-3 on our side predicts drift — LOW

### Observation

OSM pass_bid (bid at offset −1..−5) predicts next-tick mid drops
−0.30 (t=−12). Similarly pass_ask predicts +0.34.

### Status

Small effect. iter23's OSM take logic fires on some of these already
(via `vol <= 9` trigger). Not the main alpha.

---

## Priority

1. **Rule 1 (PEP agg_bid take)** — HIGH confidence, HIGH uplift, not captured by iter23. **Validate first.**
2. Rule 3 (PEP pass_ask take) — medium follow-up.
3. Rule 2 — already captured, tuning only.
4. Rule 4 — tuning only.
