# Round 2 — ideas (archive)

Compiled 2026-05-15 from `ROUND_2/` before pruning.
Products: same as R1 — **OSMIUM** + **PEPPER**.
Server testing was 1 day × **1000 ticks** (not 10k as in R1). Compare
$/tick across submissions, not absolute PnL.

## Best performing strategies

| Sub | File | Server PnL | Notes |
|---|---|---:|---|
| **342122** | `submissions/342122.py` (iter23) | **$9,268** | End-of-round preserved submission. OSM $1,945 + PEPPER $7,323. Log + trade history in `342122.log` / `342122.json`. |

Earlier reference points (no longer preserved on disk):

- **iter30** (sub 332955) — $9,916.50 mid-season high. K=5-outside /
  K=1-inside windows + c4 position-conditional take-gate. Off-disk;
  reference value only.
- **iter6** (sub 305289) — server $1.43/tick vs MC $0.99/tick. The
  first sub that flagged MC under-prediction by ~45% on PEPPER.
- **sub 296164** — failed with `ERROR_FINISHED` from a
  `from prosperity3bt.datamodel` import. Server only accepts
  `from datamodel import …`. The `/imc-submit` skill exists to
  rewrite this automatically.

### Trade breakdown — sub 342122

- **OSMIUM:** 76 fills, 169 bought / 224 sold. Net short ~55. PnL $1,945
  — about 60% of R1's OSM contribution. The iter23 defensive widen plus
  signal-gated PEP recycle protected PEPPER but cost OSM about a third
  of its R1 take.
- **PEPPER:** 47 fills, 129 bought / 51 sold. Net long ~78 (same drift
  position as R1). PnL $7,323 — essentially unchanged from R1's $7,580.

The two rounds reinforce the same conclusion: **PEPPER drift is the
durable edge**. Both R1 and R2 OSM contributions are an order of
magnitude smaller and a function of which side of the adverse-selection
trade you take.

### iter23 design notes

iter22 added defensive widening on both products when bot-take signal
predicts adverse next-tick move. iter23 then gated the PEP recycle
quantity on the same signal — `take_sig ≥ +thresh` skips the recycle
sell entirely; `take_sig ≤ −thresh` doubles it. iter24's dynamic OSM FV
gate regressed −$829/day and was dropped.

Other validated mid-rounds:

- **iter25_tb1** — 2-line OSM quote-anchor change (`fv→dynamic_fv` in
  `bid_pj`/`ask_pj`). Backtest +$1,579 / 3 days. Server mean +$261 / session,
  t=3.81 (4 iter23 vs 3 tb1 samples). Take-gate stays static.
- **iter26_c4_best** — tb1 + position-conditional take-gate relaxation
  (|pos|≥40 AND mid-regime-aligned). Backtest +$3,065 vs iter23
  (+$1,486 vs tb1), all 3 days positive. Defended against Rule-2 failure
  via dual conditions.
- **iter30** — extends iter26 with K=5/K=1 quote windows. Server $9,916.50.

## Critical server-side learnings

1. **`from datamodel import …` is the only valid import path on server**.
   Local-only `prosperity3bt.datamodel` or `prosperity4mcbt.datamodel`
   cause `ERROR_FINISHED`. (Sub 296164 died from this; `/imc-submit` skill
   was built to rewrite these imports automatically.)
2. **Server window = 1 day × 1k ticks** for testing; live is 10k. Compare
   $/tick, not absolute PnL.
3. **Hidden quotes (~20% of stream)** placed by bots *after* trader's
   orders. Visible book is incomplete. Quote-filtering logic was uniform
   regardless of trader presence in R1 → assume same in R2.
4. **80% randomized quote subset** in trial / non-bid-winner runs.
   Top-50% bid wins 100% data access in final. Bid mechanic does NOT
   apply to trial / server-testing.
5. **Deterministic taker schedule** — 50% of OSM taker qty + 31% of PEP
   fire at seeded timestamps with identical qty + direction across days.
   **Not exploitable** via MM quote placement (tape-fixed prices kill
   widens).

## Dead-end signals (do not propose)

| Idea | Result | Why dead |
|---|---|---|
| Wall-aware OSM quoting (v15) | regressed −$161 → −$204 on server | wall is noisy/dynamic, bots exploit predictable placement |
| Wall-FV alpha (v17) | regressed −$204 on server | hidden-FV ≈ 0 on wing instruments; bots already efficient |
| Buy-and-hold PEP | trap (admin-confirmed) | PEP has exploitable drift/seasonality |
| OSM dynamic FV gate (iter24) | −$829/day in backtest | static FV=10001 locally optimal |
| OSM static dynamic-gate, PEP agg_bid take | trap | don't propose either |
| L1-imbalance signal (huge t=25) | regresses $3k in backtest | signals don't translate via take-logic |
| OSM filter for 294069 adverse-selection | upside $0–$34 (0–2% of PnL), goes negative at FP≥7% | skip the filter; calibrate OSM_FAIR |
| Density-trigger BAND=2 tape-pinning | unfireable (book one-sided) | mechanism not tested |
| Density-trigger BAND=5 tape-pinning | fires 3× for −$195/3d | regressive |
| Phase-3 mid±K widening on tb1 | peaks at +$17/3d (K=3) | already exhausted by tb1's `max(ba−1, fv+1)` anchor |
| Pure book-imbalance / cap exploits | iter31-34 all null/regressive | book imbalance signal real but too noisy |

## Confirmed positive signals (R2)

1. **iter25 dynamic FV in quote anchor** (not take-gate): swap `fv` →
   `dynamic_fv` in `bid_pj`/`ask_pj` only. +$1,579/3d backtest, +$261/session
   server, t=3.81 (n=4 vs 3). Take-gate must stay static.
2. **Position-conditional take-gate relaxation (iter26 c4)**: |pos|≥40
   AND mid-regime-aligned. Backtest +$3,065. Dual-condition defends
   against Rule 2 (regime-aware) failure modes.
3. **Three-phase tick structure** (verified via `prosperity3bt` two-stage
   matching): phase-3 tape = 61.6% of iter25_tb1 fills. OSM tape bimodal
   at mid±5+.

## Discord intelligence (data scaling, mechanics)

- Cumulative R1+R2 ≥ **200k** required to advance. Buy-and-hold alone
  cannot make Phase 2 (admin-confirmed).
- After R2 closes, rankings reset for R3+. R1+R2 PnL still counts for
  qualification.
- "My osmium was heavily dependent on the middle exploits of the day"
  (single source) — OSM may have intra-day variance worth checking.
- Phantom-fill evidence: user reported market order filling at 13013 when
  best visible bid was 13014 — exactly the 80%-subset signature.

## Carryover gotchas

1. **MC backtester is not server.** Iter26 c4 +$3,065 in backtest →
   approximate +$2.5k on server (translation rate ~80% per "MC v2
   underpredicts server by ~18%").
2. **Take-logic doesn't translate** for all signals that look great in
   backtest. Pattern: high-t signals on book features regressed
   consistently. Make-side improvements port better.
3. **Static FV=10001 for OSM is locally optimal** — dynamic gates are
   traps unless the dual-condition guards from iter26 are in place.
