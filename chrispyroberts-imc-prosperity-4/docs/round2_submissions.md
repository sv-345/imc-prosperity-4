# Round 2 Server Submissions

Target: server PnL ≥ 13,000 with robust non-overfit logic.

Server spec: 1,000 ticks from day-0 held-out data (~10% of day 0).

---

## Submission 1 — ID 296164 — 2026-04-18 11:18 — ERROR

Hypothesis: iter 6 strategy (passive MM + inventory skew) should roughly
match its MC mean on server.

Change vs prev: n/a (first submission).

Pre-submit MC: per-tick $0.99 (heavy mean 29,631 / 30,000 ticks), P05 ≥ 0.

Server result: **ERROR_FINISHED** — `ImportModuleError: No module named
'prosperity3bt'`. Trader never ran; `profit = null`.

Biggest leak: local `datamodel` alias under `prosperity3bt.datamodel` is not
on the IMC server. The import error crashed every tick.

Next: swap `from prosperity3bt.datamodel import ...` → bare `from datamodel
import ...` (iter6_trader_server.py).

---

## Submission 2 — ID 294069 — 2026-04-18 16:04 — FINISHED

Hypothesis: iter 6 strategy on server (same logic, import fixed) will
deliver per-tick rate near MC's $0.99.

Change vs prev: import rewrite only (`prosperity3bt.datamodel` → `datamodel`).

Pre-submit MC: per-tick $0.99.

Server result: **total $1 434.35**, per-tick $1.43 (+45% vs MC prediction).
  OSM  $722.25  |  PEP $712.10

Per-tick delta vs prev: n/a (first successful run).

Biggest leak: PEP captured almost no drift — skew=20 aggressively neutralized
inventory, so position hovered near 0 while PEP drifted +$100 over the slice.

Next: break balanced MM on PEP — accumulate long directionally to capture
the +$0.10/tick drift (iter 7).

---

## Submission 3 — ID 294616 — 2026-04-18 16:29 — FINISHED

Hypothesis: replace PEP balanced MM with long-accumulation (passive bid at
fair-1, ask only at wall fair+10). Capture drift by holding long.

Change vs prev: PEP strategy → long-lean. OSM unchanged.

Pre-submit MC: per-tick $2.69 (heavy mean 80,820 / 30,000 ticks), P05 78,666.

Server result: **total $2 065.19**, per-tick **$2.07** (+44% vs prev).
  OSM  $699.19  |  PEP $1 366.00

Per-tick delta vs prev: +44 % ✓

Biggest leak: **fill-rate bottleneck**. PEP max long reached only **26**
(target 70). First PEP buy at tick 50 (not 0). Passive bid at fair-1 was
outbid — other teams probably bid more aggressively. We captured only 17 %
of the $7 400 theoretical PEP drift ceiling.

Next: switch from passive bid to active sweep — bid at floor(fair)+8 to
cross the bot inner ask every tick (iter 8).

---

## Submission 4 — ID 294882 — 2026-04-18 16:38 — FINISHED

Hypothesis: active sweep at `floor(fair)+8` bypasses the fill-rate ceiling.
Position builds to the limit within ~8 ticks (bot inner ask refreshes every
tick at 10 units), then we hold for the remaining 992 ticks of drift.

Change vs prev: PEP bid moved from passive fair-1 to cross-the-book
floor(fair)+8. Sweep size governed by `PEP_LONG_TARGET=78` safety margin.

Pre-submit MC: per-tick $3.05 (heavy mean 91 399, std 833, P05 90 066).

Server result: **total $7 748.38**, per-tick **$7.75** (+275 % vs prev).
  OSM  $613.12  |  PEP $7 135.25

Per-tick delta vs prev: +275 % ✓

Biggest leak: PEP near theoretical max (7 135 / 7 222 ceiling at target 78).
OSM slight regression ($613 vs $699) — hardcoded `OSM_FAIR=10001` constant
fails when real OSM fair oscillates within the slice (observed 9991–10017).

