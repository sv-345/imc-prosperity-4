"""Latent-FV Kalman filter implementation (Phase A milestone A2).

Self-contained, zero-dependency scalar Kalman filter for OSM and PEP
fair-value tracking on R2 book observations.  Implements the
state-space specification from ``phase_a/kalman_model.md`` sections
2.6 (OSM) and 3.6 (PEP) with pooled fit-day parameters:

    R_osm_base = 1.68   Q_osm = 0.145
    R_pep_base = 1.61   Q_pep = 0.040
    INFLATE    = 25     (one-sided-book R multiplier)

Public surface:

    LatentFVKalman(product, Q, R_base, inflate=25.0, P0=25.0, x0=None, ...)
        .predict()                                 # state-transition only
        .update(y, one_sided=False)                # predict + measurement update
        .fv(tick_index=None)                       # latent FV estimate (adds drift for PEP)
        .serialize() -> str                        # compact ASCII, <= 48 chars/product
        LatentFVKalman.deserialize(token) -> ...   # round-trip from .serialize()

    PairedKalman(osm, pep)                          # convenience bundler
        .serialize() -> str                        # "<osm>|<pep>", <= 200 chars total
        PairedKalman.deserialize(blob) -> ...

The filter is deliberately product-agnostic; PEP's known +0.1/tick
drift is handled by the caller passing ``tick`` into ``update`` /
``fv`` and the filter operates on the residual ``y - mu - 0.1 * tick``.

Run ``python filter.py`` to execute the validation harness, which
verifies:

    (a) posterior P converges to analytical P_inf within +/-5 %
    (b) filtered-mid RMSE vs raw mid is lower on held-out day +1.
"""

from __future__ import annotations

import csv
import math
import os
from dataclasses import dataclass
from typing import Iterable, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Calibrated parameters from phase_a/kalman_model.md section 5
# ---------------------------------------------------------------------------

OSM_Q = 0.145
OSM_R_BASE = 1.68
PEP_Q = 0.040
PEP_R_BASE = 1.61
ONE_SIDED_INFLATE = 25.0
PEP_SLOPE = 0.1


# ---------------------------------------------------------------------------
# Core filter
# ---------------------------------------------------------------------------


