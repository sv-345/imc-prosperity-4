# Round 1 — Actionable Recommendations

Ranked by **realistic $ impact ÷ implementation complexity**. $ figures are from `counterfactuals.md`, discounted for hindsight bias (typically 30–50 % of raw hindsight PnL translates to submission gains).

## TL;DR

v82_hardened booked 101,200 against a hindsight ceiling in the low-to-mid 100k range. Most identified leaks are small. The one clearly wrong behavior (aggressive OSM crosses with weak signal) is worth ~$1.5 k in future round reruns; everything else is ≤$300 or net-negative. **Spend post-mortem effort building tooling for Round 2+ rather than micro-optimizing v82.**

---

## 1. Tighten the OSM aggressive-take condition  ⭐ primary rec

**Addresses.** Leak 3 (negative-edge crosses with weak markout) — CF3.

**$ impact.** Hindsight **+3,538**; realistic **+1,000 to +2,100** (~1 – 2 % of R1 pnl).

**Change.** In `_trade_osmium` (`273632.py:321-342`), the current take condition is:

```python
if vol <= 9 or real_edge >= 2:
    fill = ...
```

This fires on 251 fills; 140 of them had markout+50 ≤ +5 (marginal-to-losing). Tighter proposal:

```python
if (vol <= 4 and real_edge >= 1) or real_edge >= 3:
    fill = ...
```

Intuition: small bot (`vol ≤ 4`) still triggers crosses but requires *some* edge; larger bots require stronger edge. Removes the "free take on tiny ask" branch.

**Complexity.** 2-line diff. ~15 min implementation + validation.

**Local validation.**
1. Run `mc/server_book_replay.py::run_server_session` on training days `-2`, `-1`, `0` with v82-hardened baseline.
2. Apply the patch, rerun.
3. Compare per-day delta. Need **all three days** showing positive delta to ship (memory: "single-day delta can be misleading, MC v2 underpredicts by ~18 %").

**Real-time signal.** `vol`, `real_edge`, `ap` — all in `order_depth`. Deterministic, no peeking.

**Hindsight bias flag.** The optimal thresholds (`4`, `3`, `1`) are fit on this one day. Cross-validate on day `-1` and `-2`. If thresholds need to differ by day, don't tune — use the most conservative values from any training day.

---

## 2. PEP fast-ramp via initial spread crossing

**Addresses.** Leak 1 (PEP saturation ramp — 202 ticks to reach +80).

**$ impact.** Hindsight **+288**; realistic **+150 to +300**.

**Change.** In `_trade_pepper` (`273632.py:394-413`), add an early-saturation branch:

```python
# Fast ramp: in first 20 ticks, cross up to 8/tick to saturate long.
if pos < 80 and tick_index < 20:
    ba_price = min(d.sell_orders) if d.sell_orders else None
    if ba_price is not None and ba_price <= fv_int + 8:
        fill = min(-d.sell_orders[ba_price], 8, LIMITS[product] - pos)
        if fill > 0:
            orders.append(Order(product, ba_price, fill))
            pos += fill
```

**Complexity.** ~8 LOC. Trivial.

**Local validation.** Same replay harness. Delta should be small (<+500) per day, but consistently positive.

**Real-time.** `tick_index` is `state.timestamp // 100`. Fully online.

**Hindsight bias flag.** Low. The PEP drift (+0.1/tick) is already memorized from the problem statement; this just exploits it faster.

---

## 3. Instrument fills with markout logging for Round 2+

**Addresses.** Meta — makes future post-mortems 10× faster.

**$ impact.** Indirect (shortens next post-mortem cycle). Not for R1 gain.

**Change.** Add per-fill diagnostic output: when a fill lands in `own_trades`, log `(ts, side, price, mid, vol_taken, book_imbalance)` so the ledger can be built without re-parsing 11 MB of `lambdaLog`.

**Complexity.** ~20 LOC in a helper. Include it in the next submission baseline.

**Local validation.** Run any submission locally; verify CSV output parses cleanly.

---

## Anti-recommendation: do NOT add an OSM fv±12 layer

**Leak it addressed.** Leak 2 (edge=20 misses the 11–15 distance band).

**Counterfactual.** CF1 shows **−472** net. The 11–15 band is mostly already caught by our existing inside quote; adding a new layer just displaces our profitable edge=20 snipes.

**Verdict.** Skip. This matches the memory entry "OSM edge=12-20 plateau (min=1071 tie)" — the edge parameter doesn't have a sharp optimum.

---

## Lower-impact items (document, don't ship)

| item | $ | reason not to act |
|---|---:|---|
| PEP recycling threshold (only sell when edge ≥ 8) | −500 to −800 net | Recycling IS positive-ev; tightening reduces revenue. |
| Bot-bot queue-priority loss | +150 (at 50 % discount) | Low confidence, simulator routing unknown. |
| End-of-session inventory trim | +100 to +500 | Path-dependent; introduces closing-price risk. |
| OSM inventory-aware skew (more buy when short, more sell when long) | 0 estimated | Already handled by `buy_cap`/`sell_cap` logic. |

---

## Key insights for Round 2 planning

1. **Drift capture dominates MM revenue on PEP.** 76.5 k of 82.9 k PEP pnl was pure drift × inventory. Any future product with a known deterministic drift should be traded as "accumulate to limit immediately, recycle marginal units for MM extra."

2. **Position-limit cap is the dominant constraint on directional products.** PEP's 80-unit cap kept us from earning the extra 120 k a +200 cap would have yielded. Not fixable — but worth understanding that future rounds' caps are the #1 PnL lever.

3. **"Adverse selection" is a bad framing for deterministically drifting products.** Every PEP sell looks adverse on a 200-tick horizon; every PEP buy looks brilliant. Use markout-over-many-fills or realized-trip PnL, not per-fill adverse flags, for these products.

4. **MM strategy on OSM is near-ceiling.** Mid barely moved; 18 k from 20 ticks of spread-capture is in the right magnitude. Tightening the take condition (rec #1) is the only clear lever identified.

5. **"Obvious" strategy changes (tighter edge, better inner quote, add layer) don't help in hindsight.** The existing `fv±20 + inside` structure is well-tuned. Next round, start from structural questions (what's the edge source?) not parameter tuning.

6. **Hindsight ceiling for this specific day is ~105-110 k.** We left ~4-9 k on the table relative to a perfectly-tuned version of v82, of which ~1-2.5 k is realistically recoverable in future runs.
