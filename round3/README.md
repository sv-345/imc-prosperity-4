# Round 3 — ideas (archive)

Compiled 2026-05-15 from `IMCProsperityR3/` before pruning.
Products: **HYDROGEL_PACK**, **VELVETFRUIT_EXTRACT** (delta-1, limit 200
each) + 10 VEV vouchers (calls, limit 300 each, strikes 4000–6500, TTE
started at 7d and decremented 1 day per round).

## Best performing strategy (preserved)

`round3/463514.py` — the v86 wing-bid trader (extends v61 base).
**Final R3 server result: $41,556** (submission 463514). Trade history
and activities log preserved in `463514.log` / `463514.json`.

An earlier v86-family run (sub 368653, mid-season) scored $14,601.82 and
was the headline number for most of R3. The preserved `463514` run is
the end-of-round scoring sub on the same strategy family and is roughly
3× larger — consistent with R3's per-day variance and the longer-lived
HYDROGEL anchor windows present in the scored session.

Backtester: `IMCProsperityR3/` uses the shared
`chrispyroberts-imc-prosperity-4/` fork (top-level) as its sim runtime.
No local backtester to preserve.

### PnL attribution — sub 463514

| Product               | Server PnL | Notes                                                          |
| --------------------- | ---------: | -------------------------------------------------------------- |
| HYDROGEL_PACK         |    $21,685 | Anchor-relative take (anchor=9991, edge=28) — the headline edge. |
| VEV_5200              |     $5,724 | Delta-1 voucher MM, near-the-money.                            |
| VEV_5300              |     $4,192 | Same.                                                          |
| VEV_5100              |     $2,272 | Same.                                                          |
| VEV_5000              |     $1,876 | Same.                                                          |
| VEV_5400              |     $1,719 | Same.                                                          |
| VEV_4500              |       $864 | Deep-ITM take.                                                 |
| VEV_4000              |       $403 | Deep-ITM take.                                                 |
| VELVETFRUIT_EXTRACT   |     $2,646 | Anchor-relative take (anchor=5250, edge=23).                   |
| VEV_5500              |       $176 | Marginal.                                                      |
| VEV_6000 / VEV_6500   |        $0  | Wing bid-at-0 never filled.                                    |
| **Total**             | **$41,556** |                                                                |

Headline: HYDROGEL anchor-relative take is 52% of the round; voucher
delta-1 MM on the 5000–5400 strike band is another ~$16k. VELVET
anchor-take is smaller than HYDROGEL despite the larger position limit
— anchor windows on VELVET are narrower in the scored session.

### Wing bid-at-0 — costless but uninformative

The v86 addition over v61 was a passive `bid = 0` on VEV_5500 / 6000 /
6500. The thesis (`wing_voucher_architecture.md` in auto-memory):
"long at bid = 0 carries positive expectation almost regardless of the
underlying realisation." Server result: zero fills on all three wings,
zero PnL. The bid is costless to maintain but produces no PnL — the
asymmetry is real, the *opportunity* to trigger it on the server is
not. Treat the wing bid as evidence-free until a fill is observed.

## Final strategy (three-layer)

### Layer 1 — Delta-1 MM with anchor-relative take

This is the alpha that mattered. Anchor-relative take captured **+$13k**.

- Passive MM: quote `bb+1` / `ba-1` at size 30 (HYDROGEL) / 50 (VELVET).
- **Take logic** (the key insight):
  - When `bb ≥ anchor + edge` → SELL (sell into elevated bot bid).
  - When `ba ≤ anchor − edge` → BUY (buy from depressed bot ask).
- Tuned:
  - HYDROGEL_PACK: anchor=9991, edge=28
  - VELVETFRUIT_EXTRACT: anchor=5250, edge=23
- **Mechanism**: IMC's end-of-session mark uses the per-product anchor.
  Convergence premium accrues to anyone selling above / buying below anchor.

### Layer 2 — Active voucher passive MM (VEV_5000 / 5100 / 5200)

- `bb+1` / `ba-1` at size 3, only when spread ≥ 4.
- **No take logic** (took out v2 with wrong-FV mispricings).
- Small contributions ~$36 total. Retained for robustness.

### Layer 3 — Deep-ITM take (VEV_4000, VEV_4500)

- Take if `ba ≤ intrinsic − 2` or `bb ≥ intrinsic + TV_cap + 2`.
- Tiny but reliable: ~$25 each.

### Excluded by design

- **Wings** (VEV_6000, 6500): v12 proved wing hidden-FV ≈ 0 (not BSM).
  Always lose. v86 added a `bid=0` passive — asymmetric, can't lose on
  entry, marks at $0.50+ if filled.
- **Deep OTM** (5300/5400/5500): tight-spread strikes can't passive-MM
  without crossing.

## Journey (v2 → v39 → v86)

