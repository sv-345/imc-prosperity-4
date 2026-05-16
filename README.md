# IMC Prosperity 4 — Season Retrospective

**Season:** Spring 2026 (Prosperity 4), all five rounds completed.
**Final placement:** 152nd overall.
**Author:** Sourabh Velaga.

This document records the methodology, results, and validated negative
results from the season. It is intended as a reference for future
participants entering Prosperity, and as a starting point for any
follow-up work on the same repository.

Substantive per-round content lives in the corresponding
`round*/README.md`. This file covers cross-round material: the overall
results, the methodology that generalised, and the dead-ends that
recurred.

---

## Repository layout

```text
tutorial/                 Tutorial round (EMERALDS, TOMATOES)
round1/                   OSMIUM + PEPPER market-making
round2/                   OSMIUM + PEPPER continued
round3/                   HYDROGEL + VELVET + 10 VEV vouchers
round4/                   Same products plus counterparty disclosure
round5/                   50 products / 10 families

shared/
  backtesters/
    prosperity3bt-fork/             R1-era Python backtester (community fork)
    prosperity_rust_backtester/     R3+ Rust simulator (10–100× faster)
  reference/
    chrispyroberts-imc-prosperity-4/ Top-finisher's open-sourced code

archive/                  Multi-agent scaffolding used during R2
```

Each `round*/README.md` is the canonical writeup for that round.
Strategy files are under `round*/strategies/` or as `trader*.py`. The
calibrated Monte Carlo backtester for Round 1 is under `round1/mc/`;
its docstrings should be read before reimplementing.

---

## Headline results

End-of-round scored submissions; all server runs are 1 day × 1,000 ticks
unless noted. The `.log` / `.json` / `.py` for each are preserved
alongside the strategy file.

| Round    | Submission                                          | Strategy               | Server PnL   | Headline driver                                                  |
| -------- | --------------------------------------------------- | ---------------------- | -----------: | ---------------------------------------------------------------- |
| Tutorial | `tutorial/trader.py` (v14)                          | EMERALDS / TOMATOES MM |      $2,757  | MC overpredicted ~6×; server is authoritative.                   |
| R1       | `round1/strategies/244644.py`                       | v82_hardened           |    **$10,859** | PEPPER drift carried (~70%); OSM MM the rest.                   |
| R2       | `round2/submissions/342122.py`                      | iter23                 |     **$9,268** | PEPPER drift again (~79%); OSM MM net of adverse-selection widen.|
| R3       | `round3/463514.py`                                  | v86 wing-bid           |   **$41,556** | HYDROGEL anchor-relative take ($21.7k) + voucher delta-1 MM ($17.2k).|
| R4       | `round4/submission/532407.py`                       | nN33_voucher_imb_skip  |   **$67,193** | Counterparty signals (Mark 67 prophet, Mark 14 maker-mirror) on vouchers ($58k).|
| R5       | sub 570453 (not preserved)                          | mixed cluster output   |  not durable | Strategies failed multiple-comparisons correction.                |

Earlier in R1, sub 273632 (also v82_hardened) reportedly scored $101,199
on a 10,000-tick run — the headline number circulated during the season.
The R1 preserved log here is the 1,000-tick scoring run that ranked the
final submission and is directly comparable to R2–R4. The 10× ratio
matches the tick-count ratio; do not use R1's $101k number to set
expectations for other rounds.

Round-over-round, the products and edges shifted:

- **R1 → R2:** same products, same edge mix. PEPPER drift is the
  dominant durable signal in both.
- **R2 → R3:** product universe changes entirely. Anchor-relative take
  on HYDROGEL becomes the largest single contributor.
- **R3 → R4:** counterparty disclosure unlocks ~3× the voucher PnL
  ($17k → $58k) by routing through Mark 67's directional prints and
  mirroring Mark 14's maker queue. HYDROGEL anchor-take simultaneously
  collapses ($21.7k → $1.4k) — the same anchor edge that worked in R3
  does not survive the R4 counterparty regime.

---

## Backtesting and submission

**Per-round backtesters:**

- **R1:** `round1/mc/` is calibrated to Spearman ρ = 1.0 against the
  live server across four submissions. Entry point:
  `mc/server_book_replay.py::run_server_session`.
- **R2:** `shared/backtesters/prosperity3bt-fork/`. The two-stage
  per-tick matching is material to results; see `NOTES_FORK.md` in
  that directory.
