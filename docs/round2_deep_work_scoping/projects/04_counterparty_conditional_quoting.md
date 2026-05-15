# Project 04 — Counterparty-conditional quoting

## Mechanism
If different bots have stable, distinguishable trading styles (some
passive, some aggressive, some informed, some noise), you can size
and price each side of your quote based on WHO is most likely to
counterparty you. Strategy: observe recent fills' pattern, infer
"which bot cohort is active," skew quotes asymmetrically.

## Required data
**UNAVAILABLE.** Cross-reference `data_inventory.md`:

- Trade CSV columns include `buyer` and `seller` but both are EMPTY strings for all non-SUBMISSION trades in training tapes and server logs.
- No participant IDs, no cohort labels, no anonymized bot tokens.
- Even server tradeHistory only distinguishes `SUBMISSION` vs empty.

There is no signal to condition on. Any "counterparty model" would be
a fiction built over a single undifferentiated bot population.

## Effort
N/A — project is infeasible.

## Probability of producing ≥ $500/slice
**0 %.** Without participant labels, the conditioning variable does not exist.

## Expected alpha conditional on success
Hypothetical: $800–$2,500 per slice if bot identities were exposed
and varied meaningfully. Moot.

## Why fast iteration didn't capture this
Not a depth issue — a data issue.

## Failure modes
The project fails at "what are we conditioning on?" on day zero.

## Recommendation
**KILL at scoping.** Archive for the case where IMC releases
participant-level data in a future round.

## Alternative worth noting
A degenerate "counterparty-style" proxy using trade-price-vs-mid
clustering (infer latent cohort per trade from price aggressiveness)
is technically possible but collapses onto Project 03 (Hawkes) or
Project 06 (latent state) — do not re-fund it separately.
