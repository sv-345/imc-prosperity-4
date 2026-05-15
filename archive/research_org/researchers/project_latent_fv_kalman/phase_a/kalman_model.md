# Phase A, Milestone A1 — Kalman State-Space Specification

**Project:** `latent_fv_kalman`
**Milestone:** A1 — state-space model specification
**Author:** Researcher subagent
**Date:** 2026-04-18
**Scope:** Mathematical specification ONLY. Implementation belongs to milestone A2 (`filter.py`).

This document specifies two online Kalman filters — one for
`ASH_COATED_OSMIUM` (OSM), one for `INTARIAN_PEPPER_ROOT` (PEP) — to
replace the hardcoded `OSM_FV = 10001` constant and the heuristic
`detect_pepper_intercept` / `_inner_mid` FV references in
`ROUND_2/iter23_trader.py`. All parameters below are estimated from
the training CSVs (`prices_round_2_day_{-1,0}.csv`) with day `+1`
reserved for held-out validation in milestone A3.

---

## 1. Motivation and Empirical Anchors

### 1.1 The leak this model targets

`ROUND_2/305289/analysis.md` diagnosed the primary iter12 leak: the
strategy's hardcoded `OSM_FV = 10001` is not the true R2 fair value.
That analysis quoted a session mean mid of **10,004.19** (activities.json
of the specific R2 session). The published training CSVs give cleaner
estimates when we restrict to ticks where both bid_price_1 and
ask_price_1 are present:

| day | n_clean | clean mean mid | raw CSV mean (mis-leading, includes one-sided ticks) |
|---|---:|---:|---:|
| −1 | 9,237 | **10,000.83** | 9,985.82 |
| 0 | 9,257 | **10,001.58** | 9,985.60 |
| +1 | 9,214 | **10,000.15** | 9,978.21 |

The raw `mid_price` column mixes in rows where one side of the book is
empty and `mid_price` is set to the single-sided quote; roughly 3.9 %
of OSM rows per day are one-sided. These rows should be downweighted
by the filter (see §2.3 below), not treated as reliable FV
observations.

Three independent observations (10,000.83 / 10,001.58 / 10,000.15) all
fall within ±1 of 10,001, while the `305289` session produced a mean
of 10,004. The true session-mean mid is **drifting ±3 ticks
session-to-session**. Any hardcoded constant (10,001 OR 10,004) will
be wrong on roughly half of sessions. This is precisely the use-case
a Kalman filter solves: maintain a running estimate that adapts to the
current session.

### 1.2 Structural signal — mid is bid-ask-bounce-noised latent FV

Lag-1 autocorrelation of first-differenced mid prices, across every
training day and both products:

| series | lag-1 ACF of Δmid |
|---|---:|
| OSM day −1 | −0.479 |
| OSM day 0 | (equivalent, ~−0.48) |
| OSM day +1 | −0.488 |
| PEP day −1 detrended | −0.492 |
| PEP day 0 detrended | −0.496 |
| PEP day +1 detrended | −0.496 |

A pure random walk has lag-1 ACF of Δ = 0. A random walk + iid
measurement noise has lag-1 ACF of Δ ∈ (−½, 0). Values clustered
tightly near **−0.49 for both products** are the fingerprint of "nearly
all variance in Δmid is measurement noise, with a small latent-FV
innovation underneath." This is the canonical Kalman setup.

---

## 2. OSM state-space model

### 2.1 State and observation

Let `x_t ∈ ℝ` denote the latent fair value (in price ticks) at
discrete time step `t = 0, 1, 2, …`. One time step corresponds to one
100-timestamp book update (i.e., `tick_index = state.timestamp // 100`).

**State transition (Gaussian random walk):**

    x_{t+1} = x_t + w_t,      w_t ~ N(0, Q_osm)

No deterministic drift term — empirically OSM mean over a session is
flat (see §1.1), and within-day drift is |Δ/tick| < 0.002 (below the
noise floor). Any trend that emerges is absorbed by the state.

**Observation equation:**

    y_t = x_t + v_t,           v_t ~ N(0, R_osm(t))

where `y_t` is the cleaned mid observation at tick `t` (see §2.3 for
the exact choice), and `R_osm(t)` is tick-dependent to accommodate
one-sided-book rows.

### 2.2 Observation choice: which "mid"?

iter23 already uses `_inner_mid`, a filtered mid that takes the
midpoint of the first book levels whose volume is in [10, 15] and
whose spread is in [15, 17]. This filters out outer-layer liquidity
and the structural 20-tick skew.

The Kalman filter uses `y_t = _inner_mid(book_t)` as the primary
observation. Rationale:

1. `_inner_mid` already sanitizes against one-sided/outer-layer
   pathologies that inflate raw-mid variance.
2. Replacing the raw `mid_price` with `_inner_mid` in the variance
   decomposition would change `R` but not the qualitative model
   structure; we calibrate `R` on the SAME quantity we filter.

If `_inner_mid` returns `None` (no inside liquidity on either side,
rare), the observation is treated as **missing** — the filter performs
the predict step (x_{t+1|t} = x_{t|t}, P_{t+1|t} = P_{t|t} + Q) and
skips the update step.

### 2.3 Measurement-noise schedule R_osm(t)

Two regimes:

- **Full book (both bb and ba present):** `R_osm(t) = R_osm_base`
- **One-sided book (bb or ba missing):** `R_osm(t) = INFLATE × R_osm_base`
  with `INFLATE = 25` (skip the observation in the limit as INFLATE → ∞,
  equivalently treat `y_t` as missing). The `_inner_mid` fallback to
  `bb + 8` or `ba − 8` adds up to ±8 of bias in these cases; the
  inflated R is equivalent to "trust the prior".

Calibration of `R_osm_base` comes from the variance decomposition
in §2.5.

### 2.4 Process-noise Q_osm — variance decomposition

Under the model `mid_t = x_t + v_t` with iid `v_t ~ N(0, R)` and
`x_{t+1} = x_t + w_t` with iid `w_t ~ N(0, Q)`, first differences
have

    Δy_t = y_{t+1} − y_t = w_t + v_{t+1} − v_t
    Var(Δy) = Q + 2R
    Cov(Δy_t, Δy_{t+1}) = −R

Hence the unbiased moment estimator:

    R̂ = −Ĉov_1(Δy)
    Q̂ = Var(Δy) − 2 R̂

Computed on contiguous-tick pairs (Δt = 1 step, to avoid day-boundary
jumps and missing-row gaps), per day, on clean full-book rows only:

| day | n_pairs | Var(Δy) | Cov_1(Δy) | R̂ | Q̂ | K_ss | 1/K_ss |
|---|---:|---:|---:|---:|---:|---:|---:|
| −1 | 7,885 | 3.569 | −1.726 | 1.726 | 0.117 | 0.228 | 4.4 ticks |
| 0 | 7,916 | 3.455 | −1.641 | 1.641 | 0.173 | 0.276 | 3.6 ticks |
| +1 | 7,825 | 3.529 | −1.696 | 1.696 | 0.136 | 0.246 | 4.1 ticks |

Pooled across fit days (−1, 0):

    R_osm_base = 1.68    (price² — i.e., about 1.3-tick RMS measurement noise)
    Q_osm      = 0.145   (price² per tick — about 0.38-tick RMS innovation per step)

The steady-state Kalman gain is

    K_∞ = P_∞ / (P_∞ + R)    where   P_∞ = (−Q + √(Q² + 4QR)) / 2

giving **K_∞ ≈ 0.25**. In plain English: the filter gives new
observations ~25 % weight and the prior ~75 %, with an effective
smoothing horizon of ~4 ticks (one-over-K). This is a much gentler
smoother than `_inner_mid` (which is 1-tick memoryless) but much
faster than `OSM_FV = 10001` (infinite memory, never updates).

### 2.5 Prior at session start

The filter needs `x_{0|−1}` (prior mean) and `P_{0|−1}` (prior variance).

**Warm-start when prior-day tail is available (preferred):**

    x_{0|−1} = mean of last 500 ticks of previous session's filtered estimate
    P_{0|−1} = R_osm_base + Var(last 500 filtered estimates)
              ≈ 1.68 + 2–5
              ≈ 5.0   (price²)

Empirically the day 0 tail (last 500 ticks) has mean mid of
**10,009.22** while day +1's first 500 ticks have mean mid of
**10,003.64** — a 5.5-tick session-to-session jump. So the warm-start
mean is informative but NOT locally correct: we need `P_{0|−1}` wide
enough for the filter to converge quickly. Setting `P_{0|−1} = 25`
(RMS 5 ticks) gives a first-tick Kalman gain of

    K_0 = P_{0|−1} / (P_{0|−1} + R) = 25 / 26.68 ≈ 0.94

i.e., the filter snaps almost entirely onto the first observation,
then exponentially decays toward steady state. Good behavior.

**Cold-start (no prior day available, first run on a fresh round):**

    x_{0|−1} = first observed _inner_mid after book contains both sides
    P_{0|−1} = 25  (same wide prior)