- **R3 / R4:** `shared/backtesters/prosperity_rust_backtester/`,
  10–100× faster than the Python equivalent and required for
  parameter sweeps. R4 additionally bundles a self-contained
  `prosperity3bt` under `round4/backtester/` with round data baked
  into `prosperity3bt/resources/round{0..8}/`.
- **R5:** no backtester preserved. A queue-aware passive-fill harness
  is a prerequisite for further work — most R5 microstructure signals
  did not survive aggressive-fill assumptions.

**Submission:** the live server only accepts `from datamodel import …`.
The form `from prosperity3bt.datamodel import …` is rejected at upload
(R2 submission 296164 failed with `ERROR_FINISHED` for this reason).
Imports must be rewritten before submission.

---

## Methodology (validated across R1 and R2)

The procedure below produced Spearman ρ = 1.0 rank preservation between
the local Monte Carlo and the live server across four R1 submissions.
A more detailed version is in `round1/README.md` §4.

1. **Hint extraction (≤ 0.5 day).** Read every README and inline
   comment in the Prosperity repository as shipped by IMC. Time-box
   this; approximately 60% of the output is superseded by step 2.
2. **Data-first statistical profile (1–2 days).** For each product,
   characterise: fair-value process (σ per tick, drift, quantisation),
   bot quote archetypes (wall / inner / near-mid), and taker flow
   (Bernoulli rate, quantity distribution, side split). Constraint:
   every parameter in the simulator must trace to a measurement
   produced in this step.
3. **Three-level Monte Carlo validation (1–2 days).**
   (a) Book replay against recorded server books.
   (b) Rank preservation across at least three prior submissions;
       Spearman ρ ≥ 0.9 required to pass.
   (c) Parameter-sensitivity sweep; accept plateaus, reject peaks.
4. **Distributionally robust optimisation (1 day).** Construct an
   uncertainty set Ξ of approximately six scenarios and grid-search
   θ × Ξ × seeds. Prefer the DRO-optimal parameter over the EV-optimal
   parameter unless the EV gap exceeds 10% *and* the minimum-scenario
   gap is under 5%.

### PnL double-count

A backtester accounting bug affected every round prior to detection.
If per-tick mark-to-market is combined with a final position
mark-to-market at simulation end, the closing position is
double-counted. The correction: track cash flows only during
simulation and compute `PnL = cash + position × final_FV` once at the
end. In R1, the uncorrected accounting added approximately +8,000
phantom PnL on PEPPER.

---

## What worked, by round

Synthesised from each round's final-submission log; full attribution in
each `round*/README.md`.

- **R1 / R2 — PEPPER drift via MM shell.** Drift FV (`day_start +
  0.10 × tick`) plus directional autocorrelation (ρ = 0.85) makes a
  passive market-making shell a long-vol exposure to the drift. Two
  consecutive rounds: PEPPER contributed $7,580 and $7,323 respectively
  — the most durable single edge in the season.
- **R3 — HYDROGEL anchor-relative take.** When `bb ≥ anchor + edge`,
  sell into the elevated bot bid; symmetric on buy. Contributed $21,685
  on a $41,556 total. The mechanism is the IMC end-of-session anchor
  mark, not last-trade mid; convergence accrues to anyone selling above
  or buying below anchor.
- **R3 / R4 — VEV delta-1 market-making on near-the-money strikes.**
  VEV_5000 through VEV_5400 produced reliable $4–11k per strike across
  both rounds. The 5500 / 6000 / 6500 wings produced zero.
- **R4 — counterparty mirroring.** Three signals carried the round:
  (1) Mark 67 as a directional prophet (95.4% H = 1 hit rate on VELVET
  and vouchers); (2) Mark 14 as a queue-position reference for
  delta-1 MM ("be like Mark 14 — proven +$7,248 in backtest vs `bb + 1`");
  (3) Mark 22 sell anticipation for cross-bias on adjacent strikes.
  Voucher PnL tripled vs R3 ($17k → $58k).

## What failed

- **R3 wing-voucher bid-at-0** (VEV_5500 / 6000 / 6500): the asymmetric
  thesis — "long at bid = 0 has positive expectation regardless of
  underlying" — produced zero PnL on the server. The bids never filled
  on any of the three wings. Costless to maintain, but the edge in
  `wing_voucher_architecture.md` is not realisable.