Next: raise PEP target 78 → 80 (+$200 ceiling) and add OSM take-crossings
(iter 9); then switch OSM to adaptive deepest_mid fair (iter 10).

---

## Submission 5 — ID 295237 — 2026-04-18 16:54 — FINISHED

Hypothesis: pushing `PEP_LONG_TARGET=80` adds 2 units × $99 drift. OSM
take-crossings (OSM_TAKE_THRESHOLD=1) adds ~$200 from free mispricings.

Change vs prev: `PEP_LONG_TARGET` 78→80, add OSM take-crossings.

Pre-submit MC: per-tick $3.20 (heavy mean 95 876).

Server result: **total $8 289.25**, per-tick **$8.29** (+7 % vs prev).
  OSM  $881.25  |  PEP $7 408.00

Per-tick delta vs prev: +7 % ✓ (but below 10 % threshold — watchlist).

Biggest leak: **OSM mid oscillates 9991–10017 within the slice** but my
strategy thinks fair is constant 10001. Per-segment averages: seg 1 = 10008,
seg 3 = 10002, seg 7 = 10006. My quotes at 9994/10008 sat below the real
market during ~400 ticks of the elevated segments and never won top-of-book.

Next: compute OSM fair via deepest_mid (wall-midpoint) — same robust
estimator PEP uses. Adaptive fair tracks real shifts (iter 10).

---

## Submission 6 — ID 295454 — 2026-04-18 17:04 — FINISHED

Hypothesis: switching OSM from `OSM_FAIR=10001` constant to `deepest_mid`
will track the real OSM mid (a true random walk per R1 PHASE2 profile,
σ≈0.31/tick) and unlock fills during elevated segments.

Change vs prev: OSM fair = deepest_mid(depth). Nothing else.

Pre-submit MC: per-tick $3.20 (unchanged — MC has constant OSM fair, so the
adaptive estimator returns the same value).

Server result: **total $8 744.00**, per-tick **$8.74** (+5.4 % vs prev).
  OSM  $1 353.00 (+54 %)  |  PEP $7 391.00 (−0.2 %)

Per-tick delta vs prev: +5.4 % ✓ (below 10 % threshold — 2 consecutive).

Biggest leak: **approaching hard ceiling**. PEP near max ($7.4 k at
80-long × 1000-tick × $0.10 drift − $7/unit sweep cost). OSM near max with
adaptive fair + take. Additional $4 k to reach 13 k has no obvious source
from the 2-product / 1-day-slice structure.

Next: investigate whether any remaining edge exists (momentum on OSM RW?
Multi-cycle PEP position management?). If iter 11 shows < 10 % improvement,
per workflow rule the strategy family is exhausted and the 13 k target is
genuinely out of reach for this round's mechanics.

---

## Submission 7 — ID 295615 — 2026-04-18 17:11 — FINISHED (iter10 re-submit)

Hypothesis: verify iter10 reproduces (gate requires ≥2 matching submissions
for a strategy to count).

Change vs prev: none — same file, second submission.

Server result: **total $8 583.81**, per-tick **$8.58**
  OSM  $1 184.81  |  PEP $7 399.00

Verdict: **reproducible within 2 %**. iter10 gives $8.6–8.7 k reliably.
PEP is dead-stable ($7 391 vs $7 399 = 0.1 % variance). OSM has 12 % per-run
variance (random-walk realization of the slice).

## Submission 8 — ID 295825 — 2026-04-18 17:21 — FINISHED

Hypothesis: OSM segment averages in iter 9 and iter 10 showed the same
peak-trough-peak oscillation — if deterministic structure, mean-reversion
lean on `deepest_mid − 10001` should capture it.

Change vs prev: added `rev_shift = dev // 3` to OSM skew term. No-op in MC
(MC fair is truly constant 10001, so dev = 0 always).

Pre-submit MC: per-tick $3.20 (unchanged — feature is server-only).

Server result: **total $8 583.41**, per-tick **$8.58**.
  OSM  $1 078.41  |  PEP $7 505.00

Per-tick delta vs prev: 0 %.

