# Tutorial Round 0 — ideas (archive)

Compiled 2026-05-15 from `TUTORIAL_ROUND_1/` before pruning.
Products: **EMERALDS** (stable FV=10000) and **TOMATOES** (random-walk FV).
Final submitted strategy: `trader_v14` — best file preserved at
`TUTORIAL_ROUND_1/trader.py`.

## Result

| Metric | Server | MC mean | MC 5–95% |
|---|---:|---:|---|
| v14 | **2,757.33** | 16,877 | 11,336–~22,000 |
| v13 (identical server PnL) | 2,757.33 | 16,600 | — |

v13 and v14 produce identical results on the deterministic server path.
v14 is preferred — FV rounding fix cuts MC variance by 24% and raises
worst-case floor by 11%.

## Core strategy: penny-jump MM + Bot3 sweeps

- TOMATOES: penny-jump (quote bb+1 / ba−1) — inside the wall bots → fill priority.
- EMERALDS: static FV ± 7 quotes; sweep anything that crosses FV.
- Wall mid FV estimation is optimal for random-walk products.
- Bot architecture (year-over-year): Bot1 outer wall, Bot2 inner wall, Bot3 rare inside-wall.

## What did NOT work (rejected experiments)

| Bucket | Strategy | Result | Reason |
|---|---|---|---|
| Phase 1 surgical | Inventory skew (TOM 0.1+, EM 0.02+) | regressed | symmetric quoting wins |
| Phase 1 | EMERALDS spread=8 | server win was artifact | -52% under match=worse |
| Phase 1 | Position-aware sizing | −8% | spread edge dominates inventory risk |
| Phase 1 | Microprice FV | noise | random-walk FV has no microstructure |
| Phase 2 | z-score mean-reversion on TOMATOES | −24% | random-walk, no MR to capture |
| Phase 2 | Order-book imbalance directional | ~identical | no signal in OBI |
| Phase 2 | 2-level EMERALDS (inner ±3 + outer ±7) | −27% | inner ate priority for thin gain |
| Phase 2 | Volatility regime switching | identical | regime is stable |
| Phase 2 | Pure aggressive | −96% | spreads dominate |
| Hypothesis-test | TOMATOES selective sweep fv−1 (H) | MC +343 / server −214 | MC ≠ server; never filter fills |
| Hypothesis-test | Late position unwind | server −522 | every fill profitable, don't filter |
| Hypothesis-test | "Aggressive oracle" EOD | server −2,490 | massive negative |
| Hypothesis-test | EMA trend skew, OBI variants | reject | random walk |
| KB-inspired | Avellaneda-Stoikov inventory mgmt | reject | game rewards symmetric max-size quoting |
| KB-inspired | Insider bot detection (sub 76470) | reject | no insider on tutorial products |
| KB-inspired | P3→P4 price correlation | R²=0.18 | too weak |

## Lessons that carry forward

1. **Baseline penny-jump is at a local optimum** for stable + random-walk
   markets. Quotes inside the bots guarantee fill priority regardless of
   matching mode. Resist "wider spread for more profit per fill" — it's a
   backtester artifact under generous matching.
2. **Every fill is profitable from spread edge alone** — never filter
   fills based on perceived adverse selection. The spread (~13) >> typical
   directional move (~2), so switching costs dominate.
3. **MC backtester ≠ server.** H improved MC +343 but hurt server −214.
   Always validate on server, treat MC as one signal among several.
4. **Server is deterministic** — same strategy = same server PnL.
5. **EMERALDS is the backbone** (~7K/day stable). TOMATOES higher variance,
   ~7K/day in expectation.
6. **Microstructure signals don't work** on random-walk FV — no signal was
   found in order flow, imbalance, or price history (Phase 1 ruled this
   out conclusively across 4 mean-reversion / directional / regime tests).
