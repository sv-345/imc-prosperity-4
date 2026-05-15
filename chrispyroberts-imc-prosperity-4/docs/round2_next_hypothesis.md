# Next Hypothesis (iter 12)

## Hypothesis

Port the R1 v82_hardened trader to R2 verbatim (only the import is adjusted
for the server). v82 earned $18.8 k on OSM in R1 via three structures my
iter10 doesn't have — aggressive cross-the-book taking (251 fills with
`vol ≤ 9 OR real_edge ≥ 2`), a wide-snipe layer at fv±20, and deep passive
inside quotes at `bb+1` — each of which is documented and reproducible from
R1 ledger data (docs/round1_postmortem/ledger.md).

The R1 v82 OSM model translates to R2 if OSM's fundamental structure is
unchanged (same fv=10001 static, same inner/wall bot quotes). Community
evidence confirms same products / same behavior. If the model ports cleanly,
iter12 should extract ~$1.8 k OSM on a 1000-tick slice (v82 achieved
$18.8 k / 10,000 ticks = $1.88/tick; at 1,000 ticks, ~$1.88 k) plus the
existing $7.4 k PEP drift capture = **~$9.2 k total as a baseline**, with
potential for more from wide-snipe and aggressive-take fills that scale
differently than linearly.

## Which ceiling assumption this breaks

My "$8.8 k ceiling" analysis assumed OSM is bounded at ~$1.4 k via the
`edge=1 inside inner` MM strategy. That bound ignored:

1. The **fv±20 wide-snipe** layer (caught 42 trades in the 16–20 band on R1).
2. **Aggressive take** of asks below fv with minimal edge (251 R1 fills,
   ~$1.4 k edge income net of spread paid).
3. The `bb+1` inside quoting (R1 used this alongside edge=20, capturing both
   bands of flow simultaneously).

Community evidence (yoyopi768: "OSM 9k ceiling") implies there's still
room beyond v82's $1.88/tick — up to potentially $9/tick. Porting v82 is
the first step; optimising beyond v82's OSM performance is a follow-up
iteration.

## Expected $/tick

- PEP: $7.4/tick (unchanged — already near hard max on drift capture)
- OSM: $1.5–3/tick (port v82 structure, gain from missing layers)
- **Total target: $9–10/tick = $9–10k on 1000-tick slice**

13k requires a further push on OSM toward community's reported $9/tick —
that's iter 13+ work. Iter 12's role is to close the gap between iter10
and v82's documented R1 performance.

## Minimum viable implementation

Create `iter12_trader.py` as a port of `ROUND_1/R1Final/273632/273632.py`:

1. Copy the entire v82_hardened file.
2. Change imports to `from datamodel import ...` only (drop the
   prosperity3bt fallback chain).
3. Remove or stub the `Logger` class — it adds print overhead the R2
   server doesn't need (and `logger.flush` was reported to slow other
   teams' submissions in community chat).
4. Confirm LIMITS, OSM_FV, PEP_SLOPE constants match R2 calibration
   (they do — docs/round2_model.md has fv=10001, slope=0.10).
5. No other changes. The "change" is structural replacement, not a tweak.

## Pre-submission gates

- **MC per-tick ≥ $3.20/tick** (iter10 baseline): v82's richer OSM logic
  should match or beat my current OSM MC. If MC drops > 20%, something
  broke in the port (e.g. PEP fv-intercept detector misfires in MC).
- **P05 ≥ 0** on --heavy sweep.
- **Std / Mean ≤ 1.0** — v82's logic has been validated on 3 R1 training
  days with tight variance.
- **Sensitivity is not meaningful for a structural port** — the parameters
  are v82's proven values. Skip the ±20% sweep for iter12 and rely on R1
  production evidence.

## What this does NOT do

- Does not attempt to beat v82. Iter12 is the minimum viable structural
  port. Iter13+ will tune beyond v82 if needed.
- Does not address hidden-quote adverse selection (task 3.3). That's a
  follow-up if iter12 underperforms MC significantly.
- Does not apply the R1 post-mortem's CF3 "tighten weak OSM crosses"
  rec. We want to verify v82's RAW behavior first, then optionally apply
  CF3 as iter13.
