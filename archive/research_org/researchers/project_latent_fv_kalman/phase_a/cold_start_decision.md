# Cold-Start Decision Note — Latent-FV Kalman

**Project:** `latent_fv_kalman`
**Phase:** A (milestone A3, decision pin)
**Status:** Pinned. Do not relitigate without revisiting `phase_a/validation.md` §B.3.
**Date:** 2026-04-18

This short note records the cold-start convention as implemented in
`phase_a/filter.py` and motivates why **cold-start is the production
default** for both OSM and PEP. Warm-start factories exist but are
training-time only. The decision is binding for Phase B ablation
design and Phase C implementation against `iter23_trader.py`.

---

## 1. The convention (as implemented)

### 1.1 Tick frame is session-relative

`t` in the PEP equation `FV_t = μ + 0.1·t + s_t` is **session-relative**,
not cumulative. In `filter.py` this is encoded by

```python
CsvTick.tick = timestamp // 100
```

where `timestamp` is the per-CSV (per-server-session) integer
timestamp that resets to 0 at the start of each day's file. A 1,000-
timestamp resolution gives ticks `0, 1, 2, …, 9999` per day, and
ticks `0, 1, …, 999` per 1,000-tick R2 server session. Both have the
same per-tick semantics (one filter step = one 100-timestamp book
update), but neither continues across files / sessions.

### 1.2 Cold-start factories

```python
LatentFVKalman.cold_start_osm()                   # OSM, no μ
LatentFVKalman.cold_start_pep(mu, tick0)          # PEP with derived μ
```

are the production entry points. Internal initial state:

| field | OSM cold-start | PEP cold-start |
|---|---:|---:|
| `x` (state) | 0 (caller seeds via first `update`) | 0 (zero-mean residual `s`) |
| `P` (variance) | 25.0 (wide) | 10.0 (wide) |
| `μ` | n/a (set 0) | derived: `y₁ − 0.1·t₁` |
| `slope` | 0 | 0.1 (`PEP_SLOPE`) |
| `tick` | `−1` initially; first `update()` advances to 0 | `t₁ − 1`; first `update()` advances to `t₁` |

The wide cold-start `P` (25 / 10) gives a first-tick Kalman gain
`K_0 ≈ 0.94` (OSM), so the first observation effectively sets the
state — at no information cost since we have no prior anyway.

### 1.3 PEP cold-start μ derivation

Per `kalman_model.md` §3.5, on cold start:

```
μ̂ = first_observed_inner_mid − 0.1 × first_observed_tick
```

For a session that starts at `tick=0` and has first observed mid `y₁`,
this gives `μ̂ = y₁`. For a session that starts at `tick=k`, it gives
`μ̂ = y₁ − 0.1·k`, so that `μ̂ + 0.1·k ≈ y₁` and the residual `s_0 = 0`
matches the data. This is unbiased on the first tick and absorbs
small μ-errors into `s_t` over the first ~100 ticks (see `validation.md`
Part A.2 — synthetic PEP first-100-tick RMSE ≈ 0.48 vs steady-state
0.47, confirming that the initial μ-error from observation noise gets
absorbed cleanly).

### 1.4 Warm-start factories (training only, NOT for production)

```python
LatentFVKalman.warm_start_osm(x0, P0=5.0)
LatentFVKalman.warm_start_pep(mu, s0=0.0, P0=5.0, tick0=0)
```

These exist for training-time analysis (e.g., the Phase A3 day-
transition diagnostic in `validation.md` §B.3) and as documentation
of the warm-start spec from `kalman_model.md` §§2.5 / 3.5. **They
must not be wired into the production Trader path.**

---

## 2. Why cold-start is the production default

### 2.1 Server runs are independent 1,000-tick sessions

The IMC R2 server runs each strategy submission as a single 1,000-
tick session with a fresh `traderData` initialised to `""`. There
is no "yesterday's tail" available at the start of a server session;
there is no prior-day continuation in `traderData`. A warm-start
factory called with no prior-day data would silently fall back to its
default initial state, which is implementation-defined and likely
wrong.

### 2.2 PEP intercepts jump per-session by O(1,000)

`kalman_model.md` §3.3 documents that PEP's daily mean mid grows by
exactly +1,000 per day (the +0.1/tick slope × 10,000 ticks/day).
Held-out data confirms it: day 0 ends at `y ≈ 13,000`, day +1 starts
at `y ≈ 13,000`. But within day +1's session-relative tick frame
(`tick=0`), a warm-started filter carrying day 0's `μ ≈ 12,000`
would predict `fv = μ + 0.1·0 + s ≈ 12,001.6`, off by **−999** ticks.

