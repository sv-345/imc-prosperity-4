"""Phase 4 DRO — find the OSMIUM edge peak.

Refinement showed monotone improvement up to edge=24. Hypothesis: once the
edge quote is below the bid wall (fv-10=9990), it never fills, so PnL is
entirely from the penny-jump mi_qty component. Beyond that, edge doesn't
matter.

Test 1: very deep edges (30, 40, 50, 80) — should plateau.
Test 2: large mi_qty (40, 60, 80) — maximize penny-jump allocation.
"""
from __future__ import annotations
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from phase4_dro import scenarios_for_osmium, run_grid, summarize, print_summary
from strategies_r1 import make_osmium_stable

N_SEEDS = 80

grid = {}
# Deep edge series
for e in (24, 30, 40, 50, 80):
    grid[f"e={e:2d},mi=15"] = make_osmium_stable(fv_anchor=10000.0, edge=e, min_inside_qty=15, limit=80)
# Large mi series at edge=24
for mi in (15, 30, 50, 80):
    grid[f"e=24,mi={mi:2d}"] = make_osmium_stable(fv_anchor=10000.0, edge=24, min_inside_qty=mi, limit=80)
# Large mi at edge=10 for comparison
for mi in (15, 30, 50, 80):
    grid[f"e=10,mi={mi:2d}"] = make_osmium_stable(fv_anchor=10000.0, edge=10, min_inside_qty=mi, limit=80)

print(f"Phase 4 peak finder — OSMIUM ({N_SEEDS} seeds, {len(grid)} configs)")
t0 = time.time()
scen = scenarios_for_osmium(None)
results = run_grid(grid, scen, "ASH_COATED_OSMIUM", 80, N_SEEDS)
summary = summarize(results)
print_summary(summary, "OSMIUM peak finder")
print(f"  total: {time.time()-t0:.1f}s")

osm_dro = max(summary, key=lambda c: summary[c]["min_mean"])
osm_ev  = max(summary, key=lambda c: summary[c]["per_scen_mean"]["S1_base"])
print(f"\nEV-optimal:  {osm_ev} (baseline={summary[osm_ev]['per_scen_mean']['S1_base']:.0f})")
print(f"DRO-optimal: {osm_dro} (min={summary[osm_dro]['min_mean']:.0f})")