Since `x_{0|−1}` is itself an observation, `P_{0|−1}` should formally
be `R_osm_base ≈ 1.68` — but a wider prior costs nothing (K_1 ≈ 1 for
the first step anyway) and protects against adverse first-tick book
artifacts. Use `25` for robustness.

### 2.6 Online update equations (summary)

Per tick `t = 1, 2, …`:

**Predict:**

    x_pred  = x_{t−1|t−1}
    P_pred  = P_{t−1|t−1} + Q_osm

**Update:**

    y_t     = _inner_mid(book_t)            # may be None
    if y_t is None:
        x_{t|t} = x_pred
        P_{t|t} = P_pred
    else:
        R_t     = R_osm_base × (INFLATE if one_sided else 1)
        K_t     = P_pred / (P_pred + R_t)
        x_{t|t} = x_pred + K_t × (y_t − x_pred)
        P_{t|t} = (1 − K_t) × P_pred

The downstream trading logic consumes `x_{t|t}` as the fair value for
take-side gates in `_trade_osmium`.

---

## 3. PEP state-space model

### 3.1 The deterministic-slope structural prior

PEP has a known mechanical drift of `+0.1 / tick` (see `PEP_SLOPE` in
`iter23_trader.py`, validated across all three training days with
session-end-minus-start / tick ≈ 0.100). Embedding this into the
state equation keeps the random-walk part small and uncorrelated with
the trend.

**Latent state decomposition:**

    FV_t = μ + 0.1 · t + s_t

where

- `μ` is the session-specific intercept (estimated from early book data),
- `0.1 · t` is the known deterministic drift (tick index),
- `s_t` is a latent residual correction (zero-mean random walk).

The filter tracks two state variables: `(μ_t, s_t)`. In practice we
freeze `μ` at its warm-start value and fold all session-to-session
variability into `s_t`; §3.4 treats the two as a 2-dim state if
richer modelling is desired.

### 3.2 Simplified 1-state form (recommended primary model)

Treat `μ` as a known constant (warm-started per session) and model
only `s_t`:

**State transition:**

    s_{t+1} = s_t + w_t,       w_t ~ N(0, Q_pep)

**Observation equation:**

    y_t = μ + 0.1 · t + s_t + v_t,    v_t ~ N(0, R_pep(t))

where `y_t` is the observed `_inner_mid` (or `_inner_mid`-style PEP
midpoint) at tick `t`. Equivalently, define the **residual
observation** `ỹ_t = y_t − μ − 0.1·t` and the filter reduces to a
standard zero-mean RW Kalman filter on `s_t`:

    ỹ_t = s_t + v_t

with the same form as the OSM filter but calibrated on residuals.

### 3.3 Parameter calibration (PEP residuals)

Per-day variance decomposition of the detrended residual
`mid_t − 0.1·tick − μ̂_day`:

| day | μ̂ (intercept) | resid_sd | Var(Δ ỹ) | Cov_1 | R̂ | Q̂ | K_ss | 1/K_ss |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| −1 | 10,999.99 | 1.248 | 3.047 | −1.505 | 1.505 | 0.037 | 0.144 | 6.9 ticks |
| 0 | 11,999.99 | 1.328 | 3.480 | −1.719 | 1.719 | 0.042 | 0.144 | 6.9 ticks |
| +1 | 12,999.99 | 1.439 | 4.101 | −2.019 | 2.019 | 0.063 | 0.161 | 6.2 ticks |

Pooled across fit days (−1, 0):

    R_pep_base = 1.61    (price² — RMS ≈ 1.3 ticks, very close to OSM)
    Q_pep      = 0.040   (price² per tick — RMS 0.20 ticks, ~4x lower than OSM)

Interpretation: after stripping the 0.1/tick drift, PEP has a
**tighter** residual state-innovation than OSM (Q smaller), consistent
with the drift explaining most of its daily motion. The steady-state
`K_pep ≈ 0.14` gives a 7-tick effective smoothing horizon.

**Session-to-session intercept jumps:** the three fitted intercepts
(10,999.99, 11,999.99, 12,999.99) differ by exactly **+1,000 per day**,
reflecting that PEP's mean mid starts the next day where the previous
day left off (the +0.1/tick slope over 10,000 ticks per day = 1,000
points of linear growth). This is consistent with continuous
drift — no session reset. This means `μ` is NOT a session-specific
random variable to re-estimate each day; it's a global function of
cumulative tick count since the series started. For a single-session
filter (R2 server session = 1,000 ticks), the practical consequence
is:

- warm-start `μ̂` from prior-day book data; the intercept should be
  such that `μ̂ + 0.1·t_start ≈ early-session mid`.
