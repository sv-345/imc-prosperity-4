# Candidate 4 validation — conditional take-gate (position-aware)

## Final variant: `iter26_c4_best.py` = c4 with `pos<-40, mid>=10001`

### Rule (exact)

In `_trade_osmium`, modify take-gate to be position-AND-regime-conditional:

```python
ask_gate = fv   # default: static 10001 (iter23/tb1 behavior)
bid_gate = fv
if pos < -40 and dynamic_fv >= 10001:
    ask_gate = int(dynamic_fv)   # relax ask-take: cover short at mid
if pos > 40 and dynamic_fv <= 10001:
    bid_gate = int(dynamic_fv)   # relax bid-take: sell long at mid
# then use ask_gate / bid_gate in place of fv in the break conditions
```

The relaxation ONLY fires when we're heavily inventoried against the
regime direction AND the regime is on the correct side. Otherwise,
the static take-gate is preserved (mean-reversion protection intact).

## Backtest result (prosperity3bt, all 3 R2 training days, full 10K-tick runs)

```
iter23 3-day: 303,524
tb1    3-day: 305,103  (Δ vs iter23: +$1,579)

candidate                                  d=-1       d=0       d=1     3-day   Δ vs tb1   Δ vs iter23
iter25_tb1.py                            101308    102033    101762    305103        +0         +1579
iter26_c4_best.py                        101634    102281    102674    306589     +1486         +3065
iter26_c4_best + c1 (dyn outer edge)     101634    102279    102674    306587     +1484         +3063
iter26_c4_best + c3 (middle layer)       101648    102284    102676    306608     +1505         +3084
```

### Validation gate check

