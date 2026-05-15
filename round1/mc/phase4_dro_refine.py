"""Phase 4 DRO — refinement sweep.

From initial sweep: OSMIUM edge=18 beats edge=8–16 monotonically; min_inside_qty=15
saturates. PEPPER trending sq=4 ~= sq=8 (within noise). Now:

  1. Extend OSMIUM edge to {16, 18, 20, 22, 24} to find peak.
  2. Increase n_seeds to 100 for final candidates.
  3. Check PEPPER sq ∈ {2, 4, 6, 8} with more seeds.
"""
from __future__ import annotations
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from phase4_dro import (
    scenarios_for_osmium, scenarios_for_pepper, run_grid, summarize, print_summary,
    make_pepper_trending_sq,
)
from strategies_r1 import make_osmium_stable

N_SEEDS = 100

# OSMIUM: extend edge, keep mi=15
osm_grid = {
    f"edge={e:2d},mi=15": make_osmium_stable(fv_anchor=10000.0, edge=e, min_inside_qty=15, limit=80)
    for e in (12, 14, 16, 18, 20, 22, 24)
}

print(f"Phase 4 DRO refinement — OSMIUM edge sweep (mi=15 fixed, {N_SEEDS} seeds)")
t0 = time.time()
osm_scenarios = scenarios_for_osmium(None)
osm_results = run_grid(osm_grid, osm_scenarios, "ASH_COATED_OSMIUM", 80, N_SEEDS)
osm_summary = summarize(osm_results)
print_summary(osm_summary, "OSMIUM refined (ranked by min-scenario mean)")
print(f"  total time: {time.time()-t0:.1f}s")

# PEPPER: finer sell_qty grid
pep_grid = {
    f"trend,sq={sq:2d}": make_pepper_trending_sq(sell_qty=sq, accum_thresh=70, limit=80, wall_offset=10)
    for sq in (2, 3, 4, 5, 6, 8, 10)
}

print(f"\nPhase 4 DRO refinement — PEPPER sell_qty sweep ({N_SEEDS} seeds)")
t0 = time.time()
pep_scenarios = scenarios_for_pepper(None)
pep_results = run_grid(pep_grid, pep_scenarios, "INTARIAN_PEPPER_ROOT", 80, N_SEEDS)
pep_summary = summarize(pep_results)
print_summary(pep_summary, "PEPPER refined (ranked by min-scenario mean)")
print(f"  total time: {time.time()-t0:.1f}s")

# ---- Recommendation ----
osm_dro = max(osm_summary, key=lambda c: osm_summary[c]["min_mean"])
osm_ev  = max(osm_summary, key=lambda c: osm_summary[c]["per_scen_mean"]["S1_base"])
pep_dro = max(pep_summary, key=lambda c: pep_summary[c]["min_mean"])
pep_ev  = max(pep_summary, key=lambda c: pep_summary[c]["per_scen_mean"]["S1_base"])

print("\n=== Final recommendation ===")
print(f"OSMIUM  EV-optimal:  {osm_ev}")
print(f"OSMIUM  DRO-optimal: {osm_dro}")
print(f"PEPPER  EV-optimal:  {pep_ev}")
print(f"PEPPER  DRO-optimal: {pep_dro}")
