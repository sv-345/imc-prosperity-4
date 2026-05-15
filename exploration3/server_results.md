# Schedule-exploit server results — session 3 extension

## All submissions (2026-04-19)

| # | variant | backtest Δ (3-day) | server TOTAL | server OSM | server PEP |
|---|---------|-------------------:|-------------:|-----------:|-----------:|
| 1 | iter23 baseline (sample 1)         |       — |  $9,231.19 | 1,564.25 | 7,666.94 |
| 2 | iter23 baseline (sample 2)         |       — |  $9,514.50 | 1,908.25 | 7,606.25 |
| 3 | iter_candidate_sched_preempt       | −$1,082 | **$9,790.50** | 1,893.25 | 7,897.25 |
| 4 | iter_candidate_schedule (widen +2) | −$26,681 |  $7,958.50 |   369.25 | 7,589.25 |
| 5 | iter_cand_sched_sizeup             |      $0 |  $9,147.50 | 1,408.25 | 7,739.25 |
| 6 | iter_cand_sched_skip               | −$26,681 |  $8,082.50 |   631.25 | 7,451.25 |
| 7 | iter_cand_preempt_osmonly          | −$1,006 |  $9,205.50 | 1,734.25 | 7,471.25 |
| 8 | iter_cand_preempt_peponly          |    −$76 |  $9,667.50 | 1,862.25 | 7,805.25 |
| 9 | iter_cand_preempt_aggressive       | −$1,082 |  $9,501.00 | 1,845.25 | 7,655.75 |
|10 | iter_cand_preempt_noshrink         | −$1,082 |  $9,424.00 | 1,822.25 | 7,601.75 |
|11 | iter_cand_preempt_pos66 combo      |   −$472 |  $9,619.62 | 1,988.88 | 7,630.75 |

## Observed iter23 baseline variance

- Today sample 1: $9,231.19
- Today sample 2: $9,514.50
- Memory 5-sample historical mean: $9,641
- Today 2-sample mean: $9,372.85, std ≈ $200
- Cross-sample range of iter23 alone: $283 (today) / $410 (including memory mean)

Each server submission is run against a fresh 80% random subset of the
master tape — single-sample deltas are noisy with σ ≈ $135-200.

## Classification by effect size

### Clearly regressing (Δ ≤ −$1,000 vs mean iter23)

| variant | server TOTAL | Δ vs today-2-sample mean $9,372 |
|---------|-------------:|-------------------------------:|
| widen +2 | $7,958.50 | −$1,414 |
| skip    | $8,082.50 | −$1,290 |

**Conclusion**: Widening our quote to fv+9 on scheduled ticks (or
skipping the quote entirely) is a ~$1.3k regression per session.
Consistent with backtest direction. Not submittable as production.

### Noise-level (Δ within ±$300 of iter23 mean)

| variant | server TOTAL |
|---------|-------------:|
| sizeup  | $9,147.50 |
| preempt OSM-only | $9,205.50 |
| preempt PEP-only | $9,667.50 |
| preempt aggressive | $9,501.00 |
| preempt noshrink | $9,424.00 |
| preempt pos66 combo | $9,619.62 |
| **preempt (original)** | **$9,790.50** |

These variants cluster in a ~$580 band ($9,205 to $9,790) which is
within ~3× the single-sample iter23 σ. **Cannot reliably distinguish
any of them from iter23 on 1 sample each.**

The original preempt result at $9,790.50 is $418 above today's
2-sample iter23 mean — about 2σ. Suggestive but not decisive on n=1.
Would need ≥3 samples of preempt to confirm.

## What the experiment established

**Positive findings**:
1. The deterministic schedule IS present on the live server — the fact
   that our schedule lookup doesn't crash and produces consistent
   behavior across 9 schedule-aware submissions confirms the
   timestamp-based seeding from training data transfers.
2. Widening and skipping quotes on scheduled ticks clearly hurts — the
   backtest warning transfers to the server with similar magnitude
   (backtest −$26k scaled down to server 1000-tick = roughly −$2.7k
   predicted, observed −$1.3k).

**Inconclusive findings**:
3. Preempt-style defensive widening on the tick BEFORE a scheduled
   taker averages around iter23 baseline with individual samples
   spread ±$400. The original preempt got lucky to hit +$418 vs mean
   on its sample. Multi-sample confirmation would be needed to treat
   it as real alpha.
4. Pos<66 PEP recycle threshold (session-3 marginal finding) combined
   with preempt gave $9,620 — also within noise of iter23 mean.

**Negative findings**:
5. No combination of schedule-widening, schedule-skipping, or
   schedule-sizing yielded a clear server win. The schedule is
   observable but **not cleanly exploitable via MM quote placement**
   on the live 1000-tick server sessions either.

## Per-variant mechanism summary

| variant | mechanism | verdict |
|---------|-----------|---------|
| widen +2 | On scheduled tick, additive ask_pj += 2 (posts at fv+9 instead of fv+7) | **REGRESSES** — ties with wall, loses queue priority, 0 fills |
| skip | On scheduled adverse-direction tick, withdraw inner quote entirely | **REGRESSES** — misses fills, same outcome as widen |
| sizeup | On aligned scheduled tick, increase quote size at normal price | Noise-level flat |
| preempt (orig) | 1 tick BEFORE scheduled event, trigger iter22's defend mechanism | Best sample result, noise-inseparable on n=1 |
| preempt OSM-only | Same, OSM schedule only | Slight regression |
| preempt PEP-only | Same, PEP schedule only | Noise-flat |
| preempt aggressive | Same + bigger ADVERSE_WIDEN/SHRINK | Noise-flat |
| preempt noshrink | Same without sell-cap shrink | Noise-flat |
| preempt pos66 combo | Preempt + PEP recycle at pos<66 | Noise-flat |

## Recommendation

**Do NOT ship any of these variants as a primary submission.** iter23
baseline remains the reliable production. Preempt is the best candidate
for further validation, but requires ≥3-sample confirmation before
declaring an uplift.

The honest finding from session 3 (deterministic taker schedule exists,
but not exploitable via MM) is now confirmed on server. The community's
"20% bot-behavior alpha" claim does not appear to live in quote-placement
responses to the schedule.

Possible remaining avenues (not tested here, not clear how to test):
- A trader that SWITCHES MODES (e.g., pure-taker) at scheduled ticks
- Position sizing that reduces exposure BEFORE adverse-direction
  scheduled ticks (similar to preempt but applied to fast-accumulate
  phase, not recycle quoting)
- Cross-tick-interval features (multi-tick lookahead in the schedule)

## Submission IDs for audit

| # | submission id | variant |
|---|--------------:|---------|
| 1 | 303257 | iter23 baseline (sample 1) |
| 2 | 303280 | iter23 baseline (sample 2) |
| 3 | 302898 | preempt (original) |
| 4 | 303018 | widen +2 |
| 5 | 303039 | sizeup |
| 6 | 303068 | skip |
| 7 | 303102 | preempt OSM-only |
| 8 | 303126 | preempt PEP-only |
| 9 | 303162 | preempt aggressive |
|10 | 303218 | preempt noshrink |
|11 | 303241 | preempt pos66 combo |
