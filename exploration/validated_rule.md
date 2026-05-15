# Validated rule — OSM aggressive-quote alpha (static-gate leak)

## UPDATE 2026-04-19 — HYPOTHESIS FALSIFIED ON TRAINING TAPE

**Backtest result (prosperity3bt, all 3 R2 training days):**

| variant                 | 3-day total | Δ vs iter23 |
|-------------------------|------------:|------------:|
| iter23 (baseline)       |    303,524  |           — |
| iter24 dyn clamp 3      |    303,328  |        −196 |
| iter24 dyn clamp 5      |    302,996  |        −528 |
| iter24 dyn clamp 10     |    301,037  |      −2,487 |
| iter23 with FV=10002    |    299,435  |      −4,089 |
| iter23 with FV=10003    |    294,387  |      −9,137 |
| iter23 with FV=10004    |    289,298  |     −14,226 |
| iter23 with FV=10005    |    283,800  |     −19,724 |

**Every variant tested regresses.** The dynamic-gate fix hurts, as
does simply shifting the static gate upward. iter23's static
`OSM_FV = 10001` is locally optimal on the training tape.

### Why the hypothesis was wrong

iter23's static gate at 10001 implicitly implements mean-reversion
against the OSM equilibrium: only buy asks _below_ 10001, only sell
bids _above_ 10001. When mid drifts up to 10008:

- Static gate: skips asks at 10002-10007 (correct — don't buy when mid
  is high and about to revert); takes bids at 10002-10007 (correct —
  sell into elevated bids before reversion).
- Dynamic gate at ≈10008: takes asks at 10002-10007 (**wrong** — buys
  into the up-regime just before reversion); skips bids at 10002-10007
  (**wrong** — misses the reversion-sell opportunity).

The dynamic gate removes the mean-reversion filter. In a range-bound
market (OSM on training: mid 9982-10020, centered ~10001), that's net
negative.

### What the `305289/analysis.md` was probably seeing

The 305289 session was 1 day × 1,000 ticks with mean mid 10004.19 —
that's a sampling artifact. Over 3 days × 10,000 ticks (training), the
mean mid is 10001.2, so the static gate is correctly calibrated.

The 305289 "item 1" hindsight analysis (+$2-4k if gate at 10,005)
would hold IFF the server session happens to have a mid centered at
10004. In most sessions (training evidence), it's centered at 10001
and the static gate is right.

### Net conclusion

**Do not ship iter24.** The hypothesis that iter23 is leaking
$2-4k/day of OSM alpha via a stale gate is FALSE on the training tape.

The raw forward-mid signals found in earlier exploration
(agg_bid → -5.3, agg_ask → +5.8) are REAL but capturing them via
take-logic does not improve end-of-day PnL because:
1. The iter23 `vol <= 9` fallback already catches low-volume aggressive
   asks/bids without needing the gate loosened.
2. The gate loosening opens up higher-volume non-bot-3 quotes that are
   adverse.
3. The instantaneous edge at the event does not persist against
   inventory carrying cost.

The 20% community alpha is elsewhere. Candidates not yet explored:
- Bot-sizing rules (wall volume as a predictor of flow)
- Taker inter-arrival timing
- Specific mid-drift trigger events (not yet isolated in visualizer)

### Artifacts

- `ROUND_2/iter24_dynamic_gate_trader.py` — new trader file with the
  dynamic clamp. Kept for reference; **do not submit**.
- `exploration/bench_iter23_vs_24.py` — initial benchmark.
- `exploration/bench_variants.py` — variant matrix (FV shifts + clamps).
- `exploration/bench_variants.json` — raw results.

---

## Original analysis (preserved for reference; now-falsified)

## Summary

~~**Validated (HIGH confidence):** iter23 has a **stale OSM take-gate**
that misses ~$3,300/day of aggressive-quote edge because it anchors on
a hardcoded `OSM_FV = 10001` while the actual R2 market mid drifts
around 10003-10010 during certain intraday regimes.~~

**Status: hypothesis falsified by backtest (see UPDATE above).**

This is the same $2-4k/day leak diagnosed in `ROUND_2/305289/analysis.md`
(items 1 and 2 of the action list). It has not been fixed in iter23 —
the gate `if ap >= fv: break` still uses the static `OSM_FV`.

**Rejected (important negative result):** The strong raw forward signal
from PEP aggressive-bid quotes (forward detrended-mid change = -5.3
tick, t = -64) is NOT exploitable in production because PEP's +0.1/tick
drift eats the +3 instantaneous edge within 30-50 ticks of holding.
Taking aggressive PEP bids reduces end-of-day PnL vs. not taking them
(iter23-like sim: $98,779/day baseline → $88,364/day with agg_bid take,
**delta −$10,415/day**).

