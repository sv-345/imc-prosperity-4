# Round 1 — Leak Decomposition

Based on `ledger.csv` (890 fills) from submission `273632` (official profit **101,199.69** on 1 day × 10,000 ticks).

## Framing

Before counting leaks, it helps to understand the **ceiling**. Given the engine-enforced ±80 position cap that no submission can relax:

- **PEP** drifts +0.1/tick deterministically, moving mid by +1,001 over the session. The max drift capture at a constant +80 long is **80 × 1,001 = 80,080**. Any PEP strategy is competing for the residual edge beyond this.
- **OSM** mid only moved −6 net. Any OSM profit is from MM wedges (buying below mid, selling above). The theoretical ceiling depends on how much toxic flow you absorb vs. how much wedge you collect.

273632 booked PnL of `OSM 18,863` + `PEP 82,921` = `101,784` (MTM-based; 0.6 % above the 101,200 official — rounding / end-tick conventions).

## Summary of identified leaks (ranked by $ impact)

| # | leak | $ cost | % of pnl | confidence |
|---|---|---:|---:|---|
| 1 | PEP not fully saturated at +80 (sells to recycle + 202-tick ramp) | ~3,500 drift-gap  (offset by +6–7k of MM edge on recycling — see analysis) | ~3.5 % drift, fundamentally offset | high (path integral) |
| 2 | OSM MM quotes at edge=20 are too wide — catches the `11–20` tick layer only | ~2,000 implied from bot-bot distribution | ~2 % | medium (requires counterfactual replay) |
| 3 | Negative-edge aggressive takes paid 5,409 gross spread | −5,409 gross (offset by +2–3k directional pnl on same fills) | −2 to −5 % net | high (direct edge accounting) |
| 4 | End-of-session unrealized stuck at +80 PEP, +80 OSM — forced to MTM | see below — not a leak but a risk exposure | — | noted |
| 5 | Bot-bot trades at our own quote price (queue-priority loss) | ~300 at 50 % discount | 0.3 % | low (simulator routing unknown) |
| 6 | Wrong-side OSM fills (markout_50 < −20) | −497 | 0.5 % | high (direct count) |
| 7 | Wrong-side PEP fills (markout_50 < −20) | −156 | 0.15 % | high |
| 8 | Missed non-MM edges (momentum, arb, obs) | 0 identified; not obviously present | 0 | high (no cross-asset correlation > small wedges) |

