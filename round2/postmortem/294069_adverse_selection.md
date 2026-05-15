# 294069 — adverse-selection leak quantification

**TL;DR — Verdict: Deprioritize.** A perfect oracle filter at the chosen
threshold yields an expected upside of `$0–$30` against current PnL of
`$1,434` (~0–2%). Realistic filters (false-positive rate ≥10%) are net
**negative**. The strategy's ~$5 entry edge already absorbs most adverse-
selection drift, so spending iteration on a filter does not pencil out. The
larger leak is fair-value misspecification (`OSM_FAIR=10001` vs. observed mid
~`10009`); fixing that would shift both base PnL and the adverse-selection
profile and is the more productive next move.

Source data: `/tmp/prosperity_logs/294069/302973.log` (server JSON contains
`tradeHistory` and `activitiesLog`). Analysis script:
`scripts/postmortems/adverse_selection.py`. Strategy:
`/tmp/prosperity_logs/294069/302973.py` (iter6 server-import variant).

---

## 1. Method

A fill is **toxic at (N, M)** if the activitiesLog `mid_price` moves N ticks
or more *against our position* within M ticks (M·100ms) after the fill.
Concretely, `signed_drift_M = -drift_M` for SELL fills, `+drift_M` for BUYs;
toxic iff `signed_drift_M ≤ -N`.

The "$ adverse-drift cost" is `qty × |signed_drift_M|` summed over toxic
fills — the drift-only loss component, separate from the entry edge captured
at fill time.

The counterfactual assumes a filter that blocks 100% of toxic fills plus a
configurable false-positive fraction of non-toxic fills (drawn preferentially
from the profitable pool — worst-case for the filter). Skipping a fill
forgoes its full M-tick realized PnL `qty × (entry_edge + signed_drift_M)`.

Why those (N, M) ranges? OSM tick = 1 SeaShell, PEP tick = 1 SeaShell,
top-of-book spreads ~4–6 ticks (OSM 16–17 wide), mid quote-to-quote rarely
moves more than 5 ticks per 5 ticks. Bot taker schedules are on the order of
3–10 ticks (per `bot_models.md` memory). So `N ∈ {1,2,3,4,5}` and
`M ∈ {3,5,10,20}` cover plausible cuts.

The reconstructed mid uses the activitiesLog `mid_price` column. Caveat: for
~5% of ticks the book is one-sided and `mid_price` falls back to the visible
side (e.g., `=ask` when bids are empty), introducing transient noise of
±5–10 ticks at those points. Affected fills are rare in this submission
(none of the 5 (N=2,M=5) toxic fills hit a one-sided horizon endpoint per
manual inspection of the toxic-fill detail below).

---

## 2. Per-product toxic-fill rate

Total fills: **23 OSM (6 BUY/17 SELL), 14 PEP (8 BUY/6 PEP)**. Small sample —
all rates carry wide Wilson 95% CIs.

| (N, M)  | Product | Toxic / Total | Rate | 95% CI |
|---------|---------|---------------|------|--------|
| (2, 5)  | OSM     | 3 / 23        | 13%  | [5%, 32%] |
| (2, 5)  | PEP     | 2 / 14        | 14%  | [4%, 40%] |
| (3, 10) | OSM     | 1 / 23        | 4%   | [1%, 21%] |
| (3, 10) | PEP     | 2 / 14        | 14%  | [4%, 40%] |
| (1, 3)  | OSM     | 4 / 23        | 17%  | [7%, 37%] |
| (1, 3)  | PEP     | 5 / 14        | 36%  | [16%, 61%] |

The strategy's average **entry edge** is $4.26 OSM / $5.39 PEP per share
(median $5.00 / $5.75) — large enough that most "drift-adverse" fills remain
net profitable. This is the central reason the filter doesn't pay off.

---

## 3. $ cost of toxic fills (drift-only)

| (N, M)  | Product | Toxic qty | Drift cost (qty × adverse drift) |
|---------|---------|-----------|----------------------------------|
| (2, 5)  | OSM     | 16        | $110.00 |
| (2, 5)  | PEP     | 9         | $37.50  |
| (3, 10) | OSM     | 3         | $19.50  |
| (3, 10) | PEP     | 13        | $69.00  |
| (1, 3)  | OSM     | 14        | $17.50  |
| (1, 3)  | PEP     | 30        | $86.00  |

The OSM `(N=2, M=5)` cost of $110 looks meaningful (~15% of OSM PnL) until
you net it against the entry edge: the 3 toxic OSM fills had a combined
realized 5-tick PnL of `−$22` (not `−$110`), because each fill captured
$1–$7 of entry edge first.

Toxic-fill detail at (N=2, M=5):

