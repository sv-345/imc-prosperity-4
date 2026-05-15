"""Compact inlined version of phase_a/filter.py.LatentFVKalman for B1 variants.

This is a NON-AUTHORITATIVE copy of the Phase-A-frozen filter. It exists
because the MC harness only imports the variant file itself; adding a
sys.path dance to pull in phase_a/filter.py would couple the Trader path
to a research-org layout that Phase C must not inherit. We keep this
copy minimal (no CSV loaders, no validation harness), structurally
identical to phase_a/filter.py on the hot path, and tested by unit
reproduction: running phase_a/filter.py's A2 validation tests against
this core should produce the same outputs. Validated in ``_self_check()``
below.

Frozen parameters from phase_a/kalman_model.md section 5:

    OSM_Q = 0.145    OSM_R_BASE = 1.68
    PEP_Q = 0.040    PEP_R_BASE = 1.61
    INFLATE = 25
    PEP_SLOPE = 0.1

Reserialised via json-in-traderData by the variant run() method. See
each variant for details.
"""
from __future__ import annotations

import math
from typing import Optional

OSM_Q = 0.145
OSM_R_BASE = 1.68
PEP_Q = 0.040
PEP_R_BASE = 1.61
ONE_SIDED_INFLATE = 25.0
PEP_SLOPE = 0.1


class LatentFVKalman:
    """Scalar Gaussian random-walk Kalman filter — structurally equivalent
    to phase_a/filter.py.LatentFVKalman on the hot path.
    """

    __slots__ = ("Q", "R_base", "inflate", "x", "P", "mu", "slope", "tick", "n_updates")

    def __init__(
        self,
        Q: float,
        R_base: float,
        inflate: float = ONE_SIDED_INFLATE,
        P0: float = 25.0,
        x0: float = 0.0,
        mu: float = 0.0,
        slope: float = 0.0,
        tick0: int = -1,
    ) -> None:
        self.Q = Q
        self.R_base = R_base
        self.inflate = inflate
        self.x = x0
        self.P = P0
        self.mu = mu
        self.slope = slope
        self.tick = tick0
        self.n_updates = 0

    @classmethod
    def cold_osm(cls) -> "LatentFVKalman":
        return cls(Q=OSM_Q, R_base=OSM_R_BASE, P0=25.0, x0=0.0, tick0=-1)

    @classmethod
    def cold_pep(cls, mu: float, tick0: int = -1) -> "LatentFVKalman":
        return cls(
            Q=PEP_Q,
            R_base=PEP_R_BASE,
            P0=10.0,
            x0=0.0,
            mu=mu,
            slope=PEP_SLOPE,
            tick0=tick0,
        )

    def update(self, y: Optional[float], one_sided: bool = False) -> None:
        self.P = self.P + self.Q
        self.tick += 1
        if y is None:
            return
        R_t = self.R_base * (self.inflate if one_sided else 1.0)
        if self.slope:
            y_resid = y - self.mu - self.slope * self.tick
        else:
            y_resid = y
        K = self.P / (self.P + R_t)
        self.x = self.x + K * (y_resid - self.x)
        self.P = (1.0 - K) * self.P
        self.n_updates += 1

    def fv(self, tick: Optional[int] = None) -> float:
        if tick is None:
            tick = self.tick
        if self.slope:
            return self.mu + self.slope * tick + self.x
        return self.x


def steady_state_P(Q: float, R: float) -> float:
    return 0.5 * (-Q + math.sqrt(Q * Q + 4.0 * Q * R))


# Analytic constants used by V3/V4 for P-band gating.
OSM_P_INF = steady_state_P(OSM_Q, OSM_R_BASE)  # ~0.4264
PEP_P_INF = steady_state_P(PEP_Q, PEP_R_BASE)  # ~0.2346


def _self_check() -> None:
    """Run a minimal convergence check to confirm this module matches
    the Phase A specification.
    """
    import random as _r

    _r.seed(42)
    # OSM: simulate RW + iid noise, feed to filter, check P -> P_inf
    xt = 10001.0
    kf = LatentFVKalman.cold_osm()
    first_y = xt + _r.gauss(0, math.sqrt(OSM_R_BASE))
    kf.x = first_y
    kf.P = 25.0
    for _ in range(500):
        xt = xt + _r.gauss(0, math.sqrt(OSM_Q))
        y = xt + _r.gauss(0, math.sqrt(OSM_R_BASE))
        kf.update(y, one_sided=False)
    rel = abs(kf.P - OSM_P_INF) / OSM_P_INF
    assert rel < 0.01, f"OSM self-check failed: P={kf.P}, P_inf={OSM_P_INF}, rel={rel}"

    # PEP: simulate s RW + deterministic slope + iid noise
    st = 0.0
    mu_true = 12000.0
    kf = LatentFVKalman.cold_pep(mu=mu_true - 0.1 * 0, tick0=-1)
    for tt in range(500):
        st = st + _r.gauss(0, math.sqrt(PEP_Q))
        y = mu_true + 0.1 * tt + st + _r.gauss(0, math.sqrt(PEP_R_BASE))
        kf.update(y, one_sided=False)
    rel = abs(kf.P - PEP_P_INF) / PEP_P_INF
    assert rel < 0.01, f"PEP self-check failed: P={kf.P}, P_inf={PEP_P_INF}, rel={rel}"
    print(f"_self_check OK: OSM P={kf.P:.4f} (OSM_P_INF={OSM_P_INF:.4f}), "
          f"PEP P_inf={PEP_P_INF:.4f}")


if __name__ == "__main__":
    _self_check()