class LatentFVKalman:
    """Scalar Gaussian random-walk Kalman filter.

    State: ``x`` (latent FV for OSM; zero-mean residual ``s`` for PEP).
    Observation: ``y = x + v`` with ``v ~ N(0, R)``.
    Transition: ``x_{t+1} = x_t + w``, ``w ~ N(0, Q)``.

    For PEP the caller passes the observed mid; the filter subtracts the
    known drift ``mu + 0.1 * tick`` before running the update so ``self.x``
    holds the residual ``s``.  Call ``fv(tick)`` to get the quotable FV.
    """

    __slots__ = (
        "product",
        "Q",
        "R_base",
        "inflate",
        "x",
        "P",
        "mu",
        "slope",
        "tick",
        "n_updates",
        "n_missing",
        "n_one_sided",
    )

    def __init__(
        self,
        product: str,
        Q: float,
        R_base: float,
        inflate: float = ONE_SIDED_INFLATE,
        P0: float = 25.0,
        x0: float = 0.0,
        mu: float = 0.0,
        slope: float = 0.0,
        tick0: int = 0,
    ) -> None:
        if Q <= 0 or R_base <= 0:
            raise ValueError("Q and R_base must be strictly positive")
        if inflate < 1.0:
            raise ValueError("inflate must be >= 1.0")
        if P0 <= 0:
            raise ValueError("P0 must be strictly positive")
        self.product = product
        self.Q = float(Q)
        self.R_base = float(R_base)
        self.inflate = float(inflate)
        self.x = float(x0)
        self.P = float(P0)
        self.mu = float(mu)
        self.slope = float(slope)
        self.tick = int(tick0)
        self.n_updates = 0
        self.n_missing = 0
        self.n_one_sided = 0

    # ------------------------------------------------------------------
    # Factory constructors (warm-start / cold-start)
    # ------------------------------------------------------------------

    @classmethod
    def cold_start_osm(cls, x0: Optional[float] = None) -> "LatentFVKalman":
        """Cold-start OSM filter per kalman_model.md section 2.5.

        ``x0`` defaults to ``None`` and the caller is expected to seed
        via ``update(first_mid, ...)`` — the wide prior (P0 = 25) makes
        K_0 ~= 0.94 so the first observation dominates anyway.  Passing
        ``x0`` pre-seeds the mean (useful in unit tests).
        """
        return cls(
            product="OSM",
            Q=OSM_Q,
            R_base=OSM_R_BASE,
            inflate=ONE_SIDED_INFLATE,
            P0=25.0,
            x0=0.0 if x0 is None else x0,
        )

    @classmethod
    def warm_start_osm(cls, x0: float, P0: float = 5.0) -> "LatentFVKalman":
        """Warm-start OSM from prior-day tail mean + wider-than-R variance."""
        return cls(
            product="OSM",
            Q=OSM_Q,
            R_base=OSM_R_BASE,
            inflate=ONE_SIDED_INFLATE,
            P0=P0,
            x0=x0,
        )

    @classmethod
    def cold_start_pep(cls, mu: float, tick0: int = 0) -> "LatentFVKalman":
        """Cold-start PEP with explicit intercept ``mu``.

        Residual state seeded at 0; caller supplies ``mu`` from first
        observed ``_inner_mid`` minus ``0.1 * tick0``.
        """
        return cls(
            product="PEP",
            Q=PEP_Q,
            R_base=PEP_R_BASE,
            inflate=ONE_SIDED_INFLATE,
            P0=10.0,
            x0=0.0,
            mu=mu,
            slope=PEP_SLOPE,
            tick0=tick0,
        )

    @classmethod
    def warm_start_pep(
        cls, mu: float, s0: float = 0.0, P0: float = 5.0, tick0: int = 0
    ) -> "LatentFVKalman":
        """Warm-start PEP from a prior-day intercept."""
        return cls(
            product="PEP",
            Q=PEP_Q,
            R_base=PEP_R_BASE,
            inflate=ONE_SIDED_INFLATE,
            P0=P0,
            x0=s0,
            mu=mu,
            slope=PEP_SLOPE,
            tick0=tick0,
        )

    # ------------------------------------------------------------------
    # Core recursion
    # ------------------------------------------------------------------

    def predict(self) -> None:
        """Advance one tick with no measurement.  Pure RW transition."""
        # x_{t+1|t} = x_{t|t}   (no drift — slope lives outside the filter)
        self.P = self.P + self.Q
        self.tick += 1

    def update(self, y: Optional[float], one_sided: bool = False) -> None:
        """Predict+update for one tick.

        ``y`` is the raw mid observation for the current product.  For
        PEP the caller passes the observed mid; the filter subtracts
        ``mu + slope * tick`` internally so ``self.x`` tracks the zero-
        mean residual.

        ``y = None`` OR ``one_sided=True`` invoke the one-sided-book
        handling of kalman_model.md sections 2.5 / 3.5.  ``None``
        triggers a pure predict (no update step).  ``one_sided=True``
        inflates R by 25x and proceeds with the update so the estimate
        still moves in the direction of the noisy observation, just
        with tiny gain.
        """
        # predict step
        self.P = self.P + self.Q
        self.tick += 1

        if y is None:
            self.n_missing += 1
            return

        R_t = self.R_base * (self.inflate if one_sided else 1.0)
        # For PEP, work on residual ỹ = y - mu - slope * tick
        if self.slope:
            y_resid = y - self.mu - self.slope * self.tick
        else:
            y_resid = y

        K = self.P / (self.P + R_t)
        self.x = self.x + K * (y_resid - self.x)
        self.P = (1.0 - K) * self.P

        self.n_updates += 1
        if one_sided:
            self.n_one_sided += 1

    # ------------------------------------------------------------------
    # Outputs
    # ------------------------------------------------------------------

    def fv(self, tick: Optional[int] = None) -> float:
        """Return the filtered fair-value estimate.

        For OSM this is just ``self.x``.  For PEP it is
        ``mu + slope * tick + s``.  ``tick`` defaults to the filter's
        internal tick counter.
        """
        if tick is None:
            tick = self.tick
        if self.slope:
            return self.mu + self.slope * tick + self.x
        return self.x

    @staticmethod
    def steady_state_P(Q: float, R: float) -> float:
        """Analytical P_inf for the scalar RW + iid-noise Kalman.

        Derived from the Riccati equation P = (1 - K)(P + Q) with
        K = (P + Q) / (P + Q + R), giving P_inf = (-Q + sqrt(Q^2 + 4 Q R)) / 2.
        """
        return 0.5 * (-Q + math.sqrt(Q * Q + 4.0 * Q * R))

    @staticmethod
    def steady_state_K(Q: float, R: float) -> float:
        P_inf = LatentFVKalman.steady_state_P(Q, R)
        return (P_inf + Q) / (P_inf + Q + R)

    # ------------------------------------------------------------------
    # Serialization (compact, for traderData round-trip)
    # ------------------------------------------------------------------
    #
    # Format: "<product>:<mu>,<x>,<P>,<tick>"
    # where floats use %.3f and product is a 3-char tag.  mu only matters
    # for PEP; for OSM we emit 0 to keep parsing uniform.
    #
    # Size envelope per product:  OSM ~= "OSM:0.000,10001.234,1.680,9999" = 31 chars
    #                             PEP ~= "PEP:11000.000,-0.123,1.550,9999" = 32 chars
    # Combined with separator ~ 65 chars, well inside the 200-char cap.

    def serialize(self) -> str:
        return "{p}:{mu:.3f},{x:.3f},{P:.3f},{t}".format(
            p=self.product, mu=self.mu, x=self.x, P=self.P, t=self.tick
        )

    @classmethod
    def deserialize(cls, token: str) -> "LatentFVKalman":
        if ":" not in token:
            raise ValueError("malformed token: missing ':'")
        tag, payload = token.split(":", 1)
        parts = payload.split(",")
        if len(parts) != 4:
            raise ValueError(f"malformed token payload: {payload!r}")
        mu = float(parts[0])
        x = float(parts[1])
        P = float(parts[2])
        tick = int(parts[3])
        if tag == "OSM":
            f = cls(
                product="OSM",
                Q=OSM_Q,
                R_base=OSM_R_BASE,
                inflate=ONE_SIDED_INFLATE,
                P0=max(P, 1e-9),
                x0=x,
                mu=0.0,
                slope=0.0,
                tick0=tick,
            )
        elif tag == "PEP":
            f = cls(
                product="PEP",
                Q=PEP_Q,
                R_base=PEP_R_BASE,
                inflate=ONE_SIDED_INFLATE,
                P0=max(P, 1e-9),
                x0=x,
                mu=mu,
                slope=PEP_SLOPE,
                tick0=tick,
            )
        else:
            raise ValueError(f"unknown product tag: {tag!r}")
        return f


