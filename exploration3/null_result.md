# Exploration session 3 — result

## Verdict

**No robust bot-behavior alpha found.** One marginal parameter-tuning
candidate (cand_4 pos<66) passes the backtest gate (+$610 over 3 days,
all 3 days positive), but is **not recommended for submission** because
the wins are within-day noise ($26-$31 on days 0 and 1) and the
parameter's threshold sensitivity is severe (+$610 at pos<66 vs +$87
at pos<67 — a 7x swing between adjacent integer settings indicates
the result is fitting noise rather than a stable structural gain).

The bot-behavior angles listed as candidates (bot sizing rules, taker
inter-arrival timing, mid-drift triggers) were examined and ruled out
by direct backtest.

## Methodology

Strict per the prompt:
1. Formulate candidate rule.
2. Event-count validation at >95% consistency (or large t-stat for
   continuous signals).
3. Draft `iter_candidate_N.py`.
4. Run prosperity3bt on 2--1, 2-0, 2-1.
5. Validated only if 3-day delta > +$100 AND all 3 days positive.

No simulator projections. No event-count extrapolation. Only real
backtest deltas.

## Candidates examined

### Signal-based (bot-behavior, rejected)

| # | rule | event-count stat | 3-day backtest Δ | verdict |
|---|------|------------------|------------------:|---------|
| 1a | OSM wall-vol imbalance → defensive widen | t=3.1-4.4 at \|imb\|≥10 | −$6,590 | REJECTED |
| 1b | same, shrink-only, tighter threshold | same | −$38 | NEUTRAL |
| 1c | same signal, offensive tighten instead | same | −$471 | REJECTED |
| 2 | OSM L1 vol imbalance → conditional gate extend | **t=10-25** at \|imb\|≥8 | −$3,048 | REJECTED |
| 6 | PEP fast-accum gated by take_sig | — | −$1,588 | REJECTED |
| 7 | OSM take-ask: drop `vol≤9` fallback | (examine fallback) | −$978 | REJECTED |
| 8 | OSM take-ask: real_edge≥1 (was ≥2) | (loosen threshold) | −$312 | REJECTED |

**Key observation:** the L1 volume imbalance signal has t-stats up to
25 with magnitudes of 1-3 ticks per event — one of the strongest
forward-mid signals in the data. It does NOT translate into backtest
alpha via take-logic changes. The mechanism (thin L1 ask gets eaten
first, ask L1 walks up, mid rises) is mechanical, not fundamental;
capturing the mechanical move requires unwinding at the new higher
price, which requires crossing the new bid (spread cost) that exceeds
the signal edge.

**This is the same trap as Rule 2 (OSM static gate) from session 1:**
high-t-stat signal + plausible mechanism → still regresses in real
backtest because the simulator-intuitions don't account for the cost
of offsetting the captured signal through the real book.

### Parameter tuning (not strictly bot-behavior)

| # | rule | 3-day backtest Δ | per-day | verdict |
|---|------|-----------------:|---------|---------|
| 3 | PEP pos-scaled recycle sell size | +$0 | flat | NEUTRAL |
| 4 pos<50 | PEP recycle earlier (was 70) | −$968 | reg | reject |
| 4 pos<55 | | −$710 | reg | reject |
| 4 pos<60 | | +$205 | d-1+205, d0+40, d1−240 | fails d1 |
| 4 pos<61 | | +$304 | d1 reg | fails d1 |
| 4 pos<62 | | +$315 | d1 reg | fails d1 |
| 4 pos<63 | | +$431 | d1−193 | fails d1 |
| 4 pos<64 | | +$431 | d1−193 | fails d1 |
| 4 pos<65 | | +$395 | d1−90 | fails d1 |
| **4 pos<66** | **PEP recycle at pos<66** | **+$610** | **d-1+553, d0+31, d1+26** | **PASSES (marginal)** |
| 4 pos<67 | | +$87 | ~zero | fails $100 gate |
| 4 pos<68 | | +$245 | d1−18 | fails d1 |
| 5 | PEP fast-accum +2 wider buy-limit | −$1,296 | reg | reject |

The pos<66 peak at +$610 is suspicious: it's sandwiched between
pos<65 (+$395, fails d1 -$90) and pos<67 (+$87, fails d1 -$18). A
7x swing across a single integer suggests this is curve-fitting to a
specific fill event, not a structural gain.

