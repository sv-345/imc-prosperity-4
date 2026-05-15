# Exploration 3 — deep microstructure findings

Second-pass investigation after the initial null_result. These are the
odd/notable things in the data, with backtest outcomes where relevant.

---

## Finding 1 — Deterministic taker schedule (HUGE, unexploited)

**Observation:** 50.6% of OSM taker quantity and 31.1% of PEP taker
quantity is scheduled at **deterministic timestamps** with identical
direction and qty across all 3 training days.

| product | unique trade-ts across 3 days | same on all 3 days (exact qty) | same on all 3 days (exact qty + direction) |
|---------|------------------------------:|-------------------------------:|-------------------------------------------:|
| OSM     | 818                            | 178 (22%)                      | **178 (22%) — all with matching direction** |
| PEP     | 540                            | 104 (19%)                      | 102 (19%)                                  |

Example deterministic events (same on days −1, 0, 1):

```
OSM  ts=15100  qtys=[2, 8]   directions=['BUY', 'BUY']
OSM  ts=34500  qty=8          direction='SELL'
PEP  ts=35700  qtys=[3, 7]   directions=['SELL', 'BUY']
PEP  ts=44700  qty=8          direction='BUY'
```

The trade **prices** differ by day (because the OSM mid / PEP drift
differ by day), but the **taker qty and direction are identical**. This
is strong evidence that the IMC simulator has a **seeded bot-taker
schedule** keyed on timestamp, with the price determined by the
current book state at that timestamp. The 80% quote randomization
drops roughly 20% of scheduled events per sample (explaining why the
"any 2 of 3" count is also large).

**Backtest outcome for several schedule-aware strategies:**

| variant | mechanism | 3-day Δ vs iter23 |
|---------|-----------|------------------:|
| schedule_widen (SCHED_WIDEN=4 from fv) | on scheduled tick, set ask_pj=fv+4 | **−$13,822** |
| schedule_widen (additive +2) | on scheduled tick, widen quote by +2 | **−$26,681** |
| schedule OSM-only | same, OSM only | −$24,669 |
| schedule PEP-only | same, PEP only | −$2,012 |
| schedule preempt defend (1-tick early) | schedule triggers defensive widen on t-1 | −$1,082 |

**Why none work:** the backtester uses tape-fixed trade prices. Our
resting limit orders only fill when a market_trade price CROSSES our
price. If we widen our ask from F+7 (inner-1) to F+9, and the
historical tape's taker trade was at F+9 (wall), we now tie with the
wall at F+9, and queue priority goes to the wall. We sell 0 instead
of iter23's normal 8-at-F+7. Net: large loss.

Conversely, narrowing our quote (posting at F+6 instead of F+7)
doesn't help — limit orders match at our resting price, so we'd sell
at a LOWER price. Also a loss.

iter23's quote placement (`ba-1` for sell, `bb+1` for buy) is already
capturing the inside-of-wall liquidity efficiently. The schedule info
is **descriptive, not prescriptive** for a MM trader.

**Not a validated alpha**, but a genuinely interesting bot-behavior
finding that might be exploitable by a strategy fundamentally different
from MM (e.g., a pure taker that hits the book just before scheduled
events, though that'd also face the same tape-fixed-price issue in
backtest).

## Finding 2 — Multi-trade bursts happen at the same ts across days

Specific timestamps have **multi-trade bursts** (2 trades in 1 tick).
These are highly deterministic:

- OSM ts=15100 has qty split (2, 8) on ALL 3 days (price differs: 10011 / 10010 / 10013)
- OSM ts=96900 (2,8), ts=139400 (6,5), ts=34500 (single 8) — all consistent
- PEP ts=35700 (3, 7) and ts=109800 (4, 3) — consistent

This further supports the seeded-schedule hypothesis. Multi-trade
bursts likely correspond to ONE scheduled taker event with qty > 10
that gets split across 2 book levels (e.g., qty 10 eats L1 vol 2 at
F+7, then L2 vol 8 at F+9).

## Finding 3 — Phantom fills on PEP (weak evidence of 80% resampling)

10 out of 996 (1.0%) PEP trades in training happen at prices NOT at
the visible L1 bid/ask — strictly between the two. This matches the
community's "cherry3003" observation (trade at 13013 when visible
bid1=13014). Evidence of the 80% quote-randomization mechanism.

## Finding 4 — Wall vol distribution isn't uniform