# ---------------------------------------------------------------------------
# Pair bundling — what actually goes into traderData
# ---------------------------------------------------------------------------


class PairedKalman:
    """Thin wrapper bundling the OSM and PEP filters for Trader-side use.

    The single public concern is ``serialize`` / ``deserialize`` round-
    tripping through the IMC harness's ``traderData`` field (3.75 KB
    cap; project design target is <200 chars total so other state can
    share the channel).
    """

    SEP = "|"

    def __init__(self, osm: LatentFVKalman, pep: LatentFVKalman) -> None:
        if osm.product != "OSM":
            raise ValueError(f"expected OSM filter, got {osm.product!r}")
        if pep.product != "PEP":
            raise ValueError(f"expected PEP filter, got {pep.product!r}")
        self.osm = osm
        self.pep = pep

    def serialize(self) -> str:
        return self.osm.serialize() + self.SEP + self.pep.serialize()

    @classmethod
    def deserialize(cls, blob: str) -> "PairedKalman":
        if cls.SEP not in blob:
            raise ValueError("missing separator")
        osm_tok, pep_tok = blob.split(cls.SEP, 1)
        return cls(
            osm=LatentFVKalman.deserialize(osm_tok),
            pep=LatentFVKalman.deserialize(pep_tok),
        )


# ---------------------------------------------------------------------------
# CSV-side helpers for the unit test / validation harness
# ---------------------------------------------------------------------------