## Backtest gate hit rate

- Candidates drafted: 9 distinct (plus sweeps)
- Candidates passing event-count validation pre-backtest: 2 (wall-imb,
  L1-imb — both signals have |t| ≥ 4 across all 3 days)
- Candidates passing backtest gate (Δ > +$100 AND all days positive): 1 (cand 4 pos<66)
- Of that 1, stability to parameter perturbation: POOR (peak is narrow)

## What was NOT found

- No bot-sizing rule that yields exploitable alpha. Wall volumes are
  roughly uniform U(20,30) on OSM and U(15,25) on PEP with 8-14%
  outliers below. The "which-vol-is-it" per tick is approximately
  independent (Poisson) — not deterministic.
- No taker inter-arrival pattern. Bot-3 inter-arrival CV ≈ 1.0
  (geometric/Poisson), not deterministic. Can't predict when a bot-3
  will appear.
- No mid-drift trigger event where a specific bot action deterministically
  predicts a large move. The imbalance signals predict magnitudes of
  1-5 ticks (real but mechanical), and this doesn't beat the spread.
- No cross-product signal. OSM and PEP aggressive-event co-occurrence
  matches chance (validated in session 1).

## What IS true but not exploitable

- **L1 vol imbalance is a huge forward-mid predictor.** t up to 25,
  magnitudes 1-3 ticks per event. Mechanism: thin-side gets eaten,
  next-level becomes L1, mid walks. Exploitation via take-logic
  regresses (cand 2 = −$3k).
- **Wall vol imbalance is a smaller forward-mid predictor.** t up to
  4, magnitudes 0.3-0.5. Same category: real but unexploitable.
- **Trade-after effects exist but are small.** Post-buy-taker on OSM:
  next-px-shift = +0.04 (near zero). On PEP: +3.04 (large, but drift
  + bid-ask bounce account for most of it).

## Recommendation

**Session-3 verdict: NULL.** Do not ship cand_4 pos<66.

Supporting reasoning:
1. The single positive result is within single-digit $ on 2 of 3 days
   (+$31, +$26). That's well within the ±$135 1σ noise band on iter23
   (per consolidated_baseline/README.md).
2. The threshold sensitivity (+$610 at 66 vs +$87 at 67) indicates
   the "alpha" is capturing a small handful of specific fills, not a
   robust phenomenon.
3. We're unable to identify a mechanism that explains WHY pos<66 is
   specifically better than pos<65 or pos<67. Without a mechanism, we
   can't expect it to hold on unseen server data.
4. The 80% quote randomization means server sessions draw different
   samples from the master tape. A threshold-tuned result on THIS
   training sample won't hold on server samples that differ at the
   specific fill-event level.

## Framework implication

Two sessions have now produced:
- Session 1: validated-looking signal (OSM static-gate) → falsified by backtest.
- Session 3: no signal-based rule passes backtest; one parameter-tuning
  candidate passes but is noise.

The pattern supports the session-3 prompt's premise: **isolated
signals (forward-mid t-stats, event counts) are not predictive of
backtest PnL delta**. The signal-to-alpha translation step is where
the alpha gets absorbed by adverse selection / spread cost.

Future sessions should either:
- Work directly with backtest deltas from the first step (parameter
  sweeps, not signal hunting), OR
- Find a new class of signal that doesn't require crossing the spread
  to exploit (pairs trading, aggregator positions, time-of-session
  regimes where MM can be systematically wider/tighter without
  taking).

## Artifacts

- `scan_bot_patterns.py` — H1-H6 scan (wall vol, L3, post-trade, bot-3 IATs, imbalance)
- `scan_more.py` — H7-H11 scan (L1 imb, vol transitions, session time, post-trade directions, one-sided book)
- `iter_candidate_1{,b,c}.py` — wall-imb variants
- `iter_candidate_2.py` — L1-imb conditional gate
- `iter_candidate_3.py` — PEP pos-scaled recycle sell
- `iter_candidate_4.py` + `iter_cand4_{50,55,61,62,63,64,65,66,67,68,75}.py` — PEP recycle threshold sweep
- `iter_candidate_5.py` — wider fast-accum
- `iter_candidate_6.py` — take-sig-gated fast-accum
- `iter_candidate_7.py` — drop `vol<=9` fallback
- `iter_candidate_8.py` — tighter real_edge threshold
- `bench.py` — backtest harness