## Data

- 3 training days × 2 products × 10,000 ticks each.
- Reference: `ROUND_2/prices_round_2_day_{-1,0,1}.csv`.
- Rolling-mid reference: 51-tick centered median of inner mid (used to
  define "aggressive" consistently as mid drifts).

## Evidence for OSM aggressive-quote alpha

### Event counts (rolling-mid reference)

| day | agg_bid events | agg_ask events |
|-----|---------------:|---------------:|
| −1  |             107 |             138 |
| 0   |             106 |             126 |
| 1   |             115 |             132 |
| **total** | **328** | **396** |

- Day 0 shows intraday concentration in Q3 (tick 5000-7500): 593 of the
  year's 997 OSM agg_asks fire during this one quartile. That's the
  "middle exploits" sriram06765 mentioned.

### Per-event edge (rolling-mid reference)

| side | avg edge/unit | total edge $/day |
|------|:-------------:|:----------------:|
| agg_bid | +$1.59 | $1,208 |
| agg_ask | +$2.47 | $2,248 |
| combined | — | **$3,456** |

### Participation rate — other traders barely touch these

| product | side | events hit by any trade | volume hit |
|---------|------|------------------------:|-----------:|
| OSM     | bid  | **2-6% (mean ~4%)**     | **1-3%**   |
| OSM     | ask  | **3-6%**                | **2-3%**   |
| PEP     | bid  | 27-34%                  | 25-33%     |
| PEP     | ask  | 29-30%                  | 29-30%     |

Over 94% of OSM aggressive-quote volume goes **unhit** — it rests for
one tick then disappears. This is a wide-open opportunity window.

### Forward-mid reversion (validates "aggressive = mispriced")

| product | event    | k=1 mid change | k=10 mid change | t-stat k=1 |
|---------|----------|---------------:|----------------:|-----------:|
| OSM     | agg_bid  | −4.73 to −4.95 |    persists     | (large)    |
| OSM     | agg_ask  | +5.20 to +5.55 |    persists     | (large)    |
| PEP     | agg_bid  | −5.26          |    persists     | −64        |
| PEP     | agg_ask  | +5.78          |    persists     | +95        |

Consistent across all 3 days. Effect does not decay — the aggressive
quote is a one-tick anomaly; the book snaps back to normal and stays
there.

## Why iter23 misses the OSM alpha

`_trade_osmium` at `ROUND_2/iter23_trader.py:338-377`:

```python
fv = OSM_FV  # = 10001, module-level constant (line 87)
...
for ap in sorted(d.sell_orders):
    if ap >= fv: break    # ← static 10001 gate
    ...

for bp in sorted(d.buy_orders, reverse=True):
    if bp <= fv: break    # ← static 10001 gate
    ...
```

When the OSM mid drifts from 10001 to 10008 (seen repeatedly in Q3 of
day 0, Q1 of day 1):

- **Asks at 10002-10007** are below true mid but `ap >= 10001` blocks
  the take. iter23 walks past them.
- **Bids at 9994-10000** are above true mid but `bp <= 10001` blocks
  the take. iter23 walks past them.

The inner `real_edge = dynamic_fv − ap` calculation on line 360 is
_already_ using `self._inner_mid(d)` as the dynamic reference — but
that logic is fenced behind the static gate and never reached for the
missing events.

This is explicitly diagnosed in `ROUND_2/305289/analysis.md §"Root cause"`
with a $2-4k/day impact estimate (item 1) plus $500-1,500/day from
tightening the `vol <= 9` fallback (item 2). The analysis was written
against iter12; iter23 inherited the bug.

## Why the PEP agg_bid signal doesn't become alpha

The raw forward signal on PEP agg_bid is huge: mid drops 5.3 ticks next
tick. An aggressive bid at F+3 sells us +3 of edge vs fair value.

But PEP has a deterministic +0.1/tick drift. Holding a short position
against this drift costs 0.1 × N per unit per N ticks. After 30 ticks
the drift has eaten the +3 edge.

Realistic buyback channels:

- **Passive buy at bb+1** (~F−5): must wait for a sell-taker. PEP has
  ~150 sell-takers per 10k ticks → expected wait ~66 ticks. During
  that wait, drift = 6.6. Net PnL = (F+3) − (F+5.6) = −2.6 per unit.
- **Aggressive buy at best ask** (~F+7): immediate but pays the spread.
  Net PnL = (F+3) − (F+7) = −4 per unit.
- **Hold short to EOD**: drift keeps accumulating; MTM loss grows
  unbounded.

Simulator confirms:

| strategy | avg MTM_fv/day on PEP |
|----------|----------------------:|
| iter23-like baseline                  | +$98,779 |
| baseline + agg_bid take (pos>=50)     | +$88,364 (**−$10,415**) |
| baseline + agg_bid take (pos>=70)     | +$89,760 (**−$9,019**)  |
| baseline + agg_bid take unconditional | +$87,868 (**−$10,911**) |