Docs claim OSM wall vol U(20,30), PEP wall vol U(15,25). Observed:

- OSM: 83% of wall vols in [20, 30], 17% in [2, 19] (long left tail)
- PEP: 46% in [20, 30], 54% in [15, 25] range is actually tighter

So the bot's effective wall vol range is wider than docs say. The
long left tail (vol 2-15) represents ~17% of ticks. These may be the
"walls after partial fill" — the taker hit 8 units, wall drops from
25 to 17.

**Backtest outcome:** not directly tested as a signal.

## Finding 5 — Wall-vol imbalance predicts next-tick mid direction (weak)

Published in session-3 null_result: `bid_wall_vol - ask_wall_vol`
predicts next-tick detrended mid monotonically, t up to 4. Mechanism
is asymmetric bot placement (when one side is deeper, the opposite
side is more likely to be taken). **Not exploitable via quote
placement (cand 1a/b/c all regress).**

## Finding 6 — L1 volume imbalance is a massive forward-mid signal (strongest signal in the data, still unexploited)

`bid_vol_L1 - ask_vol_L1` predicts next-tick detrended mid with t-stats
up to 25 (!) and magnitudes 1-3 ticks per event. Strongest forward
signal I've found.

Mechanism: thin-side L1 gets eaten first, next level becomes new L1 at
a wider price, mid walks.

**Backtest outcome:** cand 2 extends take-gate when imb >= 8. Result:
**−$3,048**. Fails because the move is mechanical; capturing it
requires crossing the NEW spread on unwind, which exceeds the signal
edge.

## Finding 7 — Trade direction Markov chain is near-independent

P(B|prev=B) ≈ P(B|prev=S) ≈ 0.50 on both products. No direction
autocorrelation. This contradicts R1's 0.85 ρ on PEP reported in
memory — R2 is different.

## Finding 8 — Trade size distribution NOT uniform on PEP

PEP supposed qty U(3,8). Observed size 8 is **3× rarer** than size 3:
- PEP BUY sizes: 3 → 99, 4 → 88, 5 → 74, 6 → 95, 7 → 108, 8 → 31
- PEP SELL sizes: 3 → 119, 4 → 93, 5 → 110, 6 → 83, 7 → 75, 8 → 11

Size 8 on SELL only 11 occurrences out of 491 — way under the expected
491/6 = 82 for uniform. Size 3 is over-represented.

Possibly the size distribution is U(3,7) + rare 8, or has a built-in
lower-bias.

**Not directly exploitable** but useful calibration data.

## Finding 9 — No cross-product schedule alignment

OSM and PEP scheduled ts don't overlap more than chance would predict.
Each product has independent seeding.

## Summary

| # | finding | exploitable? |
|---|---------|:-------------|
| 1 | Deterministic taker schedule (178 OSM ts, 102 PEP ts) | **No (via MM)** — tape-fixed prices defeat quote-placement tricks |
| 2 | Multi-trade bursts at consistent ts | Same as #1 |
| 3 | Phantom-fill events (80% resampling) | No |
| 4 | Wall vol has long left tail | No direct edge |
| 5 | Wall vol imbalance signal (t=4) | No (cand 1 regresses) |
| 6 | L1 vol imbalance signal (t=25) | No (cand 2 regresses) |
| 7 | Trade-direction near-independent | No (just background stat) |
| 8 | PEP sizes biased toward 3-7 vs 8 | No direct edge |
| 9 | OSM/PEP schedules independent | — |

**Net for the session 3 task**: no new validated alpha. But finding 1
(deterministic schedule) is a genuine bot-behavior insight that might
be exploitable by a strategy type we haven't considered (e.g., an
aggressive taker placed directly AT scheduled ticks, or a pairs
trade that uses schedule awareness orthogonally).

## Artifacts

- `deep_micro_scan.py` — trade timing, sizes, multi-trade, Markov,
  gaps, mid diffs, hidden prices, wall moves, vol outliers
- `multi_trade_determinism.py` — cross-day match count for trade ts
- `deterministic_schedule.py` — direction+qty determinism
- `extract_schedule.py` — writes `osm_schedule.py` + `pep_schedule.py`
- `osm_schedule.py` — 178-entry deterministic schedule
- `pep_schedule.py` — 102-entry deterministic schedule
- `iter_candidate_schedule.py` — schedule-widen variant (regresses)
- `iter_candidate_sched_preempt.py` — schedule-preempt variant
  (regresses)
