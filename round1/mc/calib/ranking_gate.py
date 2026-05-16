"""Ranking gate: does calibrated MC predict server ranking?

Known server result:
    127989  (submitted):  OSM 3144 + PEP 7577 = 10721
    v15     (submitted):  OSM 2983 + PEP 7577 = 10560   (−161 vs 127989)

Server says: 127989 > v15. (By −161 on OSM.)

With UNCALIBRATED MC (old taker params), we predicted v15 > 127989 by +8000.
That miscall motivated this rework. Now run both through calibrated MC
(OSM rate=0.120 qty=(3,10); PEP rate=0.015 qty=(3,8)) across many seeds and
check if the sign of the prediction reverses.

Pass criterion:
    mean_pnl(127989) > mean_pnl(v15) per seed   (paired comparison)
Fail criterion:
    mean_pnl(127989) < mean_pnl(v15)  → MC still wrong → re-examine model.
"""
from __future__ import annotations
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from synth_replay import _load_trader_from_path, run_session


P127989 = ("<repo>/"
           "ROUND_1/submissions/127989/127989.py")
V15 = ("<repo>/"
       "ROUND_1/submissions/v15_wall_aware/v15_wall_aware.py")

OSM_PARAMS = {"taker_rate": 0.140, "qty_range": (2, 8)}
PEP_PARAMS = {"taker_rate": 0.020, "qty_range": (3, 8)}


def run_both(path, n_seeds=50):
    osm, pep = [], []
    for s in range(n_seeds):
        t = _load_trader_from_path(path)
        osm.append(run_session(t, "ASH_COATED_OSMIUM", seed=s, **OSM_PARAMS))
        t = _load_trader_from_path(path)
        pep.append(run_session(t, "INTARIAN_PEPPER_ROOT", seed=s, **PEP_PARAMS))
    return osm, pep


def summarize(name, osm, pep):
    osm_pnls = [r.pnl for r in osm]
    pep_pnls = [r.pnl for r in pep]
    totals = [o + p for o, p in zip(osm_pnls, pep_pnls)]
    print(f"== {name} (n={len(osm)}) ==")
    print(f"  OSM mean={statistics.mean(osm_pnls):.0f} std={statistics.stdev(osm_pnls):.0f}")
    print(f"  PEP mean={statistics.mean(pep_pnls):.0f} std={statistics.stdev(pep_pnls):.0f}")
    print(f"  TOTAL mean={statistics.mean(totals):.0f} std={statistics.stdev(totals):.0f}  "
          f"p05={sorted(totals)[int(len(totals)*0.05)]:.0f}  "
          f"p95={sorted(totals)[int(len(totals)*0.95)]:.0f}")
    return osm_pnls, pep_pnls, totals


def main():
    n_seeds = 50
    print(f"Calibrated MC (OSM rate=0.12 qty=(3,10); PEP rate=0.015 qty=(3,8)), {n_seeds} seeds\n")

    o_a, p_a = run_both(P127989, n_seeds)
    a_osm, a_pep, a_tot = summarize("127989", o_a, p_a)

    o_b, p_b = run_both(V15, n_seeds)
    b_osm, b_pep, b_tot = summarize("v15_wall_aware", o_b, p_b)

    # Paired diff (same seeds: b - a)
    d_osm = [b - a for a, b in zip(a_osm, b_osm)]
    d_pep = [b - a for a, b in zip(a_pep, b_pep)]
    d_tot = [b - a for a, b in zip(a_tot, b_tot)]
    print("\n== Paired diff (v15 − 127989) ==")
    print(f"  OSM diff mean={statistics.mean(d_osm):+.0f} std={statistics.stdev(d_osm):.0f}  "
          f"win-rate={sum(1 for d in d_osm if d > 0)}/{len(d_osm)}")
    print(f"  PEP diff mean={statistics.mean(d_pep):+.0f} std={statistics.stdev(d_pep):.0f}  "
          f"win-rate={sum(1 for d in d_pep if d > 0)}/{len(d_pep)}")
    print(f"  TOT diff mean={statistics.mean(d_tot):+.0f} std={statistics.stdev(d_tot):.0f}  "
          f"win-rate={sum(1 for d in d_tot if d > 0)}/{len(d_tot)}")

    # Decision
    print("\n=== RANKING GATE ===")
    print("Server ground truth: 127989 beats v15 by 161 on 1 session.")
    mc_verdict = "v15 > 127989" if statistics.mean(d_tot) > 0 else "127989 >= v15"
    match = "MATCHES server (PASS)" if statistics.mean(d_tot) <= 0 else "REVERSED vs server (FAIL)"
    print(f"MC says: {mc_verdict}  →  {match}")


if __name__ == "__main__":
    main()
