# tb1 scope analysis — what's captured vs what remains

## What tb1 does (the 2-line change)

In `_trade_osmium`:
```
bid_pj = min(bb + 1, int(dynamic_fv) - 1)   # was: fv - 1
ask_pj = max(ba - 1, int(dynamic_fv) + 1)   # was: fv + 1
```

`dynamic_fv = self._inner_mid(d)` (robust mid estimate between inner bots). Unchanged:
- Take-gate: `if ap >= fv (10001): break`
- MM outer edge layer at `fv ± 20`
- PEP logic
- Defensive widen on take_sig
- Sizing (`mi = 15`)

## Mechanism

When mid is near static FV=10001, tb1 behaves identically to iter23 (both anchor on ~10001). When mid drifts far (elevated ≥10005 or deflated ≤9998), tb1 moves its inner-layer passive quotes to track the actual mid:

- Elevated (mid=10007): iter23 bid at 10000 (mid-7, too wide to fill). tb1 bid at 10006 (mid-1, captures sell-taker flow).
- Deflated (mid=9993): iter23 ask at 10002 (mid+9). tb1 ask at 9994 (mid+1).

This captures **MM spread during far-from-FV regimes** that iter23 misses.

## Where tb1 gains (from 50K-ts-window backtest per day)

| day | top-3 gain windows | mid_avg | Δ tb1 vs iter23 |
|-----|-------------------|--------:|----------------:|
| 2-0 | [700K..750K] | 9990.5 (deflated) | **+$359** |
| 2-0 | [950K..1M]   | 10009.4 (elevated) | +$186 |
| 2-0 | [550K..600K] | 10007.7 (elevated) | +$171 |
| 2-1 | [650K..700K] | 9996.8 (normal-ish) | +$139 |
| 2-1 | [150K..200K] | 10007.3 (elevated) | +$109 |
| 2-1 | [950K..1M]   | 9994.1 (deflated) | +$114 |
| 2--1 | [800K..850K] | 9994.7 (deflated) | +$92 |
| 2--1 | [650K..700K] | 10007.7 (elevated) | +$79 |

**Pattern**: tb1 wins specifically when mid is >5 ticks away from 10001. At normal mid, Δ ≈ 0.

## Where tb1 does NOT help (iter23 already captures or both underperform)

1. **Big mean-reversion windows** where iter23 already dominates:
   - Day 0 [800K..850K]: iter23 +$2,394. tb1 +$15 marginal.
   - Day 0 [900K..950K]: iter23 +$2,086. tb1 +$18 marginal.
   The mean-reversion mechanism (iter23's symmetric MM around 10001) works well here.

2. **Sustained-adverse windows** where both strategies lose:
   - Day 1 [600K..650K]: iter23 −$461, tb1 −$398 (slightly better but still big loss).
   - Day 0 [800K..850K subset inside]: some ticks have iter23 negative.
   These are "losing regimes" where neither strategy has a good mechanism.

3. **Normal mid regimes** (|mid−10001|≤3): tb1 Δ≈0 by design.

## What's still on the table (hypothesis generation targets)

### A. OSM outer-edge layer is still static
`bid_edge = fv - 20 = 9981`, `ask_edge = fv + 20 = 10021` are anchored on static FV. When mid is elevated, ask_edge at 10021 = mid+14 is reasonable, but bid_edge at 9981 = mid-26 never fills. Similarly inverted when mid is deflated. Deep outer layer could be tuned to move with mid.

### B. Sizing is static (mi = 15)
tb1 captures spread at mid±1 but always with size 15. During sustained elevation, we could size UP to capture more fills per tick.

### C. Additional quote layer
tb1 posts at mid±1 (bid_pj) and fv±20 (bid_edge). Between these there's a GAP at mid±3 to mid±10 where we have no quotes. Buys/sells in that band bypass us.

### D. PEP has fv_int which IS dynamic already
PEP's `fv_int = round(self._pep_fv)` tracks drift. PEP MM uses `bid_price = min(bb+1, fv_int-1)`. This is structurally the same as tb1's OSM change. PEP is probably already optimized for its drift FV.

### E. Take-gate conditional on mid regime
Rule 2 was unconditional dynamic gate; falsified. But a tight conditional: relax take-gate ONLY when short and mid near normal (cover inventory). Or: relax ONLY when recent trade at elevated price confirms book is genuinely trading above 10001.

### F. Sustained-loss windows (day 1 [600K..650K])
iter23 loses $461 there. tb1 barely helps. Some specific event in that window hurts both. Worth investigating — might be a bot behavior that creates adverse fills.

## Candidates to test

Per task rules, each candidate needs:
- Specific numeric rule
- Orthogonality to tb1 and Rule 2
- Backtest >+$300 3-day with all days positive

I'll focus on A (dynamic outer edge), B (size boost during elevation), and C (additional middle layer) as the most tractable. D is a no-op (already done). E is Rule-2-adjacent and risky. F needs window-specific investigation.
