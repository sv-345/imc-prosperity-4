# IMC Prosperity 4 — archive & handoff

**Season:** Spring 2026 (Prosperity 4). Completed through Round 5.
**Owner:** Sourabh Velaga (Arcturus444 on GitHub).
**Last touched:** 2026-05-15.

This repo is an end-of-season archive of every IMC Prosperity 4 round I
worked on. It's organized so a future agent (mine or someone else's) can
walk in cold next year, read this file, and have enough context to skip
the dead-ends I already paid for.

The per-round `README.md` files (was `R{n}_ideas.md`) are the substantive
content — strategies, bot models, calibration learnings, what worked and
what didn't. This top-level file is a map.

---

## Folder layout

```
tutorial/                 — Tutorial round (EMERALDS, TOMATOES)
round1/                   — OSMIUM + PEPPER MM. Best preserved: $101k server.
round2/                   — OSMIUM + PEPPER continued. Iter30 ~ $9,916 / 1k ticks.
round3/                   — HYDROGEL + VELVET + 10 VEV vouchers. $14,601 server.
round4/                   — Same products + counterparty disclosure mechanic.
round5/                   — 50 products / 10 families. NO ROBUST STRATEGY — read caveats.

shared/
  backtesters/
    prosperity3bt-fork/   — R1-era Python backtester (community fork)
    prosperity_rust_backtester/ — R3+ Rust sim (faster, used R3/R4)
  reference/
    chrispyroberts-imc-prosperity-4/ — top-finisher's open-sourced code

archive/
  research_org/           — multi-agent orchestration scaffolding (R2 deep-work era)
  supervisor/             — supervisor/inbox/outbox pattern (R2 era)
```

Each `round*/README.md` is the canonical writeup. Strategy files live
under `round*/strategies/` or as bare `trader*.py`. Round 1 has its own
calibrated Monte-Carlo backtester under `round1/mc/` — read its docstrings
before rewriting from scratch.

---

## Headline results

| Round | Best strategy (preserved) | Server PnL | Notes |
|---|---|---:|---|
| Tutorial | `tutorial/trader.py` (v14) | $2,757 | MC overpredicts by ~6× — trust server. |
| R1 | `round1/strategies/trader_273632_final.py` | **$101,199** | 1d × 10k ticks. ~81% from PEP drift. |
| R2 | iter30 (sub 332955, **not preserved on disk**) | $9,916 | 1d × 1k ticks. iter26_c4_best is the closest preserved variant. |
| R3 | `round3/trader.py` (v86) | **$14,602** | Anchor-relative take on HYDROGEL/VELVET = $13k of it. |
| R4 | `round4/submission/trader_r4_n24.py` | not recorded | Counterparty-disclosure round; Olivia-style copy-trade was the brief. |
| R5 | sub 570453 (**not preserved**) | not durable | Strategies failed multiple-comparisons; archive is for caveats only. |

---

## How to backtest and submit

**Local backtests:**

- R1: use `round1/mc/` (calibrated to ρ=1.0 vs server ranking). Entry
  point: `mc/server_book_replay.py::run_server_session`.
- R2: use `shared/backtesters/prosperity3bt-fork/`. Three-phase tick
  matching is real — see `shared/backtesters/prosperity3bt-fork/NOTES_FORK.md`.
- R3/R4: use `shared/backtesters/prosperity_rust_backtester/` (10–100×
  faster than Python). R4 also has a self-contained
  `round4/backtester/` copy of `prosperity3bt` with cached round data
  baked into `prosperity3bt/resources/round{0..8}/`.
- R5: no preserved backtester. Build a queue-aware passive-fill harness
  first — most R5 microstructure signals were un-deployable under
  aggressive fills.

**Submitting to the live server:**

Use the `/imc-submit` skill. It rewrites local-only imports
(`prosperity3bt.datamodel`, `prosperity4mcbt.datamodel`) to
`from datamodel import …` — the server only accepts the bare form. Sub
296164 in R2 died with `ERROR_FINISHED` from this exact mistake. Don't
hand-edit imports.

---

## The reusable playbook (extracted from R1, validated across R2)

R1 delivered ρ=1.0 Spearman rank vs server across 4 submissions. The
methodology is in `round1/README.md` §4, but the gist:

1. **Phase 1 — Hint extraction (half-day).** Read every README and inline
   comment in the shipped Prosperity repo. Don't over-invest; 60% gets
   overwritten by Phase 2.
2. **Phase 2 — Data-first statistical profile (1–2 days).** Per product:
   FV process (σ/tick, drift, quantization), bot quote archetypes
   (wall/inner/near-mid), taker flow (Bernoulli rate, qty dist, side
   split). **Rule: every constant in the MC must trace to Phase 2.**
3. **Phase 3 — Three-level MC validation (1–2 days).** (a) Book-replay
   against recorded server book. (b) Rank-preservation across ≥3 prior
   submissions — pass if Spearman ρ ≥ 0.9. (c) Parameter-sensitivity
   sweep, accept plateaus.
