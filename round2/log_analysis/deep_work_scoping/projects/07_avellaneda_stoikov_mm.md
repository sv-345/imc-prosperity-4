# Project 07 — Inventory-aware optimal market-making (Avellaneda-Stoikov)

## Mechanism
Classic Avellaneda-Stoikov (2008) derives optimal bid/ask quotes for
a market-maker facing inventory risk, using expected mid volatility,
inventory-risk aversion, and time-to-end-of-session. The solution has
two components: (a) a mid-based reservation price that skews away
from the current inventory (dump inventory toward zero), and (b) a
spread around the reservation price that trades off queue priority
vs. spread capture. Apply to OSM/PEP with product-specific volatility
estimates and the 1,000-tick session horizon.

## Required data
**AVAILABLE.**
- Per-tick mid → volatility estimates for each product.
- Per-tick inventory tracking (own_trades from state).
- Session horizon known (1,000 ticks on server, 10,000 MC).
- Trade sizes for liquidity intensity λ estimation.

## Effort
- **Phase A:** 10–14 h — estimate per-product volatility σ; estimate fill-intensity λ as function of quote-distance-from-mid; derive closed-form bid/ask quotes; build param-calibration harness.
- **Phase B:** 10–14 h — replay on training days and MC; show inventory path differences vs iter23; 3-way comparison iter23 / pure-AS / AS-overlay-on-iter23; held-out day +1 PnL.
- **Phase C:** 4–6 h — spec the quote-generation function; decide whether to replace iter23 passive layer or overlay.
- **Total:** 24–34 h.

## Probability of producing ≥ $500/slice
**25 %.** Medium:
- Strong: AS is well-grounded theory; matches the structural problem (inventory risk, limited session).
- Weak: iter23 already hand-tunes a lot of the same behavior (edge=20 outer, inside quote at bb+1, recycle when pos≥70). AS formalizes what iter23 empirically does. The uplift may be marginal.
- Weak: AS assumes symmetric mean-reverting mid; PEP's deterministic drift violates this and requires extending AS to drift-aware variant (more scope).

## Expected alpha conditional on success
**$300–$1,200.** Upper bound only achievable if AS captures structural asymmetry iter23 misses (e.g., optimal spread WIDENS near session end as time-decay term kicks in, which iter23 doesn't do).

## Why fast iteration didn't capture this
iter23 has `edge`, `buy_limit`, `sell_qty`, etc. as hand-tuned
constants. AS derives these from observable inputs (σ, λ, T, q).
Iteration picks a static number; AS makes the number a function of
state. That's a structural depth change.

## Failure modes
1. AS closed-form assumes infinitely divisible orders and continuous mid — the 1-tick-integer market violates both; discretization error washes out the theoretical advantage.
2. Calibrating λ(distance) requires quote-response data we mostly don't have (we know our fills, not our misses).
3. AS-optimal spread is tighter than iter23's edge=20 outer wall; losing the deep-edge "sniper" fills that iter23 gets costs more than AS saves on inventory risk.
4. PEP drift extension doubles the model complexity; overfit risk.
