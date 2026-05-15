"""Replay MC v1 using the ACTUAL R1 server FV trajectory.

Hypothesis: the MC's random FV often drifts far from fv_anchor, destroying
the OSMIUM strategy. On the real server, FV barely moved (range 10, net
drift 0.016). Replaying against the real FV trace isolates whether the gap
is from FV randomness (strategy-level fragility) or from a fill-mechanics bug.
"""
from __future__ import annotations
import json
import statistics
import random
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent))
from mc_r1_v1 import MCSim, OSMIUM, PEPPER
from strategies_r1 import make_osmium_stable, make_pepper_trending

DATA = Path(__file__).parent.parent / "data" / "server_state_round1.json"


def load_server_fvs():
    d = json.loads(DATA.read_text())
    osm = [t['fv'] for t in d['ticks'] if t['product']=='ASH_COATED_OSMIUM' and t['fv'] is not None]
    pep = [t['fv'] for t in d['ticks'] if t['product']=='INTARIAN_PEPPER_ROOT' and t['fv'] is not None]
    return osm, pep


class FVReplaySim(MCSim):
    """MCSim that replays a fixed FV trajectory instead of random walk."""
    def __init__(self, *args, fv_trace, **kwargs):
        super().__init__(*args, **kwargs)
        self.fv_trace = fv_trace
        self._tick_idx = 0

    def _update_fv(self):
        if self._tick_idx < len(self.fv_trace):
            self.fv = self.fv_trace[self._tick_idx]
            self._tick_idx += 1


def run_osmium_seeds(fv_trace, n_seeds=50):
    strat = make_osmium_stable(fv_anchor=10000.0, edge=10)  # strat still uses 10000
    pnls = []
    for seed in range(n_seeds):
        sim = FVReplaySim(
            OSMIUM, n_ticks=len(fv_trace), seed=seed, strategy=strat,
            fv_trace=fv_trace, fv0=fv_trace[0],
        )
        sim.run()
        pnls.append(sim.summary()['final_mtm_pnl'])
    return pnls


def run_osmium_aligned(fv_trace, n_seeds=50):
    """Same but strategy uses actual mean of fv_trace as anchor."""
    fv_anchor = round(statistics.mean(fv_trace))
    strat = make_osmium_stable(fv_anchor=float(fv_anchor), edge=10)
    pnls = []
    for seed in range(n_seeds):
        sim = FVReplaySim(
            OSMIUM, n_ticks=len(fv_trace), seed=seed, strategy=strat,
            fv_trace=fv_trace, fv0=fv_trace[0],
        )
        sim.run()
        pnls.append(sim.summary()['final_mtm_pnl'])
    return fv_anchor, pnls


def run_pepper_seeds(fv_trace, n_seeds=20):
    strat = make_pepper_trending()
    pnls = []
    for seed in range(n_seeds):
        sim = FVReplaySim(
            PEPPER, n_ticks=len(fv_trace), seed=seed, strategy=strat,
            fv_trace=fv_trace, fv0=fv_trace[0],
        )
        sim.run()
        pnls.append(sim.summary()['final_mtm_pnl'])
    return pnls


def main():
    osm_trace, pep_trace = load_server_fvs()
    print(f"Loaded FV traces: OSMIUM={len(osm_trace)} ticks PEPPER={len(pep_trace)} ticks")
    print(f"OSMIUM FV: first={osm_trace[0]:.3f} last={osm_trace[-1]:.3f} "
          f"mean={statistics.mean(osm_trace):.3f}")
    print(f"PEPPER FV: first={pep_trace[0]:.3f} last={pep_trace[-1]:.3f}")

    # OSMIUM with fv_anchor=10000 (original strategy behavior)
    print("\n== OSMIUM — strat uses fv_anchor=10000 (original 127989 hardcode) ==")
    pnls = run_osmium_seeds(osm_trace, n_seeds=50)
    pnls.sort()
    print(f"  mean={statistics.mean(pnls):.0f}  stdev={statistics.stdev(pnls):.0f}")
    print(f"  p05={pnls[2]:.0f}  p50={pnls[25]:.0f}  p95={pnls[47]:.0f}  max={pnls[-1]:.0f}")

    # OSMIUM with fv_anchor aligned to actual mean (what strategy *could* do)
    print("\n== OSMIUM — strat uses fv_anchor=round(mean(server FV)) ==")
    anchor, pnls = run_osmium_aligned(osm_trace, n_seeds=50)
    pnls.sort()
    print(f"  fv_anchor={anchor}")
    print(f"  mean={statistics.mean(pnls):.0f}  stdev={statistics.stdev(pnls):.0f}")
    print(f"  p05={pnls[2]:.0f}  p50={pnls[25]:.0f}  p95={pnls[47]:.0f}  max={pnls[-1]:.0f}")

    print("\n== PEPPER — replay server PEPPER FV ==")
    pnls = run_pepper_seeds(pep_trace, n_seeds=20)
    pnls.sort()
    print(f"  mean={statistics.mean(pnls):.0f}  stdev={statistics.stdev(pnls):.0f}")
    print(f"  p05={pnls[0]:.0f}  p50={pnls[10]:.0f}  p95={pnls[18]:.0f}  max={pnls[-1]:.0f}")
    print(f"  server=7577  ratio={statistics.mean(pnls)/7577:.2%}")


if __name__ == '__main__':
    main()
