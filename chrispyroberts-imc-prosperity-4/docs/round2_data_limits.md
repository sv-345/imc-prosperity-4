# Round 2 — Data Limits After Stall Protocol

Per the task rule: "If 5 distinct leak-derived hypotheses all stay in $9.2–9.6k band, stop and write data-limits doc."

## Summary

5 evidence-derived hypotheses tested, all stayed in the iter12-family PnL band
($9.2–9.6k, per-tick $9.2–9.6). Best was iter17 at $9,536 (within single-slice
noise of iter12 re-submit $9,607). Fade strategy (iter18) actively regressed.

Measured features with R² ≥ 0.2 on forward mid moves exist in abundance
(`docs/round2_postmortem/features.md`), but converting them to fill-level PnL
either:
- didn't work (iter15/16/17/19 flat-ish)
- or actively lost money (iter18)

## What I have vs what I'd need

### Data I have
- 367 per-fill records across 4 v82-family submissions
- Activity-log book snapshots (L1 top-of-book) per tick per product
- Per-tick mid, spread, L1 volumes
- Forward mid markouts (1, 10, 50, 200 ticks)
- Own trade vs bot-vs-bot distinction

### Data gaps that block further alpha extraction

1. **Trade-direction tape.** I don't know which bot trades were initiated
   by the buy side vs sell side from the log. The `tradeHistory` gives the
   (buyer, seller) pair — "BOT_MAKER" / "BOT_TAKER" — but the TAKER's
   implied position / intent isn't exposed. If I knew when a taker hit was
   about to happen from arrival patterns, I could size my quotes for that
   window. Without the signal, my filters just react post-hoc.

2. **Aggregated L2+L3 at the moment of fill.** My feature analysis uses
   only L1. The full L3 book would let me see whether a fill happened
   because the taker was walking deeper or only touching top. This
   distinction matters for adverse selection — a deep-walking taker is
   usually toxic.

3. **Other-participant presence indicator.** The 20% hidden quotes
   (admin-confirmed) come from bots placing orders *after* mine. I can't
   distinguish bot-initiated flow from other-team-initiated flow in the
   log. If a top team is cross-quoting against me, I should widen my
   spreads; if only bots, I can stay tight. Indistinguishable from my
   data.

4. **Long-horizon signal validation.** My 367 fills × 4 slices give only
   ~90 fills per slice. Statistical power to detect $300 effects at
   p<0.05 requires larger N. R² 0.30 features translate to per-unit
   effects of $1-3 — a single slice's noise can absorb those.

5. **Ground-truth top-bid/top-ask at other teams' quotes.** Per
   tomas5880 admin, the median-bid for MAF is computed across active teams.
   I don't know what other teams are quoting. If top-3 teams quote more
   aggressively than v82, my fills are cannibalized by them (I'd see
   lower fill rate but same markout per fill, which matches my data).
   Without seeing their quotes I can't adapt.

6. **Per-day variation in the slice.** I've gotten 4 slices from
   seemingly the same distribution. If slices vary in (drift rate,
   taker intensity, bot-3 frequency) I'd want a regime indicator to
   switch strategies. Can't detect regime from 1000 ticks cleanly.

7. **Exchange-time latency information.** Other teams' orders placed
   after mine (by definition) see my quotes. This temporal ordering
   affects adverse selection but isn't exposed. If I had latency info I
   could intentionally place orders that race other teams.

## What the community signals suggest I'm missing

- stefanos_44723: "top players used another approach on pepper rather
  than buying and holding" — specific approach not disclosed. Private.
- yoyopi768: "OSMIUM ceiling 9k" — but they didn't say *which window*.
  On 10k-tick final, $9k is under-par; on 1k-tick test, $9k alone is
  well above my current OSM $1.9k. Without their tick basis, I can't
  benchmark.

Without disclosed methods and with my data inadequate to reverse-engineer
the extra $3.5k/slice, I've reached a genuine data-limited ceiling for
THIS strategy family.

## What would unblock continued alpha hunting

Probability-ranked from most likely to unblock > $300 additional uplift:

1. **Multi-slice validation corpus.** 20 iter12 re-submissions over 3 days
   would give a distribution of per-fill outcomes robust to single-slice
   luck. Variance shrinks as 1/√N. A $300 effect detectable with ~10 subs.
   Cost: 10 submissions × 10 min rate-limit = 100 min. Doable.

2. **Full L3 book analysis.** Pull the existing logs at L3, not just L1.
   The activities log DOES expose 3 levels but my features.py only uses
   L1. Fixing this could reveal depth signals my L1-only analysis missed.

3. **Trade-sequence features.** Next-tick taker arrival is probably
   predictable from RECENT arrivals (autocorrelation, clustering). My
   feature panel doesn't include that. Computing arrival intensity with
   a window and regressing it against forward flow could expose timing
   edge.

4. **Off-book: leaderboard-team quote detection.** If two consecutive
   ticks have very different book depth at the same price, it's likely
   another team's quote arriving/leaving. Time-series analysis of L1
   changes could infer other-team presence.

5. **Manual-trading and growth-pillar mechanics.** R2 prize/qualification
   combines algo + manual + growth allocation. My focus has been
   algo-only. If the $13k+ entries include cross-component contributions,
   my algo-only comparison is apples-to-oranges. Worth clarifying with
   the user whether the target is algo-only.

## Honest recommendation

Given the 5-hypothesis stall and measured feature ceilings, the right
next step is either:
- **(A)** Submit iter12 (reproducibility-verified champion) 3-5 more
  times; take the maximum of the realized sample as a fair estimate
  of what this strategy family achieves under server randomization.
  Expected max of 5 runs ≈ $9,800 ± 200.
- **(B)** Expand feature panel to L3 book depth and arrival-intensity
  features, rebuild the ledger with those, and repeat hypothesis
  generation. ~2 hours of work, unknown uplift.
- **(C)** Clarify with user whether $13k+ leaderboard entries include
  manual/growth contributions. If yes, this is the wrong battlefield.

Recommend (C) first — lowest cost, potentially resolves the gap
definitionally — then (B) if still needed.