@dataclass
class CsvTick:
    tick: int
    bb1: Optional[float]
    bv1: Optional[int]
    bb2: Optional[float]
    bv2: Optional[int]
    bb3: Optional[float]
    bv3: Optional[int]
    ba1: Optional[float]
    av1: Optional[int]
    ba2: Optional[float]
    av2: Optional[int]
    ba3: Optional[float]
    av3: Optional[int]
    raw_mid: Optional[float]

    def one_sided(self) -> bool:
        return (self.bb1 is None) or (self.ba1 is None)

    def inner_mid_osm(self) -> Optional[float]:
        """Match ``Trader._inner_mid`` in ROUND_2/iter23_trader.py (OSM).

        Scans buy/sell levels for the first book level whose absolute
        volume is in [10, 15]; uses its midpoint if spread in [15, 17].
        Fallback: bb+8 or ba-8 if only one side has an inner level.
        Returns None if neither side has any book liquidity.
        """
        bids = [
            (self.bb1, self.bv1),
            (self.bb2, self.bv2),
            (self.bb3, self.bv3),
        ]
        asks = [
            (self.ba1, self.av1),
            (self.ba2, self.av2),
            (self.ba3, self.av3),
        ]
        ib = None
        ia = None
        for p, v in bids:
            if p is None or v is None:
                continue
            if 10 <= v <= 15:
                ib = p
                break
        for p, v in asks:
            if p is None or v is None:
                continue
            if 10 <= v <= 15:
                ia = p
                break
        if ib is not None and ia is not None and 15 <= ia - ib <= 17:
            return (ib + ia) / 2.0
        if ib is not None:
            return ib + 8.0
        if ia is not None:
            return ia - 8.0
        return None

    def inner_mid_pep(self) -> Optional[float]:
        """Simplified PEP inner mid per kalman_model.md section 3.7."""
        bids = [
            (self.bb1, self.bv1),
            (self.bb2, self.bv2),
            (self.bb3, self.bv3),
        ]
        asks = [
            (self.ba1, self.av1),
            (self.ba2, self.av2),
            (self.ba3, self.av3),
        ]
        ib = None
        ia = None
        for p, v in bids:
            if p is None or v is None:
                continue
            if 8 <= v <= 12:
                ib = p
                break
        for p, v in asks:
            if p is None or v is None:
                continue
            if 8 <= v <= 12:
                ia = p
                break
        if ib is not None and ia is not None:
            return (ib + ia) / 2.0
        if self.bb1 is not None and self.ba1 is not None:
            return (self.bb1 + self.ba1) / 2.0
        return None


def _to_float(s: str) -> Optional[float]:
    return float(s) if s else None


def _to_int(s: str) -> Optional[int]:
    return int(s) if s else None