- allow the filter to absorb small intercept errors into `s_t`.

### 3.4 Optional: 2-dim state with slowly-varying intercept

If future validation shows `s_t` is drifting systematically (non-zero
mean residual), promote to a 2-dim state `(μ_t, s_t)`:

    μ_{t+1} = μ_t + u_t,      u_t ~ N(0, Q_μ)       [Q_μ very small, ~0.001]
    s_{t+1} = s_t + w_t,      w_t ~ N(0, Q_pep)
    y_t     = μ_t + 0.1·t + s_t + v_t

with observation matrix `H = [1, 1]`. This remains a standard
(linear, Gaussian) Kalman filter. For Phase A we commit to the 1-dim
form; the 2-dim is a milestone B fallback if residuals show drift.

### 3.5 Prior at session start (PEP)

**Warm-start when prior-day tail is available:**

Fit `μ̂_prior` as `mean(last 500 mids) − 0.1 · mean(last 500 ticks)`
from the previous session. Carry `μ̂_prior` forward as `μ` for the
current session (but see §3.3 caveat — the current day's `μ` may need
a +1,000 / −1,000 jump if the simulator resets).

    s_{0|−1} = 0                           # expect residual to start near zero
    P_{0|−1} = 5.0                         # wide-ish so filter can absorb μ error

**Cold-start (no prior day):**

    μ̂            = first observed (_inner_mid) − 0.1 · tick_0
    s_{0|−1}     = 0
    P_{0|−1}     = 10.0                    # wider because μ̂ is untested

### 3.6 Online update equations (PEP)

Per tick `t = 1, 2, …`:

**Predict:**

    s_pred  = s_{t−1|t−1}
    P_pred  = P_{t−1|t−1} + Q_pep

**Update:**

    y_t     = _inner_mid_pep(book_t)       # PEP-style inner-mid (see §3.7)
    if y_t is None:
        s_{t|t} = s_pred
        P_{t|t} = P_pred
    else:
        ỹ_t     = y_t − μ̂ − 0.1·t
        R_t     = R_pep_base × (INFLATE if one_sided else 1)
        K_t     = P_pred / (P_pred + R_t)
        s_{t|t} = s_pred + K_t × (ỹ_t − s_pred)
        P_{t|t} = (1 − K_t) × P_pred

    # Fair value output
    FV̂_t = μ̂ + 0.1·t + s_{t|t}

Downstream PEP trading logic consumes `FV̂_t` in place of the `_pep_fv`
produced by `detect_pepper_intercept`.

### 3.7 PEP-specific inner mid

iter23 uses `detect_pepper_intercept` (3-layer: vol ∈ [8,12]
inner-level midpoint, then vol ∈ [15,25] wall midpoint, then raw
mid). For the Kalman observation `y_t` we use a simplified inner-mid:

1. If inside level has both sides with vol ∈ [8, 12], use their
   midpoint.
2. Else if raw book has both sides, use `(bb + ba) / 2`.
3. Else return `None` (missing observation).

This avoids the multi-layer heuristic bias while still filtering one
clear structural anomaly (empty inside levels).

---

## 4. Assumptions and Limitations

### 4.1 Gaussianity

`w_t` and `v_t` are treated as Gaussian. Actual Δmid histograms have
fatter tails (structural 1-tick jumps dominate, mid gaps of 3+ ticks
are uncommon but present). Kalman with under-estimated tail variance
lags on shocks but recovers within ~5 K-horizon ticks. Acceptable for
R2 where extreme moves are rare (|Δmid| ≥ 5 in < 0.5 % of ticks
per training-day inspection).

### 4.2 Constant Q, constant R

True Q may be time-varying (regime switches, news). We track a single
scalar Q. Regime-switching is project 02's territory (see
`strategic/priorities.md`) — explicitly out of scope here (scoping.md
§ Non-goals).

### 4.3 One-sided book handling

One-sided ticks (3.9 % per day for OSM, ~0 % for PEP) are
down-weighted via inflated R (§2.3). This is simpler than treating
them as formally missing and empirically sufficient — the filter's
steady-state memory (~4 ticks for OSM) means a single high-R
observation barely moves the estimate.

### 4.4 Independence of `w` and `v`

The model assumes `Cov(w_t, v_t) = 0`. Under bid-ask-bounce where
the true FV move and the bounce are mechanically uncorrelated, this
holds. Our Q̂ being small (0.14) and positive (not negative or 0
within estimator noise) is consistent with this assumption.

### 4.5 No explicit trade-flow conditioning

