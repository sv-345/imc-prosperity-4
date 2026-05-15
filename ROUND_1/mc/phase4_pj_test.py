"""Test penny-jump-only variants + compare to deep-edge variants."""
from __future__ import annotations
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from phase4_dro import scenarios_for_osmium, run_grid, summarize, print_summary
from strategies_r1 import make_osmium_stable
from strategies_pj_only import make_osmium_pj_only

N_SEEDS = 100

grid = {}
# PJ-only at various sizes
for ps in (5, 8, 10, 12, 15, 20, 30):
    grid[f"pj_only,pj={ps:2d}"] = make_osmium_pj_only(fv_anchor=10000.0, pj_size=ps, limit=80)
# Reference: e=80 dual
grid["ref_e=80,mi=15"] = make_osmium_stable(fv_anchor=10000.0, edge=80, min_inside_qty=15, limit=80)
grid["ref_e=120,mi=15"] = make_osmium_stable(fv_anchor=10000.0, edge=120, min_inside_qty=15, limit=80)

print(f"Phase 4 PJ-only test ({N_SEEDS} seeds)")
t0 = time.time()
scen = scenarios_for_osmium(None)
results = run_grid(grid, scen, "ASH_COATED_OSMIUM", 80, N_SEEDS)
summary = summarize(results)
print_summary(summary, "OSMIUM pj-only vs deep-edge")
print(f"  total: {time.time()-t0:.1f}s")

best = max(summary, key=lambda c: summary[c]["min_mean"])
print(f"\nDRO-optimal: {best} (min={summary[best]['min_mean']:.0f}, baseline={summary[best]['per_scen_mean']['S1_base']:.0f})")