The A3 warm-start diagnostic (`validation.md` §B.3) measured this
shock empirically:

```
PEP warm-start init fv(tick=0) = 12,000.12   first day+1 y = 13,000.00
                       shock   = +999.88
```

The filter does eventually recover (50 ticks after start, fv ≈ 13,005,
P ≈ 0.235 = P_∞), but the first ~10 ticks are catastrophically wrong
(error ≈ −20 to −240 ticks). For a 1,000-tick session, this 10-tick
warm-up is 1 % of the session and would dominate downstream PnL.
Cold-start avoids this entirely: it derives `μ` from the first
observed mid, so `fv(tick=0) ≈ y₁`, error ≈ 0, no warm-up shock.

### 2.3 OSM warm-start shock is smaller but still present

`validation.md` §B.3 also measured the OSM warm-start day-transition:

```
OSM warm-start init x = 10,007.77   first day+1 y = 10,008.00   shock = +0.23
```

The shock is small here because OSM's session-to-session intercept
drift is bounded (~5 ticks per the §1.1 table in `kalman_model.md`).
But the magnitude is unpredictable at deploy time — some sessions
will jump 5+ ticks (the memo's "10,001 vs 10,004" mismatch) — and the
warm-up cost is again ~10 ticks. Cold-start is safer.

### 2.4 The risk model: unknown failure mode > known one-tick K

The cold-start convention has one downside: the first observed tick
gets `K ≈ 0.94`, so a single noisy `y₁` (e.g., a stale book artifact)
fully sets the state. This is the standard concern with the wide-
prior approach.

In practice:
- The Trader's first call to the filter is gated on a healthy book
  (`_inner_mid_*` returning a real number, not `None`).
- One bad first-tick sets the state ±1.3 ticks (the measurement-noise
  RMS) on average, which is recovered within 4 (OSM) / 7 (PEP) ticks.
- A bad warm-start can produce a +1,000 PEP shock that takes 50
  ticks to correct.

The expected damage from a bad cold-start is bounded; the expected
damage from a bad warm-start is not. We accept the K_0 ≈ 0.94 risk.

---

## 3. Implications for Phase B and Phase C

### 3.1 Phase B (analysis)

- All ablation runs against day +1 (held-out) MUST use cold-start to
  reproduce production behavior. Warm-start runs are useful as a
  training-time control (to understand what the filter would do with
  perfect prior-day knowledge) but should be reported separately.
- The synthetic-recovery test (`validation.md` Part A) seeds the
  filter from the first observation per the cold-start convention.
  Phase B sensitivity sweeps should mirror this.

### 3.2 Phase C (specification)

- The Phase C spec for `_trade_osmium` / `_trade_pepper` initialises
  via cold-start factories.
- `traderData` round-trip carries the live filter state across ticks
  *within* a session (this is what `PairedKalman.serialize` /
  `deserialize` exists for). It does NOT carry state across sessions.
- The Phase C spec's "Implementation notes" section must explicitly
  state: "Production uses cold-start. Warm-start factories are
  for training only and must not be invoked from the Trader path."

### 3.3 If a future change wants warm-start

If a later phase finds an exploitable cross-session predictor (e.g.,
a stable per-day intercept that survives the +1,000 PEP jump), the
warm-start machinery is in place to use it. But the change must:
1. Re-derive `μ` for the new session's tick frame (don't carry
   day 0's `μ` directly; compute `μ_new = μ_prev + slope × ticks_per_day`).
2. Re-run the §B.3 day-transition diagnostic to confirm the warm-
   start shock is < ±2 ticks.
3. Update this file to reflect the new convention.

Until any of those changes happens, **cold-start is the production
default and the only supported path through the Trader**.

---

## 4. Summary

| dimension | decision |
|---|---|
| `t` semantics | session-relative (`timestamp // 100`, resets per session) |
| Production init | cold-start (`cold_start_osm()`, `cold_start_pep(μ, tick0)`) |
| Warm-start factories | exist; training-time only; must not be wired into Trader |
| PEP `μ` derivation | `y₁ − 0.1·t₁` from first observed inner-mid |
| Initial `P` | 25.0 (OSM), 10.0 (PEP) — wide enough that K_0 ≈ 0.94 |
| Initial tick | `t₁ − 1` so first `update()` advances to `t₁` |
| Empirical justification | `validation.md` §B.3 — warm-start PEP shock = +999.88 ticks on day-transition; cold-start has no such shock by construction |

This decision is pinned. Do not change the production init path
without revisiting `validation.md` §B.3 and the rationale in §2 above.