def load_prices_csv(path: str, product: str) -> List[CsvTick]:
    """Load a ROUND_2 prices CSV, filter by product, return chronological ticks."""
    out: List[CsvTick] = []
    with open(path, "r", newline="") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            if row["product"] != product:
                continue
            ts = int(row["timestamp"])
            out.append(
                CsvTick(
                    tick=ts // 100,
                    bb1=_to_float(row["bid_price_1"]),
                    bv1=_to_int(row["bid_volume_1"]),
                    bb2=_to_float(row["bid_price_2"]),
                    bv2=_to_int(row["bid_volume_2"]),
                    bb3=_to_float(row["bid_price_3"]),
                    bv3=_to_int(row["bid_volume_3"]),
                    ba1=_to_float(row["ask_price_1"]),
                    av1=_to_int(row["ask_volume_1"]),
                    ba2=_to_float(row["ask_price_2"]),
                    av2=_to_int(row["ask_volume_2"]),
                    ba3=_to_float(row["ask_price_3"]),
                    av3=_to_int(row["ask_volume_3"]),
                    raw_mid=_to_float(row["mid_price"]),
                )
            )
    out.sort(key=lambda t: t.tick)
    return out


# ---------------------------------------------------------------------------
# Validation harness
# ---------------------------------------------------------------------------


def _rmse(errors: Iterable[float]) -> float:
    sq = [e * e for e in errors]
    if not sq:
        return float("nan")
    return math.sqrt(sum(sq) / len(sq))


def _convergence_test_osm(day_minus1_path: str) -> Tuple[float, float, float]:
    """Replay day -1 OSM inner-mids; return (P_final, P_inf, rel_error)."""
    ticks = load_prices_csv(day_minus1_path, "ASH_COATED_OSMIUM")
    assert ticks, "no OSM ticks loaded"
    filt = LatentFVKalman.cold_start_osm()
    # Seed the mean from the first observable inner mid (don't leave it at 0).
    for t in ticks:
        y = t.inner_mid_osm()
        if y is not None:
            filt.x = y
            filt.P = 25.0
            break
    for t in ticks:
        y = t.inner_mid_osm()
        one_sided = t.one_sided()
        filt.update(y, one_sided=one_sided)
    P_inf = LatentFVKalman.steady_state_P(OSM_Q, OSM_R_BASE)
    rel = abs(filt.P - P_inf) / P_inf
    return filt.P, P_inf, rel


def _convergence_test_pep(day_minus1_path: str) -> Tuple[float, float, float]:
    """Replay day -1 PEP inner-mids; return (P_final, P_inf, rel_error)."""
    ticks = load_prices_csv(day_minus1_path, "INTARIAN_PEPPER_ROOT")
    assert ticks, "no PEP ticks loaded"
    mu0 = None
    tick0 = None
    for t in ticks:
        y = t.inner_mid_pep()
        if y is not None:
            mu0 = y - PEP_SLOPE * t.tick
            tick0 = t.tick
            break
    assert mu0 is not None, "no observable PEP mid on day -1"
    filt = LatentFVKalman.cold_start_pep(mu=mu0, tick0=tick0 - 1)
    for t in ticks:
        y = t.inner_mid_pep()
        one_sided = t.one_sided()
        filt.update(y, one_sided=one_sided)
    P_inf = LatentFVKalman.steady_state_P(PEP_Q, PEP_R_BASE)
    rel = abs(filt.P - P_inf) / P_inf
    return filt.P, P_inf, rel