```
OSM:
  ts= 3600 SELL qty=3  px=10008  mid=10009  entry=$-1  drift=$+2  pnl_M5=$-9
  ts=34500  BUY qty=8  px= 9995  mid=10002  entry=$+7  drift=$-8  pnl_M5=$-8
  ts=86100  BUY qty=5  px= 9996  mid=10003  entry=$+7  drift=$-8  pnl_M5=$-5
PEP:
  ts=57000 SELL qty=4  px=13063  mid=13057  entry=$+6  drift=$+2.5 pnl_M5=$+14
  ts=80200  BUY qty=5  px=13075  mid=13082  entry=$+7  drift=$-5.5 pnl_M5=$+7.5
```

Note that **both PEP toxic fills are net profitable over 5 ticks** despite
qualifying as "toxic" by the drift criterion. Only OSM has fills that are
genuinely net-losing after drift.

---

## 4. Counterfactual — filter upside

Symmetric filter blocking 100% of toxic + `fp_rate` of profitable non-toxic
fills (worst-case false-positive model). Operating point: (N=2, M=5).

| fp_rate | OSM gain | PEP gain | OSM loss | PEP loss | **Net upside** |
|---------|----------|----------|----------|----------|----------------|
| 0% (oracle) | +$22 | −$21.5 | $0 | $0 | **+$0.50** |
| 10%     | +$22 | −$21.5 | −$52 | −$35 | **−$87** |
| 20%     | +$22 | −$21.5 | −$104 | −$71 | **−$174** |
| 30%     | +$22 | −$21.5 | −$156 | −$106 | **−$262** |

Per-product summary:
- **OSM**: filter gains $22 (3 toxic losers blocked), loses $0–$156 to FP
  on ~$220 of profitable PnL pool ⇒ net $+22 to $-134.
- **PEP**: filter "gains" −$21.5 (toxic fills are still profitable, so
  blocking them HURTS), loses additional $0–$106 to FP ⇒ net $-21.5 to $-127.

The PEP result is qualitatively different: a drift-based filter would block
fills that the wide entry edge already makes profitable. **The filter does
the wrong thing on PEP** even with perfect drift prediction.

Bootstrap 95% CI on combined oracle (`fp=0%`) net upside: **[$-36, $+39]**
(median $+2). The point estimate of $0.50 is statistically indistinguishable
from zero given 37 fills.

---

## 5. Sensitivity sweep

Combined OSM+PEP net upside ($) across reasonable (N, M) and FP rate:

| (N, M) | fp=0% | fp=10% | fp=20% | fp=30% |
|--------|-------|--------|--------|--------|
| (1, 3)  | −145.5 | −224.4 | −303.3 | −382.2 |
| (2, 3)  | +0.5   | −93.2  | −186.9 | −280.6 |
| (2, 5)  | +0.5   | −87.0  | −174.5 | −262.0 |
| (2, 10) | −13.0  | −105.2 | −197.3 | −289.4 |
| (3, 5)  | +5.5   | −83.4  | −172.3 | −261.2 |
| (3, 10) | +3.0   | −90.8  | −184.5 | −278.2 |
| (4, 10) | +24.0  | −71.9  | −167.7 | −263.6 |
| (5, 20) | +34.0  | −53.3  | −140.6 | −227.9 |

The oracle (fp=0%) upside ranges from `−$145.5` (N=1) to `+$34` (N=5,M=20).
**Swing > 5×** across reasonable N — the upside is NOT robust to the
threshold choice. The (N=1, M=3) row is dominated by PEP (which has a 36%
"toxic" rate at this loose threshold but where toxic fills are profitable),
producing a strongly negative oracle upside.

The most filter-friendly setting (N=5, M=20) yields $34 of oracle upside —
about **2.4% of total PnL** — and goes negative at any FP ≥7%.

---

## 6. Verdict

**Deprioritize: upside < 10% of current PnL.** Specifically:

1. The **best-case oracle upside is $34** (2.4% of $1,434). Realistic
   filters (FP ≥10%) push the number negative at every (N, M) tested.
2. The strategy's **entry edge ($4–6 per fill) absorbs most drift**. PEP
   "toxic" fills are net profitable; a drift-based filter actively damages
   PEP PnL.
3. Sample size is small (23 OSM, 14 PEP fills). Bootstrap 95% CI on the
   oracle upside straddles zero (`[$-36, $+39]`). Even if the point estimate
   were larger, we couldn't distinguish it from noise in a single 1000-tick
   submission.
4. The bigger lever is **fair-value calibration**, not adverse-selection
   filtering. `OSM_FAIR=10001` is ~$8 below the observed mid; that gap drives
   a structural bias (we sell into the rising market, rarely buy back).
   Fixing fair to track `deepest_mid` (as PEP already does) would change the
   fill mix entirely and likely yields >$30 directly.

**One-line answer to "should I build the adverse-selection filter before
adding another product?"** — No. Skip the filter. Calibrate fair value or
add a product first; revisit toxicity only after the fill count per
submission grows enough to detect it (>~100 fills/product).
