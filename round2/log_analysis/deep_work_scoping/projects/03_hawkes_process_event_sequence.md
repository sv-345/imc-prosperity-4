# Project 03 — Hawkes process for event-sequence modeling

## Mechanism
Bot taker-flow is clustered: memory (`bot_behavior.md`) notes
ρ = 0.85 direction autocorr on PEP and a deterministic 3-phase OSM
taker schedule. Model bot buy-takes and sell-takes as a mutually
excited Hawkes process. Use the fitted intensity as a real-time
"taker storm likely in next N ticks" signal. Use it to (a) widen the
adversely-selected side, (b) tighten the other side to catch the
queue fill, or (c) pre-position inventory ahead of anticipated flow.

## Required data
**AVAILABLE.**
- Trade timestamps at 100-ts resolution from all 3 R2 training days + R2 server tapes.
- Buyer/seller empty strings mean we can't directly label "which bot triggered which" — but we can label BUY-initiated vs SELL-initiated by comparing trade price to best-bid/best-ask (accuracy ~80–95 %).
- Aggregate per-product event streams are enough for a bivariate Hawkes.

## Effort
- **Phase A:** 10–14 h — infer aggressor-side per trade; build event stream tooling; likelihood-maximization fitter for exponential-kernel Hawkes (self + cross excitation).
- **Phase B:** 8–12 h — fit on day −1/0, validate on day +1; report excitation matrix, decay half-lives, and predictive R² for next-tick event intensity; held-out AUC for "burst in next K ticks" prediction.
- **Phase C:** 4–6 h — spec online intensity tracker (exponentially-decayed trade count per side) and threshold-gated defensive widening / aggressive taker logic.
- **Total:** 22–32 h.

## Probability of producing ≥ $500/slice
**30 %.** Strong: the underlying autocorrelation pattern is already documented as real and significant in memory. Weak: converting a signal's predictive AUC into $ depends on translating it into actions that clear engine friction (slippage, queue priority).

## Expected alpha conditional on success
**$500–$2,000.** Lower bound assumes signal only gates defensive widening (modest gain). Upper bound assumes signal enables both defense AND offensive inventory pre-positioning on predicted taker storms.

## Why fast iteration didn't capture this
iter22 added a simple net-take signal but treated it as iid (no
temporal structure). Full Hawkes requires modeling mutual excitation
decay kernels, needs MLE fit, and iteration speed can't support the
"try N parameter triplets" cycle. Phase B's held-out validation also
catches overfits that iter tuning naturally produces.

## Failure modes
1. Aggressor-side inference is too noisy on bot-bot trades — intensity estimates are wrong enough that real-time filtering doesn't help.
2. Hawkes structure exists but is dominated by product-specific phase schedules that are better modeled directly (e.g., OSM 3-phase schedule) rather than as a stationary process.
3. Decay kernels are so fast (< 5 ticks) that the signal is useless by the time we can act.
4. Engine latency: the book has already moved by the time our response order reaches the server.