def _rmse_test_osm(day_plus1_path: str) -> Tuple[float, float, int, int]:
    """On held-out day +1, compare filter FV tracking vs raw-mid tracking.

    Target: the 1-step-ahead prediction error of the filter should be
    smaller than the raw-mid 1-step-ahead error (i.e., the filter
    reduces bid-ask-bounce noise).  We measure
        err_filter[t] = inner_mid[t+1] - fv_after_update[t]
        err_raw[t]    = inner_mid[t+1] - inner_mid[t]
    on pairs where both endpoints have observable inner mids.
    """
    ticks = load_prices_csv(day_plus1_path, "ASH_COATED_OSMIUM")
    assert ticks, "no OSM ticks loaded"
    filt = LatentFVKalman.cold_start_osm()
    for t in ticks:
        y = t.inner_mid_osm()
        if y is not None:
            filt.x = y
            filt.P = 25.0
            break
    errors_filter: List[float] = []
    errors_raw: List[float] = []
    prev_y: Optional[float] = None
    prev_fv: Optional[float] = None
    warmup = 50  # ignore the first 50 ticks so the filter has converged
    for t in ticks:
        y = t.inner_mid_osm()
        one_sided = t.one_sided()
        if prev_y is not None and y is not None and filt.n_updates >= warmup:
            errors_raw.append(y - prev_y)
            errors_filter.append(y - prev_fv)  # type: ignore[arg-type]
        filt.update(y, one_sided=one_sided)
        if y is not None:
            prev_y = y
            prev_fv = filt.fv()
    return _rmse(errors_filter), _rmse(errors_raw), len(errors_filter), filt.n_one_sided


def _rmse_test_pep(day_plus1_path: str) -> Tuple[float, float, int, int]:
    ticks = load_prices_csv(day_plus1_path, "INTARIAN_PEPPER_ROOT")
    assert ticks, "no PEP ticks loaded"
    mu0 = None
    tick0 = None
    for t in ticks:
        y = t.inner_mid_pep()
        if y is not None:
            mu0 = y - PEP_SLOPE * t.tick
            tick0 = t.tick
            break
    assert mu0 is not None, "no observable PEP mid on day +1"
    filt = LatentFVKalman.cold_start_pep(mu=mu0, tick0=tick0 - 1)
    errors_filter: List[float] = []
    errors_raw: List[float] = []
    prev_y: Optional[float] = None
    prev_fv: Optional[float] = None
    warmup = 50
    for t in ticks:
        y = t.inner_mid_pep()
        one_sided = t.one_sided()
        if prev_y is not None and y is not None and filt.n_updates >= warmup:
            errors_raw.append(y - prev_y)
            errors_filter.append(y - prev_fv)  # type: ignore[arg-type]
        # Baseline "raw" prediction for PEP is y_{t-1} + slope (apples-to-
        # apples with filter FV, which includes slope extrapolation).
        filt.update(y, one_sided=one_sided)
        if y is not None:
            prev_y = y
            # filter's 1-tick-ahead FV uses its internal tick+1
            prev_fv = filt.mu + filt.slope * (filt.tick + 1) + filt.x
    # Align the raw baseline to include the known drift, else it trivially
    # loses.
    errors_raw_with_drift = [e - PEP_SLOPE for e in errors_raw]
    return (
        _rmse(errors_filter),
        _rmse(errors_raw_with_drift),
        len(errors_filter),
        filt.n_one_sided,
    )


def _serialization_roundtrip_test() -> Tuple[int, bool]:
    """Build a realistic pair, serialize, deserialize, check invariants."""
    osm = LatentFVKalman.cold_start_osm(x0=10001.234)
    osm.P = 1.68
    osm.tick = 9999
    pep = LatentFVKalman.cold_start_pep(mu=10999.99, tick0=9999)
    pep.x = -0.123
    pep.P = 1.55
    pair = PairedKalman(osm=osm, pep=pep)
    blob = pair.serialize()
    size = len(blob)
    round = PairedKalman.deserialize(blob)
    ok = (
        round.osm.product == "OSM"
        and abs(round.osm.x - 10001.234) < 1e-3
        and abs(round.osm.P - 1.68) < 1e-3
        and round.osm.tick == 9999
        and round.pep.product == "PEP"
        and abs(round.pep.mu - 10999.99) < 1e-3
        and abs(round.pep.x + 0.123) < 1e-3
        and abs(round.pep.P - 1.55) < 1e-3
        and round.pep.tick == 9999
    )
    return size, ok