**Net identifiable leak floor: ~8–11 k.** Most of it is structural (can't be fixed without changing engine rules).

---

## Leak 1 — PEP saturation gap

**Mechanism.** The strategy hits +80 at tick 202 (ts 20,200) and sits near-+80 for the rest of the session. Time-weighted average PEP inventory = **76.5** (not 80).

**Cost.** Drift capture at inv=76.5 × 1,001 ≈ **76,573**; at constant +80 would be 80,080. **Gap = 3,507**.

**Why we dip below 80.** The `_trade_pepper` function, when pos ≥ 70, flips to MM mode: it quotes a small (8-unit) sell at `max(ba−1, fv_int+7)`. When hit, inventory drops to 72–76, and the next tick's buy leg starts refilling. This recycles ~122 times per session, each round-trip earning ~6–8 ticks of MM edge (spread between sell and subsequent buy).

**Hindsight verdict.** The recycling pays for itself — total PEP MM edge contribution ≈ +6,365 (residual on top of drift), vs. the 3,507 drift given up. Net: recycling is slightly +ev.

**But there's a tighter variant.** If we only recycle when `bb − fv_int ≥ 8` (i.e., only when the inside spread gives a clear edge), we'd cut marginal recycles and tighten to +78 avg. Estimated recovery: **+1,500 to +2,500** (optimistic).

**Ramp leak.** The 202-tick ramp (inventory 0 → 80) costs ~800 in drift capture vs. instantaneous +80. Unavoidable without crossing the spread for the first 80 units (which costs ~4–6 ticks × 80 = 320–480 in crossing spread). Net wash.

---

## Leak 2 — OSM MM: edge=20 misses the 11–15 tick layer

**Observed distribution of all OSM trades (|price − 10001|):**

| distance | count |
|---|---:|
| 0 | 9 |
| 1–2 | 180 |
| 3–5 | 174 |
| 6–10 | 241 |
| 11–15 | 94 |
| 16–20 | 42 |
| >20 | 0 |

We quote at fv±20 (9981 / 10021) — the 42 trades in 16–20 bucket are a pure bonus we catch. But the **94 trades at 11–15** happen INSIDE our far edge, reachable only by the inner-layer quote at `min(bb+1, fv−1)` (typically 9999) which sits at 0–2 away. Nothing of ours is at 11–15.

**Cost.** If we placed a second passive layer at fv±12 (9989 / 10013) with size 15, and captured ~30 % of the 94 × 5 ≈ 470 qty at ~10 ticks of edge ≈ **+1,410 to +2,800** (depending on queue priority). Memory flags edge=12 as a historical plateau optimum.

**Caveat.** Requires re-running the MC / server-replay harness to confirm the fills actually land. Simulator routing means bot flow sometimes bypasses our quotes. Prior memory ("MC v2 overpredicts book-structure changes") warns that adding quote layers may not convert linearly on the real server.

---

## Leak 3 — Negative-edge aggressive takes cost 5,409 in direct spread

251 fills had edge_at_fill < 0 (mean edge −4.3). Σ (edge × size) = **−5,409**. These are fills where the strategy crossed the book to take (OSM `if vol <= 9 or real_edge >= 2:` and aggressive-buy logic in PEP).

**Is the cross worth it?** Markout+50 on these 251 fills is +18,500 net (they do move in our favor on the medium horizon). So the crosses pay off directionally — they are **not** a pure leak; they're paying for edge. But the 5,409 is lost to the market as transaction cost. If we had better entry timing (waited 10 ticks when possible), we'd recover some of that as passive edge instead of crossing.

**Estimated savings from avoiding crosses with weak signal:** ~1,000–2,000 (25–40 % of the 5,409). Not huge, and risks losing the directional edge entirely — this is a negative-carry optimization.

---

## Leak 4 — End-of-session open inventory

Final position: **OSM +80, PEP +78**. Unrealized MTM at end:

| product | end qty | end mid | avg cost basis | unrealized |
|---|---:|---:|---:|---:|
| OSM | +80 | 10,001 | ~9,994 | +547 |
| PEP | +78 | 13,999.5 | ~13,915 | +6,565 |

Being long OSM is a **coin-flip** since OSM mean-reverts. Being long PEP at +78 is **aligned with drift** and correct.

No explicit leak, but: with 200 ticks left, mid had moved farther away than it would recover. If we trimmed inventory earlier (ticks 9500–9800) we could have locked a higher exit. Potential: marginal (<500).

---

## Leak 5 — Bot-bot trades at our quote price (queue priority loss)

Of 300 bot-bot trades:
- 33 trades at a price where we had a quote on the same side (A_at)
- 2 trades where our quote was strictly inside (B_inside) — likely simulator routing quirk
- 265 trades at prices where we had no competitive quote

Σ |mid−price| × qty on A_at trades: **613** (OSM 441, PEP 172). Apply 50 % queue-priority discount: **~306**.

Low confidence — the simulator may not route taker flow to the best-priced quote (known IMC quirk: memory notes "MC v2 overpredicts book-structure changes"). The discount could be 0–100 %.

---

## Leak 6 — Wrong-side OSM fills (markout_50 < −20)

**13 fills, aggregate markout_50 = −497.**

These are BUY/SELL fills where mid moved ≥20/size against us in the next 50 ticks. Given OSM mean-reverts, these are either (a) bots taking us on breakout (rare) or (b) our bad timing on a cross.

Per-fill impact is small; not worth a dedicated filter.

---

## Leak 7 — Wrong-side PEP fills

**6 fills, −156.** Negligible. PEP drift is deterministic enough that PEP sizing rarely goes wrong.

---

## Leak 8 — Missed non-MM edges

Systematic check:
- **OSM/PEP correlation:** OSM mid std dev is ~5, PEP is monotone drift. No meaningful cross-asset signal.
- **Momentum:** PEP slope is already known a priori (+0.1/tick). Nothing to add from observation.
- **Observations (in `state.observations`):** 273632 does not consume observations. Round 1 had no observation stream (confirmed empty in logs).
- **Mean-reversion:** OSM already mean-reverts and our MM captures this.

**No identified miss.** Round 1 is, by design, a clean market-making round — there are no hidden arbitrages to find.

---

## Sensitivity — adverse-selection parameters

Redefinition for clarity: we use a stricter markout-based definition since path-based adverse flags are misleading for PEP (every PEP sell is "adverse" vs. an uptrending asset).

**Adverse-selected fills by markout < −10 (price moved ≥10/size against us):**

| window | count | aggregate markout |
|---|---:|---:|
| +10 ticks | 48 | −1,103 |
| +50 ticks | 23 | −654 |
| +200 ticks | 97 | −6,400 |

The +200-tick count is inflated by PEP SELL fills (PEP rises +1,001, so every PEP sell loses ~20 on 200-tick horizon). Filtering those out:

| product / side | +200 markout |
|---|---:|
| OSM BUY | +6,877 |
| OSM SELL | +9,950 |
| PEP BUY | +16,211 |
| PEP SELL | **−8,145** (structural — uptrend) |

The PEP SELL markout_200 leak is **structural to MM in an uptrending asset**. It's the price of recycling to stay at +80. The 8k is not a mistake — it's paid for by the 122 recycles × avg edge 7 × avg size 5 ≈ +4,270 realized MM edge. So PEP recycling is slightly net-negative on a 200-tick horizon, but net-positive on a 50-tick horizon (+1,391).

**Conclusion:** recycling is +ev only if we re-enter within ~100 ticks. If the market gaps up sharply between our sell and re-buy (rare), we lose.