4. **Phase 4 — DRO (1 day).** Uncertainty set Ξ over 6 scenarios; grid
   θ × Ξ × seeds. Prefer DRO-optimal over EV-optimal unless EV gap
   > 10% AND min-scenario gap < 5%.

R1 also revealed a calibration trap that bit every subsequent round —
the PnL double-count (per-tick MTM PLUS final-position-value
mark-to-market). **Track cash flows only during simulation; compute
`PnL = cash + pos × final_FV` at the end.** Failure mode added ~+8000
phantom PnL on PEP in R1.

---

## Cross-round dead-ends — DO NOT RE-PROPOSE

Per the per-round notes, these were validated dead and burned cycles:

- **Hidden-FV / wall-FV alpha** (R1 v17): −$204 on server. Looks great in
  MC because bots queue predictably; on server the queue dynamics shift.
- **Buy-and-hold any product** (Tutorial through R3): trap. Drift is
  real but the spread/timing edge dominates for MM strategies.
- **L1 imbalance signals** for take-logic (R2 exploration3): high t-stat
  in feature space, regressive in PnL space. Pattern repeats across
  features — book-imbalance signals consistently fail to translate
  through take-logic. Make-side improvements port better.
- **Dynamic OSM FV gate** (R2 iter24): −$829/day vs static FV=10001.
  Iter26_c4_best is the only safe dynamic-gate variant (dual condition).
- **PEBBLES basket arbitrage** (R5 A1): perfect identity `sum=50000±3`,
  but 5-leg round-trip spread (~30) >> tradable deviation (~10). Useful
  as a sanity filter, not a trade.
- **Wall-aware OSM quoting** (R1 v15): −$161 on server. Walls are noisy.
- **Per-counterparty profiling on `buyer`/`seller` fields** (R5):
  promised but fields were 100% NULL. R4 was the round that finally
  populated them; verify before promising any counterparty alpha.
- **MICROCHIP_SQUARE spread MR** (R5 A8): IC=-0.22 is real but the spread
  IS the cost. Same trap as SNACKPACK aggressive.
- **`micro_PEBBLES_XL_RV200`** (R5): day-4 OOS = −$27,696, max DD −$45,071,
  top-1% concentration 60%. Looks great in-sample; killed by red team.

A longer list with mechanisms is in each `round*/README.md`.

---

## Persistent context (the auto-memory)

Everything I learned that's *non-derivable* from the code lives in:

```
/Users/svelaga/.claude/projects/-Users-svelaga-Documents-IMC-Prosperity/memory/MEMORY.md
```

That file is a one-line-per-memory index pointing to per-fact `.md`
files in the same dir. Examples worth checking before starting a new
round:

- `backtester_calibration.md` — the PnL double-count and rate fixes.
- `mc_validation_results.md` — what passes/fails the ρ=1.0 bar.
- `deterministic_market.md` — server market state is identical across
  submissions; only PnL differs.
- `r2_server_testing_length.md` — server test = 1 day × 1000 ticks (not
  10k). Compare $/tick, not absolute.
- `bot_discovery_guide.md` — methodology pointer for reverse-engineering
  bots from prices+trades. Reference at `round1/exploration_r3/`
  (consult chrispyroberts repo if missing).

If you're an agent reading this, **load that memory dir at session
start**.

---

## Round 5 caveat — read before reusing the cluster approach

R5 used a 7-sub-agent topology (A: viz, B: single-product microstructure,
C: cointegration, D: anonymous order-flow, E: red team, F: passive-fill
harness, G: manual puzzle). The methodology was clean, the cluster
shipped, but the strategies were not durable in production.

Failure modes documented in `round5/README.md`:

1. **Multiple comparisons.** 1,225-pair search universe → Bonferroni
   threshold p < 4.08e-05. Smallest observed p = 0.00144. Selection was
   done on relative walk-forward Sharpe, not statistical proof.
2. **β instability.** GSD/TSG β flipped sign day-2 → full-sample
   (−0.65 → +0.19). Refit daily if you reuse cointegration.
3. **Tick-cluster concentration.** All 4 deployed pairs had top-5% PnL
   share > 60%. One bad cluster wipes the strategy — drawdown stops
   are essential.

The sub-agent topology is still worth repeating; the trust-the-Sharpe
ranking is not.

---

## What to do next year, in order

1. Read `round{N-prev}/README.md` for the round you're entering (round
   numbers reset between seasons but products often rhyme).
2. Re-validate the calibration bug fix is still applied on whichever
   backtester you start from (`round1/mc/` is the cleanest reference
   for the cash-flow accounting fix).
3. Run Phase 1 + Phase 2 from the playbook above. Don't skip to alpha
   search until Phase 2's per-bot profile is written down.
4. Before deploying anything microstructural, ask: does this signal
   translate through aggressive fills, or do I need a passive-fill
   harness? R5 buried itself on this.
5. Start a fresh `memory/MEMORY.md` index for the new season; carry
   forward only the truly cross-season lessons (the playbook, the PnL
   double-count fix, the import-path gotcha, MC ≠ server).

— Sourabh, May 2026