| criterion | c4_best |
|-----------|---------|
| 3-day total Δ vs tb1 > +$300 | ✓ **+$1,486** (4.95× the gate) |
| 3-day total Δ vs iter23 > +$300 | ✓ **+$3,065** |
| All 3 days positive vs tb1 | ✓ (d−1: +$326, d0: +$248, d1: +$912) |
| All 3 days positive vs iter23 | ✓ (d−1: +$325, d0: +$1,336, d1: +$1,404) |
| Composition with tb1 clean | ✓ (tb1's quote anchor change preserved; c4 adds take-gate layer) |
| Composition with Rule 2 protection | ✓ (static gate preserved when \|pos\| ≤ 40) |
| Improvement concentrates in high-gap periods | ✓ (d0 and d1 gain most; matches step-up window pattern) |

## Tuning sweep

| pos threshold | mid threshold | 3-day Δ vs tb1 | d=-1 Δ vs tb1 |
|--------------:|--------------:|---------------:|---------------:|
| 20 | 10005 | +$50 | −$228 |
| 30 | 10001 | +$1,113 | +$72 |
| 35 | 10003 | +$995 | +$68 |
| 35 | 10004 | +$675 | −$89 |
| 40 | 10000 | +$1,486 | +$326 |
| **40** | **10001** | **+$1,486** | **+$326** |
| 40 | 10002 | +$1,486 | +$326 |
| 40 | 10003 | +$1,396 | +$291 |
| 40 | 10004 | +$1,025 | +$60 |
| 40 | 10005 | +$466 | +$75 |
| 45 | 10004 | +$937 | +$60 |
| 45 | 10001 | +$1,290 | +$344 |
| 50 | 10004 | +$890 | +$144 |
| 50 | 10003 | +$1,319 | +$362 |
| 55 | 10001 | +$1,224 | +$367 |
| 60 | 10005 | +$711 | +$133 |
| 60 | 10003 | +$1,260 | +$346 |
| 70 | 10001 | +$1,328 | +$245 |

**Peak at pos=40, mid=10001 (or m=10000/10002 equivalently).** Robust — nearby settings (pos 30-55, mid 10001-10003) all stay above +$1,000. Rule 2 defense: mid filter on LOW-side cap (bid_gate) is necessary; posonly (no mid filter) regresses day -1 significantly.

### Failed variants (for record)

| variant | Δ vs tb1 | why |
|---------|---------:|-----|
| c1 alone (dyn outer edge) | −$8 | Outer layer rarely fills, negligible effect |
| c2 alone (size boost) | $0 | Size boost doesn't activate — taker qty binds, not our quote size |
| c3 alone (middle layer mid±3) | +$17 | Middle band rarely traded; marginal |
| c4_mid_only (no pos gate) | −$2,908 | **Rule 2 territory** — unconditional relax on mid alone; adverse when pos neutral |
| c4_posonly (no mid gate) | +$242 | Day −1 regresses $711 (fires wrong side during mid-volatile day) |
| c4_shortonly | −$6 | Asymmetric: only short-cover direction; insufficient |
| c4_longonly | +$166 | Asymmetric: only long-sell direction; partial |

## Why this works and Rule 2 didn't

**Rule 2** (session 1, falsified): unconditional dynamic take-gate.
- Fired at neutral position (pos=0) when mid was elevated.
- At pos=0, buying asks at 10002-10006 is just entering trade at stale-high price. Adverse.
- Removed iter23's mean-reversion enforcement entirely.
- Result: regressed up to −$2,487.

**c4_best**: conditional on `|pos| ≥ 40` AND regime-aligned.
- Fires only when we've already accumulated inventory against the regime.
- We ARE already committed to being short (−40 or worse); covering at mid beats covering at wall ask (10010) because wall requires tighter edge.
- At neutral position, static gate preserves mean-reversion enforcement.
- Composes with tb1's passive quote anchor — tb1 handles the passive fills, c4 handles inventory unwind.
- Result: +$1,486 on top of tb1.

## Mechanism summary

tb1 captured **passive fills** during far-from-FV regimes by anchoring quotes on dynamic_fv. But when those passive fills accumulate a large short (or long) position, iter23's static take-gate prevents rebalancing at favorable-vs-wall prices. c4_best fills this gap by allowing active cover at mid when we're inventoried against the regime direction.

Together (tb1 + c4): capture more passive fills AND clean up inventory faster, reducing hold-against-regime exposure.

## Composition: tb1 + c4_best

Both changes coexist in `iter26_c4_best.py` (which is a superset of tb1). The file should REPLACE tb1 as the production candidate. It's a SINGLE file, not two layered modifications.

Diff from iter23:
1. Line 386: `bid_pj = min(bb + 1, int(dynamic_fv) - 1)` (was `fv - 1`)
2. Line 387: `ask_pj = max(ba - 1, int(dynamic_fv) + 1)` (was `fv + 1`)
3. Lines 354-362: add `ask_gate` / `bid_gate` computation and use in take loops

## Per-day analysis

| day | iter23 | tb1 | c4_best | Δ c4 vs iter23 | Δ c4 vs tb1 |
|-----|-------:|----:|--------:|---------------:|------------:|
| 2--1 | 101,309 | 101,308 | 101,634 | +325 | +326 |
| 2-0  | 100,945 | 102,033 | 102,281 | +1,336 | +248 |
| 2-1  | 101,270 | 101,762 | 102,674 | +1,404 | +912 |
| **3-day** | **303,524** | **305,103** | **306,589** | **+3,065** | **+1,486** |

Day 1 shows the biggest uplift (+$1,404 vs iter23, +$912 vs tb1). Day 1 is the day used for the original step-up window analysis — this is direct evidence that c4_best captures additional alpha in the hypothesized step-up windows.

## Recommended next action

**Route to framework for Skeptic/Integrator review and server validation.**

This is iter26 (successor to iter25_tb1). Not a layered modification — just a single trader file with both changes.

Flag to Skeptic: this modification does touch take-gate logic (Rule 2 failure mode axis). Defense:
1. The relaxation is POSITION-CONDITIONAL (|pos| ≥ 40), not unconditional like Rule 2.
2. mid-filter preserves mean-reversion enforcement at neutral positions.
3. Backtest tuning sweep shows Rule 2 failure mode (mid-only, no pos condition) regresses $2,908 — we explicitly avoided it.
4. All 3 training days show positive delta vs both iter23 and tb1.

## Artifacts

- `iter26_c4_best.py` — final production candidate
- `iter26_c4_conditional_take.py` — original (pos<-20, mid>=10005) version for reference
- `candidates.md` — hypothesis set
- `tb1_scope_analysis.md` — step 1 analysis