Verdict: **pattern was random-walk realization, not deterministic.** Three
consecutive iter10-family submissions at $8.58 / $8.58 / $8.74 / $8.29 —
all land within the same $8.3–8.7 k band. OSM micro-oscillations are
path-specific noise.

## Per-tick trajectory

| Sub | ID | $/tick | Δ | OSM | PEP | Notes |
|---|---|---:|---:|---:|---:|---|
| 1 | 296164 | — | — | — | — | ERROR (import) |
| 2 | 294069 | 1.43 | — | 722 | 712 | balanced MM baseline |
| 3 | 294616 | 2.07 | +45 % | 699 | 1 366 | + PEP long-lean (fill-rate blocked) |
| 4 | 294882 | 7.75 | +275 % | 613 | 7 135 | + PEP active sweep |
| 5 | 295237 | 8.29 | +7 % | 881 | 7 408 | + OSM take, PEP target 80 |
| 6 | 295454 | 8.74 | +5 % | 1 353 | 7 391 | + OSM adaptive fair |
| 7 | 295615 | 8.58 | −2 % | 1 185 | 7 399 | iter10 re-submit (reproducibility) |
| 8 | 295825 | 8.58 | 0 % | 1 078 | 7 505 | + OSM mean-reversion lean (no effect) |

**Ceiling was wrong.** Triangulation with community alpha + R1 post-mortem
unlocked v82's richer OSM structure. Continuation below.

---

## Submission 9 — ID 296317 — 2026-04-18 17:46 — FINISHED (iter 12 — v82 port)

Hypothesis: port R1 v82_hardened verbatim. v82's OSM logic (aggressive
take + fv±20 wide snipe + dual-layer passive quotes) earned $18.8 k on 10 k
R1 ticks = $1.88/tick — 40 % higher rate than iter 10's OSM. v82's PEP
includes auto-intercept detection + recycle-when-long branch that iter 10
lacks.

Change: full strategy replacement from iter 10 (iter10_trader.py) to
v82-hardened port (iter12_trader.py). Imports stripped to bare `datamodel`;
Logger removed.