def run_validation(
    data_dir: str = "/Users/svelaga/Documents/IMC Prosperity/ROUND_2",
    tol: float = 0.05,
) -> bool:
    """Run all validation checks; return True on full pass."""
    day_m1 = os.path.join(data_dir, "prices_round_2_day_-1.csv")
    day_p1 = os.path.join(data_dir, "prices_round_2_day_1.csv")
    ok = True

    print("=" * 72)
    print("Kalman filter validation harness")
    print("=" * 72)

    # (1) Convergence to P_inf on day -1
    print("\n[1] Posterior P convergence on fit day (day -1)")
    P_osm, Pinf_osm, rel_osm = _convergence_test_osm(day_m1)
    print(
        f"    OSM  P_final = {P_osm:.5f}   P_inf = {Pinf_osm:.5f}"
        f"   rel_err = {rel_osm*100:.2f}%   (tol {tol*100:.0f}%)"
    )
    P_pep, Pinf_pep, rel_pep = _convergence_test_pep(day_m1)
    print(
        f"    PEP  P_final = {P_pep:.5f}   P_inf = {Pinf_pep:.5f}"
        f"   rel_err = {rel_pep*100:.2f}%   (tol {tol*100:.0f}%)"
    )
    if rel_osm > tol:
        print("    FAIL: OSM P did not converge within tolerance")
        ok = False
    if rel_pep > tol:
        print("    FAIL: PEP P did not converge within tolerance")
        ok = False

    # (2) Held-out RMSE improvement on day +1
    print("\n[2] 1-step-ahead RMSE on held-out day (day +1), warmup=50")
    r_filter_osm, r_raw_osm, n_osm, os_count_osm = _rmse_test_osm(day_p1)
    print(
        f"    OSM  filter RMSE = {r_filter_osm:.4f}   raw RMSE = {r_raw_osm:.4f}"
        f"   n = {n_osm}   one_sided = {os_count_osm}"
    )
    r_filter_pep, r_raw_pep, n_pep, os_count_pep = _rmse_test_pep(day_p1)
    print(
        f"    PEP  filter RMSE = {r_filter_pep:.4f}   raw RMSE = {r_raw_pep:.4f}"
        f"   n = {n_pep}   one_sided = {os_count_pep}"
    )
    if not (r_filter_osm < r_raw_osm):
        print("    FAIL: OSM filter RMSE not below raw RMSE")
        ok = False
    if not (r_filter_pep < r_raw_pep):
        print("    FAIL: PEP filter RMSE not below raw RMSE")
        ok = False

    # (3) Serialization round-trip
    print("\n[3] Serialization round-trip (<= 200 chars; round-trip accuracy)")
    size, rt_ok = _serialization_roundtrip_test()
    print(f"    blob size = {size} chars   round-trip ok = {rt_ok}")
    if size > 200:
        print("    FAIL: serialized blob exceeds 200-char cap")
        ok = False
    if not rt_ok:
        print("    FAIL: round-trip did not preserve state")
        ok = False

    # (4) One-sided inflation correctness (smoke test)
    print("\n[4] One-sided inflation: gain with R*25 << gain with R")
    f = LatentFVKalman.cold_start_osm(x0=10000.0)
    f.P = 2.0
    K_base = f.P / (f.P + f.R_base)
    K_infl = f.P / (f.P + f.R_base * f.inflate)
    print(f"    K (full book)      = {K_base:.4f}")
    print(f"    K (one-sided, x25) = {K_infl:.4f}")
    if not (K_infl < K_base * 0.1):
        print("    FAIL: one-sided gain not sufficiently attenuated")
        ok = False

    print("\n" + "=" * 72)
    print("OVERALL:", "PASS" if ok else "FAIL")
    print("=" * 72)
    return ok


if __name__ == "__main__":
    success = run_validation()
    raise SystemExit(0 if success else 1)
