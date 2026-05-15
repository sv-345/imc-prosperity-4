# Round 1 — Counterfactuals for Top 3 Leaks

All numbers are **hindsight-optimal** replays against official R1 data (submission 273632). Real submission improvement will be lower — simulator quirks, path dependence, and lack of perfect foresight all bite. Expect ~30–50 % of hindsight $ to translate to real gains.

Replay script: `scripts/postmortems/round1/counterfactuals.py`.

## CF3 (largest): skip OSM negative-edge crosses with weak markout ⇒ **+3,538**

**Leak.** 251 of our 610 OSM fills had edge_at_fill < 0 (we crossed the book). Of those, **140 had markout+50 ≤ +5** — meaning 50 ticks later the price hadn't meaningfully moved in our favor. These 140 fills cost us:
- Cross cost (direct spread paid): **−2,467.5**
- Forward markout: **−1,070.5**
- **Total: −3,538**

**Counterfactual.** Skip these 140 fills entirely. Net +3,538 vs. 273632.

**Feasibility.** The trigger in `_trade_osmium` is `if vol <= 9 or real_edge >= 2`. The 140 weak crosses likely came through the `vol <= 9` branch (small bot ask) without enough directional signal. A tighter condition like `vol <= 4 OR (real_edge >= 2 AND book_imbalance_same_side)` would skip most of them.

**Real-time availability.** The needed signal (`vol`, `real_edge`, `book_imbalance`) is all in the tick snapshot. This is a **real, learnable** signal, not hindsight. The 82 strong crosses have the same book signature except their markout turned out positive — so there's an implicit feature we're not capturing at fill time.

**Validation path.** Re-run v82_hardened with modified take condition against all three training days (−2, −1, 0) in `mc/server_book_replay.py`. If delta_pnl is consistently positive, ship it.

**Hindsight discount.** Ex-ante signal for "weak markout" is noisy — we cannot perfectly distinguish 140 losers from 82 winners. Realistic capture: **30–60 % of 3,538 ≈ +1,000 to +2,100**.

---

## CF2 (medium): PEP fast ramp — cross the spread for first 80 units ⇒ **+288**

**Leak.** The current strategy quotes passive `bb+1` buys on PEP. It takes **202 ticks** to accumulate +80. During that ramp, PEP drifts +20.2 ticks; average inventory is 40 (linear ramp), so we capture 40 × 20.2 ≈ **+808**. If we were at +80 throughout the ramp, capture would be 80 × 20.2 ≈ +1,616. **Gap: ~800**.

**Counterfactual.** Cross the PEP ask for 8 units/tick until saturated. With actual book data (ba values in first 50 ticks), reaching +80 happens by **ts≈900** (tick 9) at a cross cost of **484** (each unit paid ~6 ticks above mid). Drift gain: **772**.

**Net: +288.**

**Feasibility.** The ramp is a trivial code change: in `_trade_pepper`, when pos < 70 AND tick < 20, add an aggressive take of up to 8 units at any ask ≤ fv_int + 8.

**Real-time availability.** Trivially real-time — executed in first 20 ticks before mid has moved.

**Hindsight discount.** The cross cost depends on the actual ba sequence, which varies day-to-day. On average, PEP ba − mid ≈ 7 ticks. Realistic: **+150 to +300**.

---

## CF1 (smallest / negative): OSM add passive layer at fv±12 ⇒ **−472**

**Leak.** 94 OSM trades happened at the `11–15` tick distance band (prices 9986–9990 and 10012–10016). We quote at 9981/10021 (edge=20) and 9999/10017 (inside). Nothing at 12.

**Counterfactual (as specified).** Add a layer at 9989/10013, size 15 per side. Catch 29 of the 94 trades that aren't already ours (65 of the 94 are already us — incoming taker flow matching our inside quote's outer reach). Apply 50 % queue priority discount: gross upside **+502**. Adding a new layer fills us faster → we hit +80 more often → displaces some of the outer edge=20 sniper bonuses (estimate 30 % of 3,245 = **−973**). **Net: −472.**

**Interpretation.** This matches memory: "OSM edge=12-20 plateau (min=1071 tie)". The plateau is genuine; tightening to 12 doesn't help on this day.

**Feasibility.** Easy change, but the counterfactual says it's slightly harmful. Skip.

**Real-time availability.** Real-time. No ex-ante info required.

**Hindsight discount.** None — already computed as realistic.

---

## Summary table

| # | counterfactual | raw hindsight $ | realistic capture $ | complexity |
|---|---|---:|---:|---|
| CF3 | Skip weak OSM crosses | +3,538 | +1,000 to +2,100 | low (tighten `vol ≤ 9` branch) |
| CF2 | PEP fast ramp via crossing | +288 | +150 to +300 | low (few lines in `_trade_pepper`) |
| CF1 | OSM add fv±12 layer | −472 | do not ship | trivial but harmful |

**Combined realistic upside: ~+1,200 to +2,400** on 101,200 base (1.2 – 2.4 %).

The small magnitudes reflect that **v82_hardened is already close to the engine-constrained optimum**. The +80 position cap and the engine's fixed bot flow patterns leave limited alpha. Future rounds with larger caps, multi-product arbitrage, or observation streams offer materially bigger $.
