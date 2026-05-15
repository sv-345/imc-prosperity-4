# Step 4 — iter25 modification & backtest validation

## Modification

**File**: `exploration4/iter25_tb1.py` (copy of iter23 + 2-line change)

**Change**: in `_trade_osmium`, replace the STATIC fv anchor on quote
placement with DYNAMIC anchor (`dynamic_fv = _inner_mid(d)`, already
computed in iter23):

```diff
-    bid_pj = min(bb + 1, fv - 1)
-    ask_pj = max(ba - 1, fv + 1)
+    bid_pj = min(bb + 1, int(dynamic_fv) - 1)
+    ask_pj = max(ba - 1, int(dynamic_fv) + 1)
```

**What is unchanged**:
- Take-gate still uses static `fv = OSM_FV = 10001`: `if ap >= fv: break`.
  Rule 2 (session 1) falsified the dynamic TAKE gate — don't change it.
- MM outer-edge layer (bid_edge = fv-20, ask_edge = fv+20) still static.
- PEP logic entirely unchanged (`_trade_pepper` uses `fv_int` — different
  variable name, not touched by the sed).
- `vol <= 9 or real_edge >= 2` take condition unchanged.
- Defensive widen on take_sig unchanged.
- Fast-accumulate for PEP unchanged.

## Backtest result (prosperity3bt, 3 R2 training days, full-length)

```
day      trader             OSM       PEP     TOTAL
-------------------------------------------------------
2--1     iter23           19377     81932    101309
2--1     tb1              19376     81932    101308
2--1     Δ (tb1-23)          -1        +0        -1

2-0      iter23           18632     82313    100945
2-0      tb1              19720     82313    102033
2-0      Δ (tb1-23)       +1088        +0     +1088

2-1      iter23           17939     83331    101270
2-1      tb1              18431     83331    101762
2-1      Δ (tb1-23)        +492        +0      +492

3-day total Δ: +$1,579
```

## Validation gate check

| criterion | result |
|-----------|--------|
| 3-day total > +$100 | ✓ **+$1,579** (15.8× the gate) |
| All 3 days positive (or non-negative-within-noise) | ✓ day −1 = −$1 (essentially zero); days 0 & 1 strongly positive |
| All uplift from OSM (target was OSM miscalibration) | ✓ PEP Δ = $0 on every day |
| Uplift concentrated in hypothesized step-up-style periods | Not per-window verified, but day-level magnitudes (+$1,088 / +$492) are consistent with the Window 2-scale gap |

## Offset sweep robustness

Tested `int(dynamic_fv) - N` for N in {0,1,2,3,4,5,6}:

| offset | 3-day Δ | day−1 | day 0 | day 1 |
|-------:|--------:|------:|------:|------:|
| 0      | +$1,568 | −$15  | +$1,096 | +$487 |
| **1**  | **+$1,579** | **−$1** | **+$1,088** | **+$492** |
| 2      | +$1,578 | −$78  | +$1,142 | +$514 |
| 3      | +$1,596 | −$97  | +$1,126 | +$567 |
| 4      | +$1,547 | −$126 | +$1,087 | +$586 |
| 5      | +$1,475 | −$126 | +$1,019 | +$583 |
| 6      | +$1,488 | −$119 | +$1,041 | +$567 |

**Robust**: all offsets 0-6 produce +$1,475 to +$1,596 total uplift.
Offset 1 is the cleanest (day −1 essentially flat; 2 strongly positive days).
Offset 3 is nominal peak (+$1,596) but with slightly worse day −1.

## Why this worked where Rule 2 didn't

Rule 2 (session 1) changed the TAKE gate to dynamic — that let iter23 buy
asks ABOVE 10001 during elevated regimes (buying at stale-high prices).
Falsified.

iter25_tb1 changes only the QUOTE PLACEMENT anchor. The take gate stays
at static 10001 (so we still only take asks below 10001 — protecting
against adverse fills). What changes is where our passive MM quotes rest
on the book, which adapts to actual mid. This captures spread during
elevated regimes without taking the adverse-selection risk that Rule 2 took.

## Relation to the original step-up windows

Window 2 (ts 76K-83K) was on day 1. Baseline iter23 captured $547 OSM there
vs leaderboard's ~$1,000. Gap ~$450.

Day 1 full-run OSM uplift from iter25_tb1: **+$492**. The magnitude aligns
with the single-window gap, suggesting the mechanism is capturing that
hypothesized missed flow.

## Recommendation

**Mechanism identified and modification validates.** Ready for framework
review.

Suggested routing: the single-line quote-anchor change is surgical and
low-risk by code diff, but the +$1,579 training uplift is large relative
to prior interventions. Skeptic should review because:
- Rule 2 looked similarly promising and was falsified. This change is
  structurally different (quote placement, not take gate) — but careful
  Skeptic scrutiny is warranted.
- Backtest shows day-0 captures most of the uplift ($1,088) — single-day
  concentration should be flagged as potential sample-specific.
- Server uncertainty: backtest ≠ server. Need server sample(s) to confirm.

Per task rules, I am NOT routing directly to framework. User decides.
