# Round 2 — Triangulation

Reconciling (1) ROUND2/knowledge/ community alpha, (2) docs/round1_postmortem/
own-trader retrospective, and (3) R2 iteration log docs/round2_submissions.md.
Goal: understand why the "ceiling ~$8,800" analysis was wrong and what edge
sources remain unapplied.

## 3.1 Per-tick calibration

| source | baseline | ticks | $/tick |
|---|---:|---:|---:|
| R1 official (v82_hardened, sub 273632) | 101,199 | 10,000 | **10.12** |
| R2 current best (iter10, 3 server runs) | 8,700 | 1,000 | **8.70** |
| R2 community — "OSMIUM can't get past 9k" (yoyopi768) | 9,000 | 1,000 | **9.00** OSM alone |
| R2 community — "top PEP players use non-hold strategies" | unknown | 1,000 | > 7 |

**Scoring window question**:
- R1 final scoring **ran 10,000 ticks** (official v82 ledger has ts 0..999,900 step 100 = 10,000 ticks).
- R2 testing submissions run **1,000 ticks** (ts 0..99,900 = 100× fewer).
- Community assumption (hariseldon, #algo-trading 2026-04-17 18:55): **"data becomes 10x in live round, like R1"** — not yet admin-confirmed but matches R1 structure.
- Admin (tomas5880): MAF bid mechanic "only applies to the final round (1m ticks)" — *final* is 1m ticks (equivalent to R1's 10k × 100 step).

**13k target reading**:
- If interpreted as *testing-submission* PnL on 1,000 ticks: **needs $13/tick**, which is 1.5× my current and 1.4× what v82 achieved on R1 final. Hard but not impossible (community claims OSM alone can hit $9/tick).
- If interpreted as *final-round* PnL at 10,000 ticks: **needs $1.3/tick**, trivially met.
- **Assume the harder target**: testing-submission $13/tick, since that's what the user has been evaluating against.

## 3.2 Edge-source inventory across both rounds

### R1 PnL decomposition (v82_hardened)
- PEP: **$82,921** (82%) — $76,560 pure drift capture + ~$6,360 MM recycling spread
- OSM: **$18,863** (19%) — $11k pure MM spread + $7.9k directional round-trip from wide-snipe `fv±20` layer + aggressive takes

### R2 iter10 decomposition (submission 295454 / 295615)
- PEP: **$7,400** (85%) — ~$7,360 pure drift capture (80 × $100 end drift − $560 sweep cost). **No MM recycling.**
- OSM: **$1,200** (15%) — ~$600 MM spread + ~$600 from adaptive-fair + take-crossings. **No wide-snipe layer.**

### Missing in R2 vs R1
1. **OSM fv±20 wide-snipe layer** — R1 catches 42 trades in `16–20 | mid-10001 |` band (roughly $20/trade wedge). On R2 1,000-tick slice → ~4 trades × $20 × 5 qty = **~$400 missed**.
2. **OSM aggressive take-below-fair** — R1 takes ANY ask below fv if `vol ≤ 9 OR real_edge ≥ 2`. My R2 take threshold is `fair-1`, much stricter. R1 did 251 such crosses → ~25 on R2 slice × ~$2 edge × 5 qty = **~$250 missed**.
3. **PEP recycling when long** — R1 sells 8 units at `(ba-1)` or `fv+7` when pos ≥ 70, earning $6-8 MM spread per recycle × ~12 recycles/slice = **~$700 missed**.
4. **PEP aggressive take-through-fair when accumulating** — R1 walks ALL asks up to `fv_int + 6` when pos < 70. My R2 only sweeps at the inner-ask price (`floor(fair)+8`). R1 captures full depth = **+$100–200 missed**.

Missing total: **~$1,500 / 1,000 ticks**. Would put me at ~$10.2k, still short of 13k.

## 3.3 Community claims that break the ceiling

| claim | source | invalidates which assumption | mechanism |
|---|---|---|---|
| "R2 data scales 10× in live round (like R1)" | hariseldon, #algo-trading 18:55 | My ceiling is relative to 1,000 ticks — final round may be 10,000 | Drift capture is position-limited; **MM spread scales linearly with tick count**. |
| "OSMIUM can't get past 9k" | yoyopi768 | My OSM ceiling of ~$1,400 | Someone is extracting $9/tick of OSM — ~7× my rate. Unknown what edge. |
| "Top performers on PEP use non-hold strategies" | stefanos | My PEP is "drift capture + ceiling hit" | There's PEP alpha beyond pure hold — likely recycling MM spread on top of drift (R1 does this). |
| "Hidden 20% quotes placed *after* your orders" | abhishek964 | My MC's fill-rate calibration | Adverse selection: my passive quotes get run over by hidden bot orders → wider spreads offset this. |
| "Backtester data is 80%-randomized per submission" | tomas5880 ADMIN | My iter10 re-submit variance is "noise" | It's randomized data, not bot behavior variance. Two MCs of same strategy give different numbers even in deterministic Rust sim — wait, only the live server randomizes (my MC is deterministic). |

## 3.4 R1 lessons not yet applied in R2

| R1 rec | applicable to R2? | applied? | est $/tick impact |
|---|---|---|---:|
| **R1-R1**: Tighten `_trade_osmium` `vol ≤ 9 OR real_edge ≥ 2` — skip weak crosses | Yes (same products) | N/A — R2 iter10 doesn't even have this aggressive-take logic | 0 (already conservative) |
| **R1-R2**: PEP fast ramp — cross ask for 8/tick for first 20 ticks | Yes | **Already applied** — iter8+ sweep at fair+8 | 0 (already done) |
| **R1-anti**: Do NOT add OSM fv±12 layer | Yes | N/A — no fv±12 layer | 0 |
| **R1-implicit**: OSM fv±20 wide snipe layer (part of v82 baseline) | Yes | **NOT applied** in R2 iter10 | +$0.3–0.5/tick |
| **R1-implicit**: PEP recycle when pos ≥ 70 (sell 8 at ba-1) | Yes | **NOT applied** in R2 iter10 | +$0.5–0.8/tick |
| **R1-implicit**: OSM aggressive take `vol ≤ 9 OR real_edge ≥ 2` | Yes | **NOT applied** in R2 iter10 | +$0.2–0.4/tick |

## 3.5 Contradiction: R1 ceiling was also conservative

The R1 post-mortem's "realistic recoverable $1–2.5k" = 1–2.5% of $101k base, which is tiny. That figure was computed by:
- Measuring identified leaks against a hindsight-replay of one day's data
- Applying a 30–60% discount for "ex-ante signal noise"

**What the R1 post-mortem did NOT do**:
- Compare v82_hardened's PnL to what *other* competing traders achieved. If top R1 scorers got more than $101k, v82 itself was sub-optimal and the "ceiling" was actually lower than the achievable max.
- The community notes "OSMIUM can't get past 9k" (yoyopi768) as a *reported ceiling*. R1 v82 did $18,863 on OSM (10× that). So the community OSMIUM ceiling is for a 1000-tick slice, and 10k scaling gives $9k/slice = $90k on 10k ticks — which is **substantially above v82's $18.8k**. Community top OSMIUM players beat v82 by 4–5×.

**Conclusion**: v82 was not at the R1 ceiling either. Both "ceilings" (R1 $105k, R2 $8.8k) were self-derived from a model that excluded competitor-benchmarking. Every future ceiling estimate in this codebase must be cross-checked against "what are other players actually doing?" before being asserted as maximum.

## 3.6 Ranked edge sources for R2

| # | edge source | R1 evidence | R2 community evidence | R2 applied? | est $/tick | complexity |
|---|---|---|---|---|---:|---|
| 1 | **OSM richer take + wide snipe** (v82-style `_trade_osmium`) | $18.8k (v82) vs $1.3k (my iter10) | "OSM ceiling is 9k" = $9/tick | NOT applied | **+$3–8/tick** | low (port code) |
| 2 | **PEP recycling when long** (v82 sells 8 at ba-1 when pos≥70) | $6.4k R1 recycling income | top PEP players "don't just hold" | NOT applied | **+$0.5–1/tick** | low |
| 3 | **PEP aggressive take through fair** (not just sweep at one price) | part of v82 _trade_pepper | — | partial | +$0.2/tick | low |
| 4 | **80% quote subset awareness** — widen spreads to offset adverse selection | not in R1 (R1 data was 80% too) | admin-confirmed | not directly | unclear | medium |
| 5 | **Multi-sample MC evaluation** (run MC 5× per hypothesis, use median) | — | "single backtest is noisy point estimate" | not done | indirect | low |

## Next step

Port the R1 v82_hardened OSM + PEP logic into R2 as iter12. The single
biggest expected impact is source #1 — OSM richer quoting. iter12 is not
"iter10 plus one change" — it's a full strategy port with the proven R1
structure, adapted only for imports and any R1-specific constants that
need R2 values. That's the minimum-viable way to test "is the $8.8k ceiling
wrong?" against real R1-proven edge sources.

Expected server result: PEP still ~$7.4k (ceiling hasn't moved), OSM jumps
to maybe $3–8k from the wider quoting + take logic. Total $10–15k. **If
this hits $13k, the ceiling was wrong by the gap between iter10's OSM
($1.3k) and v82's OSM scaled to 1k ticks (~$1.9k) plus the missing wide-
snipe & recycling income.**