| v | Change | PnL | Lesson |
|--:|---|---:|---|
| v2 | Active voucher MM with take | $777 | BSM take with wrong S → adverse |
| v3b | Drop all voucher trading | $1,049 | +35% just by removing bad takes |
| v6 | Delta-1 size 5→10 | $1,184 | Sizing matters; HYDROGEL saturated at 10 |
| v7 | Size 10→20 | $1,374 | VELVET added $190 |
| v15 | Multi-level quoting | $978 | **Adverse selection disaster** |
| **v17** | **Anchor-relative take both delta-1** | **$4,877** | **+680% on HYDROGEL** |
| v22 | HYDROGEL edge=30 | $9,008 | edge sweep |
| v23 | edge=40 | $3,766 | **Cliff** — no triggers fire |
| **v28** | HYDROGEL edge=28 | $13,074 | sweet spot |
| **v35** | + VELVET edge=23 | **$14,618** | peak |
| v39 | final confirmation | $14,602 | shipped |

## Velvet drift-aware ask shift (v61 add)

When `state.market_trades["VELVETFRUIT_EXTRACT"]` contains a price >
prev-tick mid → set 5-tick cooldown. During cooldown, drop the VELVET
passive ask (`ba−1`) quote, keep bid + anchor-take sells at bb.

Source: A3's bot-to-bot report. BUY-aggressor prints predict **+0.47 mid
drift over 5 ticks** (t=5.87, n=781). Skipping our ask during the drift
window avoids adverse fills.

## Safety-critical lessons

1. **Voucher take with BSM theo is TOXIC**: first-tick underlying mid
   defaults to anchor if no VELVET observed yet. Real S ≠ anchor on tick
   0 → huge BSM error → bogus takes → runaway shorts. v2 lesson.
2. **Multi-level quoting causes adverse selection** (v15 lost $400).
   Deeper passive orders fill AFTER mid drifts against you.
3. **Wing vouchers close at intrinsic ≈ 0, not BSM.** v12 lost $540
   buying pinned 6000/6500 at $1.
4. **Anchor-relative takes work because hidden FV tracks the anchor**,
   not the final session mid. Edge sweet spot narrow (~25–28).
5. **Fixed-tick close was overfit to 1k test** (v58e–v58h). Per-day MTM
   peaks on 10k sessions land at fractions [0.88, 1.00]; no
   fixed-tick / fraction / threshold / drawdown variant beats
   never-close on all 3 days. v58h was catastrophically test-overfit.

## Strategic lesson on test ≠ eval

The R3 wiki (quoted by dam4709) confirmed eval runs **10× longer** per
session than test. The local rule "trader.py pinned at best-test-PnL"
was false. **v58h won test ($22,382) but would have lost eval** —
closes at 6.9% through, forfeits $60k MTM. v61 was projected ~$76k on
eval, won.

## Rook-E1 voucher hints (for future option rounds)

The in-game hints fully specified the intended approach:

1. **Black-Scholes IV per voucher.** B-S is *the* pricing model, not a
   candidate.
2. **Cross-sectional view**: IV vs moneyness. The smile structure is the
   signal.
3. **Trade outliers** — strikes deviating from the smile. Direction =
   sign of deviation. Buy underpriced vol, sell overpriced.
4. **Size proportional to deviation magnitude.**

But in practice, **anchor-relative take on delta-1 dominated** the
voucher smile alpha by ~5×. The smile alpha was small (~$25 deep-ITM,
~$36 passive MM); the delta-1 anchor mechanic captured ~$13k.

Hint 4 ("Means to an End") describes the manual auction, not options.

## Sim ↔ server divergence

| | Sim quick mean | Server v39 | Ratio |
|---|---:|---:|---:|
| Total | 12,505 | 14,602 | 0.86 |
| HYDROGEL | 9,026 | 12,310 | 0.73 |
| VELVETFRUIT | 3,226 | 2,205 | 1.46 |

Sim assumed bot-only books + Poisson takers from 3-day CSVs. Server
runs **shorter single day** (~99k timestamps vs sim 999.9k) with bot
quotes further off-anchor — HYDROGEL bb regularly reaches anchor+28 on
live, less often in sim. **Anchor-relative take is tuned to live
behavior, not sim**.

## Wiki rules verified

From `chrispyroberts-imc-prosperity-4/backtester/prosperity3bt/runner.py`
`match_buy_order()`:

1. Orders match **instantaneously**, player-first (no bot can beat you
   at the same price).
2. **Unfilled residual → step-in mechanic**: residual posts as outstanding
   quote at player's price; bot-to-bot trades at that timestamp that
   cross your price fill **at your price** (not the market trade price).
3. **All orders cancelled at end of each timestep** (~100ms TTL).

## Other notes

- Position limits R3+: delta-1 = ±200, vouchers = ±300 each.
- Server uses anchor for EOD mark, not last-trade mid — this is the
  exploitable fact behind anchor-relative take.