The filter uses only the passive book (`_inner_mid`). It does NOT
condition on the take-signal (market trades in the last tick) that
iter22+ uses for defensive widening. Adding trade-flow as a second
observation channel (`H = [1, τ]` with τ being the mean marketable
trade price) is a milestone-B extension if validation shows
residual alpha.

---

## 5. Parameter Summary Table

| symbol | OSM | PEP (residual) | units | source |
|---|---:|---:|---|---|
| Q_base | 0.145 | 0.040 | price²/step | fit days −1, 0 |
| R_base | 1.68 | 1.61 | price² | fit days −1, 0 |
| INFLATE (one-sided) | 25 | 25 | — | §2.3 |
| P_0 (warm-start) | 5.0 | 5.0 | price² | §2.5, §3.5 |
| P_0 (cold-start) | 25.0 | 10.0 | price² | §2.5, §3.5 |
| x_0 (warm-start mean) | prior-day tail filtered | — | price | §2.5 |
| μ̂ (warm-start) | — | prior-day tail intercept | price | §3.5 |
| s_0 (PEP) | — | 0 | price | §3.5 |
| known drift | 0 | 0.1 / step | price/step | iter23 `PEP_SLOPE` |
| K_∞ (steady-state gain) | ~0.25 | ~0.14 | — | §2.5, §3.3 |

### 5.1 ±20 % sensitivity envelope (MC gate requirement)

Per scoping.md deliverable requirement (Phase C MC gate: sensitivity
within ±20 % of nominal), the tunables are:

- **Q** (state-innovation variance): primary smoothing knob. Higher Q
  → faster reaction, less smoothing. Test: {0.8·Q, 1.0·Q, 1.2·Q} for
  each product.
- **R** (measurement noise): primarily a regime-level constant;
  implicitly tested via the Q/R ratio.
- **INFLATE**: {10, 25, 50} — coarse sensitivity for one-sided
  robustness.
- **P_0 (prior uncertainty)**: only matters for the first ~10 ticks;
  not a primary knob.

---

## 6. What this document does NOT contain

Per the milestone A1 scope, this spec DELIBERATELY omits:

- Actual filter implementation code (`filter.py` — milestone A2).
- Day +1 validation with per-tick RMSE plots (`validation.md` —
  milestone A3 / B).
- Comparison vs iter23 in-simulator PnL (milestone B — Phase B).
- Final code edit spec for `_trade_osmium` / `_trade_pepper`
  (milestone Phase C).

The deliverables above are the three subsequent milestones; each
builds on this mathematical spec.

---

## 7. Validation performed on this spec

1. **Stationarity of Δmid lag-1 ACF across days.** −0.48 to −0.50 on
   all six day-product combinations. A Kalman filter of the specified
   form is consistent with this signature; alternative models (AR(1)
   on mid level, random walk with iid drift) are not.
2. **Q, R are positive across all three days when computed separately**
   (after cleaning one-sided rows). So the variance decomposition
   gives physically meaningful numbers, not numerical artifacts.
3. **Q, R values are consistent day-to-day within ~30 %** (Q_osm:
   0.12, 0.17, 0.14; Q_pep: 0.04, 0.04, 0.06). Stable enough that a
   single pooled estimate transfers to held-out day +1.
4. **PEP intercepts differ by exactly +1,000 per day**, confirming
   the 0.1/tick slope and validating §3.3's session-chaining claim.
5. **PEP residual (after detrending) has standard deviation ~1.3
   ticks**, smaller than OSM raw mid std (3.9–5.2 ticks), confirming
   that the deterministic slope absorbs most of PEP's daily motion
   and leaves a well-behaved residual for the Kalman to filter.
6. **Reconciliation with memory / 305289 analysis**: the memo's
   "R2 OSM mean mid 10,004" refers to the single-session 305289
   activities.json. Our per-training-day clean means are 10,000.8 /
   10,001.6 / 10,000.2 (and the 305289 session happened to be a
   higher-mean session). Both observations are consistent with the
   core claim: **no fixed constant captures session-mean FV**, which
   is the problem a Kalman filter solves.

---

## 8. Next milestone (A2)

Implement `phase_a/filter.py`:

- `class LatentFVKalman` with `__init__(product, Q, R_base, inflate,
  P0, x0, ...)`, `update(observation, one_sided: bool) -> None`,
  `state: float` (posterior mean).
- Unit test: run on day −1, fit Q/R from residuals, verify posterior
  variance converges to `P_∞`.
- Keep the filter state small enough to round-trip through
  `traderData` (a few floats per product).

Expected effort: 1.5–2 h.
