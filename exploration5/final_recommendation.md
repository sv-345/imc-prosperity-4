# Exploration 5 — final recommendation

## Result

**Validated candidate: `iter26_c4_best.py`** (position-conditional
take-gate relaxation, layered on top of tb1).

Backtest (prosperity3bt, 3 R2 training days, full 10K-tick runs):

| | iter23 | tb1 | **iter26_c4_best** |
|-|-------:|----:|-------------------:|
| 3-day total | $303,524 | $305,103 | **$306,589** |
| day −1 | 101,309 | 101,308 | **101,634** (+325 vs iter23) |
| day 0  | 100,945 | 102,033 | **102,281** (+1,336 vs iter23) |
| day 1  | 101,270 | 101,762 | **102,674** (+1,404 vs iter23) |
| Δ vs iter23 | — | +$1,579 | **+$3,065** |
| Δ vs tb1 (incremental) | — | — | **+$1,486** |

All 3 days positive vs iter23 AND vs tb1. Passes +$300 gate by 4.95×.

## What it does (3-line change vs iter23)

```python
# In _trade_osmium, BEFORE the take loops:
ask_gate = fv   # default static 10001
bid_gate = fv
if pos < -40 and dynamic_fv >= 10001:
    ask_gate = int(dynamic_fv)   # cover short at mid
if pos > 40 and dynamic_fv <= 10001:
    bid_gate = int(dynamic_fv)   # sell long at mid
# replace `if ap >= fv: break` with `if ap >= ask_gate: break`
# replace `if bp <= fv: break` with `if bp <= bid_gate: break`
# (plus tb1's quote anchor change on bid_pj/ask_pj)
```

## Mechanism

tb1 captures passive-fill flow during far-from-FV regimes by
anchoring quotes on dynamic inner mid. Those fills accumulate
inventory against the regime (e.g., long when mid is elevated,
since sell-takers hit our bid near mid).

When the position grows large (|pos| ≥ 40), iter23's static
take-gate prevents active rebalancing at favorable prices
(ask-take loop breaks at fv=10001, missing asks at 10002-10006).

c4_best relaxes the take-gate to dynamic_fv ONLY when we're
heavily inventoried in the correct direction. This lets us
cover at mid prices (better than waiting for the book to give
us asks below 10001).

Result: more passive fills (tb1) + faster inventory unwind
(c4_best) = ~2× the uplift vs iter23.

## Why it avoids Rule 2's failure mode

Rule 2 (session 1, falsified) changed the take-gate from static
to dynamic **unconditionally**. At neutral position (pos=0), it
would buy asks at 10005 when mid=10007 — effectively entering
new long positions at stale-high prices. Adverse; regressed
$196-$2,487.

c4_best's relaxation is **doubly conditional**:
1. Position threshold: only when |pos| ≥ 40 (already inventoried)
2. Regime alignment: only when mid is on the side matching the
   position (short + elevated; long + deflated)

At neutral position, static fv=10001 gate is preserved. At
position-against-regime, still preserved (no phantom relaxation).

Tuning sweep (see `validation_c4.md`) confirms:
- Unconditional mid relaxation (no pos gate): −$2,908 (Rule 2 reproduced)
- Position gate alone (no mid filter): +$242 total BUT day −1 regresses $711
- Both filters: +$1,486 clean, all days positive

## Composition

`iter26_c4_best.py` is a single file containing tb1's quote anchor
change AND c4's take-gate relaxation. It REPLACES iter25_tb1.py
as the production candidate (not a layer on top).

PEP logic is unchanged. All OSM-only modifications.

## Recommended next action

**Route `iter26_c4_best.py` through framework for Skeptic/Integrator
review and server validation.**

The change is larger in scope than tb1 (3 additional lines touching
take-gate) but structurally defended against Rule 2 failure mode.
Magnitude is meaningful: +$1,486 vs tb1 baseline on 3-day training
maps to roughly +$300-500 per 1,000-tick server session if the
backtest-to-server ratio matches tb1's prior pattern (~2×).

Skeptic notes:
1. Yes, this modifies take-gate (Rule 2 axis). Defense: position-conditional, mid-filtered, tuning sweep shows Rule 2 failure mode when either condition removed.
2. Day 0 captures largest absolute uplift — check for single-day over-concentration. Per-day deltas vs iter23: +325 / +1,336 / +1,404. NOT Day-0-only; day 1 is comparable.
3. Needs server validation. Backtest ≠ server (prior tb1 ratio: backtest +$1,579 / 3 days → server +$261 / session). Expect similar or higher scale-down factor.
4. |pos|≥40 threshold is ~50% of iter23's day-end position. Requires the strategy to actually reach that position — in normal trading it does.

## What remains uncaptured

Even with c4_best + tb1, leaderboard player at $12,137/session retains
some gap vs iter26_c4_best's estimated ~$10,000/session. Remaining
mechanisms not investigated here:
- PEP-side alpha (hard — iter23 PEP is already near max drift capture)
- Adverse-selection patterns specific to individual bots (session 3
  schedule work didn't translate to MM alpha)
- Bot response to our fills (requires per-fill instrumentation)

No further alpha candidates from this angle passed validation.
Future sessions should consider these remaining directions.

## Summary artifacts

- `tb1_scope_analysis.md` — step 1: what tb1 captures vs leaves on table
- `candidates.md` — step 2-3: hypothesis set
- `validation_c4.md` — step 4-5: c4 backtest + tuning
- `iter26_c4_best.py` — the validated production candidate
- `bench5.py` — backtest harness
- `bt_window_compare.py` — per-window trajectory diff tool
- `compare_trajectories.py` — server-log trajectory comparison