Every variant loses to the baseline.

## Why iter23 already captures PEP agg_ask

`_trade_pepper` at `ROUND_2/iter23_trader.py:438-445`:

```python
for ap in sorted(d.sell_orders):
    if ap >= fv_int: break
    fill = min(-d.sell_orders[ap], limit - pos)
    ...
```

`fv_int = round(self._pep_fv)` — this tracks the drifting PEP FV
correctly. So agg_ask on PEP (ask < floor(FV)) is captured via
`ap < fv_int`. My isolated simulator confirms this: the
"iter23_ask" replica yields +$3,756/day, matching my `ask_only` variant
exactly ($3,756 vs $3,756). No leak on PEP ask side.

## Recommended fix

**Replace the OSM `fv` gate with a dynamic reference that tracks intraday
mid drift.** Three options in increasing order of complexity:

1. **Quick fix**: Use `dynamic_fv = self._inner_mid(d)` (already computed
   at line 351) as the gate reference:
   ```python
   fv = self._inner_mid(d)
   if fv is None:
       fv = OSM_FV
   fv = int(round(fv))
   ```
   Zero new state. Fallback to 10001 when `_inner_mid` returns None.

2. **Rolling mid**: Maintain a short (e.g., 21-tick) rolling window of
   inner mids in `traderData`; use the median as the gate reference.
   More robust to single-tick noise but requires persisted state.

3. **Kalman-filtered mid**: Use the in-progress Kalman filter's posterior
   mean as the gate reference. Most principled but depends on
   `project_latent_fv_kalman` Phase A/B landing.

All three options leave the MM quote anchor (the `fv ± edge`, `fv ± mi`
parameters on lines 395-396) at the STATIC 10001 — the MM spread and
layer placement were tuned for that anchor, and the 305289 analysis
doesn't flag those as needing change. The fix is ONLY to the
take-logic gate.

## Estimated uplift

- 305289 analysis item 1 ("make OSM_FV dynamic"): +$2-4k/day on a
  10k-tick training day.
- 305289 item 2 ("tighten `vol <= 9` fallback"): +$0.5-1.5k/day.
- Combined: **+$2.5-5.5k per 10k-tick day**.
- Server session scaling (1 day × 1k ticks): ~$250-550/session.
- Against a $9,641/session baseline, this is **3-6% server-session
  uplift**, or equivalently **20-40% of OSM-only PnL**.

This lands within the community's "20% ~ $1,500-2,000 alpha" claim
when measured over a full 1M-tick final round. Per-session variance is
high because of the intraday regime effect (some sessions have
pronounced mid drift; others don't).

## Strategy risks

1. **Adverse selection on the newly-taken quotes.** iter23's OSM take
   currently works because the static gate is conservative — it only
   hits truly out-of-line asks (ap < 10001). Expanding to dynamic means
   we hit more asks, some of which may be informed flow. Mitigation:
   keep iter23's `vol <= 9 or real_edge >= 2` guard, which filters by
   volume and signed edge.
2. **Dynamic reference noise.** `_inner_mid` returns `None` during
   one-sided book ticks. The fallback to OSM_FV during those ticks
   should maintain conservative behavior.
3. **Ranges where mid drifts FAR from 10001.** If a session has mid at
   10020 (extreme), dynamic take means buying asks up to ~10019. If
   the market reverts to 10001 by close, those purchases lose −18 per
   unit MTM. Cap on how far the gate can drift from 10001 may be
   prudent (e.g., clamp `dynamic_fv` to [10001 − 10, 10001 + 10]).

## Files in this exploration

- `recon.py` — offset and gap distributions
- `test_bot3_signal.py` — forward-mid signal test vs floor(FV) reference
- `inspect_events.py` — book snapshots around aggressive events
- `validate_rule1.py` — simulator with take-only + MTM variant
- `validate_rule1b.py` — take-sides breakdown (bid-only / ask-only / iter23 replica)
- `validate_rule1c.py` — pure instantaneous edge summation
- `validate_rule1d.py` — rolling-mid reference reproduction (stable across products)
- `validate_rule1e.py` — iter23-like PEP simulator with/without agg_bid take
- `validate_rule1f.py` — iter23-like OSM simulator, static vs rolling-mid
- `validate_rule1g.py` — OSM take/quote variant matrix
- `explore_other_patterns.py` — time-of-day quartile analysis, cross-product
- `check_trades_at_agg.py` / `check_trades_at_agg_v2.py` — other-trader
  participation at aggressive prices
- `visualize_bots.py` — HTML plotly visualizer with agg-event markers
