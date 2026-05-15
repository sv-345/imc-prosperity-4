# Hidden $500+ single-tick alpha investigation — HONEST NULL

User hint: "there is some hidden alpha that gives 500+ pnl in one tick, you need to think outside the box to find it in the data, visualizing it and looking at the chart will help you immensely"

## Investigation outcome: I could not find a mechanism that reliably produces $500+ in one tick via modifications to iter23's framework.

## What I checked

### 1. Single-tick PnL deltas in existing server samples (cumulative OSM+PEP)

Across 5 samples (iter23 best, iter23 worst, tb1, iter26 best, iter26 worst):
- Max single-tick Δ: **$185** (iter26 worst sample at ts=90300)
- Distribution: mean ~$9-10/tick, σ small
- Count of ticks with Δ≥200: **0**
- Count of ticks with Δ≥500: **0**

Our strategies do NOT produce $500+ single-tick events.

### 2. Trade history — biggest single fills

- Max fill qty: 12 (PEP BUY at ts=3400 px=13010)
- Most fills are 6-10 qty OSM, 3-12 PEP
- Max trade edge (vs rolling mid): $12 (OSM)
- Max potential (edge × qty): $120 single fill

Single fills cannot produce $500 edge.

### 3. Training-data dislocations

Scanned all 3 days for trades far from rolling mid:
- OSM: 0 trades at >$5 edge (beyond normal wall prices) across all 3 days
- PEP: 7 ask-dislocations on day 1 with potential $16-44 each

Training data has no extreme dislocations that would provide $500+ in one tick.

### 4. One-sided book phantom events

Mid appears to jump ±5-13 when one side of the book is missing (phantom mid uses the one visible side):
- ~177 "big jumps" per day on OSM
- Most are phantom (mid returns within 1 tick)
- Server's profit_and_loss column does NOT use phantom mid for accounting (verified by inspecting actual cumulative PnL around these events)

My initial analysis using `mid_price` × position gave false $1,461 single-tick "deltas" — these were ARTIFACTS of phantom mids and DO NOT appear in real PnL.

### 5. Tested candidate variants

| variant | Δ vs iter23 |
|---------|------------:|
| iter26_c4_best (previous validated) | +$3,065 |
| iter27_ladder (post multiple mid-range asks/bids) | **−$16,499** ← big regression |

Ladder strategy fails: adverse fills at mid-range prices swamp any sweeper wins.

## What I consider exhausted

- MM quote placement modifications (tb1 + c4_best captured)
- Take-gate variations (Rule 2 falsified, c4 position-conditional works)
- Ladder quotes (fails)
- Size boost during regime (no effect — taker qty binds)
- Middle layer at mid±3 (marginal +$17)

## What I cannot rule out

The user's "$500+ in one tick" hint may refer to:

1. **A mechanism I don't have access to detect from iter23 samples.** If the leaderboard's strategy TRIGGERS $500+ events by structuring their own orders in specific ways, our sample logs wouldn't show the pre-trigger structure.

2. **Conversions or observations for some R2-specific product.** The backtester's runner.py references MAGNIFICENT_MACARONS conversion observations — not in R2. But maybe there's a hidden observation mechanism I'm missing. Iter23's `bid()` returns a constant 15; maybe dynamic bid strategy unlocks different data.

3. **Loose interpretation of "one tick".** My 7K-ts window analysis (70-tick window) DOES show $1000+ gains regularly:
   - iter23 best 7K-ts window: $1,361
   - tb1 best 7K-ts window: $1,495
   - iter26 best 7K-ts window: $1,310
   These are the "step-ups" the user pointed to earlier. They exist in ALL strategies — not unique to leaderboard. If "one tick" means "one chart-tick" on a 100-tick-per-chart-point plot, then these 7K-ts gains ARE the $1000 jumps.

4. **Lucky sample.** The leaderboard's $12,137 may be an unusually lucky single sample. Iter23 σ ≈ $135. 2σ events ± $270. 3σ events ± $405. Leaderboard at $12,137 vs iter23 mean $9,285 is **~21σ above iter23 mean** — that's effectively impossible as a lucky single sample unless their TRUE mean is genuinely higher.

## Likely explanation

Given the 21σ gap, the leaderboard has a genuinely-higher mean strategy. But the "per-tick" framing is misleading — the alpha is DISTRIBUTED across the session with concentrations at specific moments (which look like step-ups on the chart). Not a single $500 tick event.

If I had to speculate on a concrete mechanism I haven't tested:
- **More aggressive fast-accumulate on PEP** (push pos to +80 earlier, capture more drift)
- **Better timing of OSM short/long cycle** (predict when mid reverts and size in)
- **Use observations or bid mechanic** if R2 has undiscovered features

But these are guesses — no data-driven proof.

## Recommendation

**iter26_c4_best remains the validated candidate.** The $500+ one-tick hidden alpha claim is not reproducible in our data. I recommend:

1. Route iter26_c4_best through framework as previously validated (+$261/session server mean).
2. If the user has specific info about the mechanism, share it directly — I've exhausted my analytical angles without finding it.

## Artifacts

- `real_big_ticks.py` — verified single-tick deltas (max $185)
- `hunt_dislocations.py` — scanned training data for extreme events
- `compare_best_vs_worst.py` — iter26 sample variance analysis
- `viz_osm_trades.html` — trade dots colored by offset-from-rolling-mid
- `viz_iter26_best.html` — mid + pos + cumulative PnL trajectory
- `iter27_ladder.py` — failed variant (−$16k regression)

## Failed hypotheses summary (for future-proofing)

| hypothesis | result |
|------------|--------|
| Single-fill trades give $500 edge | NO — max $12 edge, max $120 single fill |
| Training data has $500+ dislocations | NO — max potential $44/event |
| Position × mid-jump produces $500 MTM | NO — server ignores phantom mid in PnL |
| Ladder quotes catch sweepers for $500+ | NO — backtest −$16k |
| Size boost in sustained regimes | NO — taker qty is binding constraint |
| Outer edge dynamic anchor | NO — negligible |
| Middle layer at mid±3 | marginal +$17 only |
| Observation-based or conversion alpha | NOT APPLICABLE — no observations/conversions in R2 |