Pre-submit MC: per-tick **$3.33** (+4 % vs iter10's $3.20). PEP $82 617,
OSM $17 135. All gates pass.

Server: **$9 227.25**, per-tick **$9.23** (+7.6 % vs iter 10).
  OSM  $1 877.31 (+58 % vs iter10's $1 185)  |  PEP $7 349.94

**The $8 600 "ceiling" was wrong by $600** — and that's without further
tuning. v82's OSM machinery unlocked structural edge my simpler iter 10
missed: the 3 fills in the 16–20 distance band and 10 fills in the 11–15
band are entirely new MM flow. PEP held at the ~$7.4 k mechanical max.

## Submission 10 — ID 296379 — 2026-04-18 17:49 — FINISHED (iter 12 re-submit)

Hypothesis: confirm iter 12 reproduces across the 80 %-randomized data runs.

Server: **$9 606.50**, per-tick **$9.61**.
  OSM  $1 928.25  |  PEP $7 678.25

Two iter 12 runs land at $9 227 and $9 607 → median **$9 417**, range
$9.2–9.6 k. Reproducible. PEP recycling added ~$300 on this run vs
iter10 baseline.

## Submission 11 — ID 296878 — 2026-04-18 18:13 — FINISHED (iter 13 — R1 CF3)

Hypothesis: R1 post-mortem CF3 — drop `vol ≤ 9` trigger, require
real_edge ≥ 2 for all OSM crosses. Hindsight estimate +$1–2 k on 10 k
ticks; scaled to R2 ≈ +$100–200.

Pre-submit MC: $3.32/tick (essentially identical to iter 12 because the
vol ≤ 9 branch rarely fires in MC's clean book).

Server: **$9 470.84**, per-tick **$9.47**.
  OSM  $1 750.59 (−$170 vs iter12.1)  |  PEP $7 720.25

**CF3 regressed OSM by ~$150** on server, confirming R1 post-mortem's
warning: the `vol ≤ 9` branch has net-positive contribution despite the
140 weak-markout losers. **Reverting CF3 for iter14+.**

## Submission 12 — ID 297226 — 2026-04-18 18:31 — FINISHED (iter 14 — PEP wider sweep)

Hypothesis: widen PEP accumulation buy_limit from fv_int+6 to fv_int+10
so we sweep inner AND wall asks, reaching +80 faster → more time holding
+80 → more drift captured. R1 CF2 estimated +$50–150 hindsight.

Pre-submit MC: $3.29/tick (−1 % vs iter12). Wider sweep pays more per unit.

Server: **$9 304.50**, per-tick **$9.30**.
  OSM  $1 563.25  |  PEP $7 741.25

PEP up ~$250 vs iter12 median as hoped (faster accumulation works). OSM
down $300 — variance from the 80 % data randomization. **Net ≈ zero** vs
iter12. Iter 14 marginally improves PEP fast-ramp but doesn't close the
$3.5 k gap to 13 k.

## Per-tick trajectory (updated)

| Sub | ID | $/tick | ΔPT | OSM | PEP | Notes |
|---|---|---:|---:|---:|---:|---|
| 2 | 294069 | 1.43 | — | 722 | 712 | balanced MM baseline |
| 3 | 294616 | 2.07 | +45 % | 699 | 1 366 | + PEP long-lean |
| 4 | 294882 | 7.75 | +275 % | 613 | 7 135 | + PEP active sweep |
| 5 | 295237 | 8.29 | +7 % | 881 | 7 408 | + OSM take, PEP target 80 |
| 6 | 295454 | 8.74 | +5 % | 1 353 | 7 391 | + OSM adaptive fair |
| 7 | 295615 | 8.58 | — | 1 185 | 7 399 | iter10 re-submit (reprod.) |
| 8 | 295825 | 8.58 | 0 % | 1 078 | 7 505 | + OSM mean-rev (no effect) |
| 9 | 296317 | **9.23** | **+7.6 %** | 1 877 | 7 350 | **iter12 v82 port — broke ceiling** |
| 10 | 296379 | 9.61 | — | 1 928 | 7 678 | iter12 re-submit (reprod.) |
| 11 | 296878 | 9.47 | — | 1 751 | 7 720 | iter13 CF3 — regressed OSM, revert |
| 12 | 297226 | 9.30 | — | 1 563 | 7 741 | iter14 wider PEP sweep — neutral |

**v82-family reproducible band: $9.2–9.6 k, median $9.47**. Per-tick ≈ $9.4.

---

## Bot-take hypothesis series (iter 20–22)

After triangulation identified bot-take behavior as the gap, extracted
395 bot-bot trades (R1 + R2) with z=19.5 on PEP buy-take → fwd_1 mid.

| sub | ID | iter | strat | Total | OSM | PEP | Δ vs median |
|---|---|---|---|---:|---:|---:|---:|
| 21 | 299063 | 20 | direction price-shift | 9 361 | 1 746 | 7 615 | −$39 |
| 22 | 299103 | 21 | direct aggressive cross | **9 026** | 1 926 | 7 100 | **−$400** |
| 23 | 299166 | 22 | defensive widen | **9 625** | 2 034 | 7 590 | +$208 |

**Findings**:
- **Attacking** the signal (iter20 shift, iter21 cross) failed because the mid
  move has already happened by the time `state.market_trades` exposes the
  bot-take. Latency kills the alpha.
- **Defensive** use (iter22 — pull adverse-side quotes) marginally helped
  (+$200 OSM), but the total still in-band because few ticks trigger the
  signal threshold. Best-in-band score at $9,625.
- z=19.5 signal is real in data but mostly unattributable to a single
  actionable fill once the tick clock advances.

---

## Bot-take series iter 23-24 (continuation)

Shifted from "trade the signal" to "SIZE-gate trades by signal":

### Submission 24 — ID 299263 — iter 23 (PEP recycle signal-gate)

Hypothesis: PEP recycle sell quantity should be 0 when +sig (ask about to
be adversely selected), 15 when -sig (ask is in best quality window per
fill-outcome data pnl50 = −$1.33/u vs 0sig −$3.82/u), default 8 otherwise.

Server: **$9,867** (OSM $2,162, PEP $7,705). **NEW HIGH — broke $9.6 band.**

### Submission 25 — ID 299298 — iter 23 re-submit

Server: **$9,501** (OSM $1,788, PEP $7,712).

### Submission 26 — ID 299361 — iter 24 (+ OSM size boost on -sig)

Server: $9,572 (OSM $1,899, PEP $7,672). Within iter23 band.

### Submission 27 — ID 299394 — iter 23 run 3

Server: **$9,673** (OSM $1,833, PEP $7,839).

**iter 23 three-sample: {9867, 9501, 9673}  mean $9,680  std $185  min $9,501**

**+$263 reliable lift from iter 12 baseline ($9,417 median).**

### Continuation iter 25-26 (predict-the-take angle + architecture test)

iter 25: tighter PEP bid (bb+2) — harvest-flow hypothesis from fingerprint
analysis showing PEP takes are near-uninformed.
Server: $9,094 (OSM $1,627, PEP $7,467). **Regressed $586 vs iter23.** Tighter quoting lost on spread economics.

iter 26: architecture change — remove v82 PEP recycle entirely.
Server: $9,120 (OSM $1,709, PEP $7,411). **Regressed $560 vs iter23. PEP dropped $341.**
Recycling is confirmed net-positive on server.

### Winner: iter 23

After 6 distinct bot-take-family hypotheses (iter20-26), iter 23's
signal-gated PEP recycle size is the only variant that moved the reproducible
mean above the iter12 band. Per-tick median **$9.68**.

| metric | iter12 (v82 port) | iter23 (v82 + signal) | Δ |
|---|---:|---:|---:|
| Per-tick mean | $9.42 | **$9.68** | +2.8 % |
| OSM mean | $1,828 | $1,928 | +$100 |
| PEP mean | $7,587 | $7,752 | +$165 |

The bot-take signal-gated PEP recycle is a **real, reproducible alpha** at
$200-300 per slice. It's the first structural improvement on top of v82.
But it's not enough — still $3.3k short of $13k target.

## Honest gap analysis

Target $13 k on 1000-tick testing slice = $13/tick. v82 on R1 full scoring
(10 k ticks) earned $10.12/tick; community reports same strat earning $8.4k
testing = $8.4/tick (generoce). My $9.4/tick median is **above both of
these data points**. No documented strategy has demonstrated $13/tick on
R2 testing.

Where $3.5 k more might come from (unexplored):
- **Hidden-quote adverse selection awareness**: admin-confirmed 20 % of
  quotes are placed after our orders. Our quotes experience worse fill
  rates than MC assumes. Widening passive spreads could partially
  compensate but unlikely to 1.5× OSM.
- **Predictive OSM micro-structure**: community reports OSM pattern
  detection beyond random walk. Requires building a book-feature model I
  don't have.
- **Novel PEP alpha**: stefanos_44723 says "top players use another
  approach on pepper rather than buy-and-hold" — specific strategy not
  disclosed. Unclear what to build.
- **Final-round 10× data scaling**: per community, live round may run
  10 k ticks vs testing's 1 k. At $9.4/tick, final = $94 k (+ $101 k R1 =
  ~$195 k cumulative, just below 200 k qualification). Testing 13 k is
  not the operational goal if scaling holds.

## Standing ceiling estimate

- PEP drift capture (80 units × $100 slice drift − $560 sweep cost): **$7 400**
- OSM MM + take + adaptive fair (σ=0.31 RW spread capture): **$1 400–1 600**
- **Total ceiling: ~$8 900** — iter 10 at $8 744 is **98 %** of ceiling.

Remaining $4 k gap to 13 k would require a structural alpha source not
present in a 2-product, 1-day-slice, position-capped-at-80 market:
  - more products (R2 rules: no)
  - baskets / conversions (R2 rules: no)
  - observations (R2 rules: no)
  - longer scoring window (not mine to control)