- **R3 → R4 HYDROGEL collapse.** The anchor-relative take that drove
  $21.7k in R3 produced $1,445 in R4 against the same configuration.
  Trade tape shows 200 HYDROGEL sells with 0 buys against Mark 01 /
  Mark 14 / Mark 38 — the anchor edge gets one-sidedly run over once
  counterparties are disclosed. The R4 trader did not adapt the
  HYDROGEL take logic to the new regime.
- **OSM market-making** (R2): produced $1,945 vs $3,279 in R1. The
  defensive widen and signal-gated PEP recycle added in iter23 protected
  PEPPER but cost OSM about a third of its R1 contribution. Adverse-
  selection filters generalise across products less well than expected.

## Validated negative results

Each of the items below was investigated, implemented, and shown to be
unprofitable or actively harmful on the server. The corresponding
per-round README contains the full mechanism analysis.

- **Hidden-FV / wall-FV alpha** (R1 v17): −$204 on server. MC
  overstates the edge because bot queue behaviour is more stable in
  simulation than in production.
- **Buy-and-hold any single product** (Tutorial through R3): drift is
  present but is dominated by spread and timing costs for
  market-making strategies.
- **L1 book-imbalance signals routed into take-logic** (R2
  exploration3): statistically significant in feature space,
  regressive in PnL space. The pattern repeats across feature
  variants; the same signals tend to be usable on the make side.
- **Dynamic OSM fair-value gate** (R2 iter24): −$829/day relative to a
  static FV of 10001. The only dynamic-gate variant that survived
  validation is `iter26_c4_best`, which uses a dual-condition trigger.
- **PEBBLES basket arbitrage** (R5 A1): the identity `sum = 50,000 ± 3`
  holds, but the 5-leg round-trip spread (~30) substantially exceeds
  the tradable deviation (~10). Usable as a sanity filter only.
- **Wall-aware OSM quoting** (R1 v15): −$161 on server. Walls are
  noisier than they appear in MC.
- **Per-counterparty profiling on `buyer` / `seller` fields** (R5):
  these fields were null until R4 populated them. Field population
  should be verified before any counterparty-based strategy is
  designed.
- **MICROCHIP_SQUARE spread mean-reversion** (R5 A8): IC = −0.22 is
  real, but the spread is the cost. Same failure mode as SNACKPACK
  aggressive.
- **`micro_PEBBLES_XL_RV200`** (R5): out-of-sample day-4 PnL of
  −$27,696, maximum drawdown −$45,071, top-1% PnL concentration 60%.
  In-sample performance was not representative.

---

## Round 5 — caveats on the multi-agent approach

Round 5 used a seven-sub-agent topology (visualisation /
single-product microstructure / cointegration / anonymous order-flow /
red team / passive-fill harness / manual puzzle). The execution was
clean and the cluster met its deadlines, but the resulting strategies
were not durable.

Three failure modes, documented in detail in `round5/README.md`:

1. **Multiple comparisons.** Candidate universe of 1,225 pairs
   implied a Bonferroni threshold of `p < 4.08e-5`. Smallest observed
   p was 0.00144. Selection was performed on relative walk-forward
   Sharpe, not on statistical proof of edge.
2. **Parameter instability.** GSD/TSG cointegration β flipped sign on
   day 2; full-sample β moved from −0.65 to +0.19. If cointegration is
   reused, β should be refit daily and sign flips treated as kill
   signals.
3. **Tick-cluster concentration.** All four deployed pairs had top-5%
   PnL share above 60%. A single adverse cluster is sufficient to
   wipe the strategy; drawdown stops are required.

The sub-agent topology itself is reusable. The selection criterion
(walk-forward Sharpe ranking) is not.

---

## Recommended sequence for next season

1. Read `round{N}/README.md` for the round being entered. Round
   numbers reset between seasons but product mechanics often recur.
2. Verify the cash-flow accounting fix on whichever backtester is
   being used as the starting point. `round1/mc/` is the cleanest
   reference implementation.
3. Execute phases 1 and 2 of the methodology (hint extraction and
   data-first profile) before any alpha search. The cost of skipping
   them is consistently higher than the time saved.
4. For any microstructural signal, determine whether it survives
   aggressive fills before deployment. If it requires passive fills,
   build the harness first.
5. Do not rely on Monte Carlo numbers without rank-preservation
   evidence against the server. R1's ρ = 1.0 was earned across four
   submissions, not assumed.

— Sourabh, May 2026
