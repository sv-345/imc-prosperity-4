"""Sweep OSM_PHASE3_K and PEP_PHASE3_K on all 3 R2 days.

Compares each (osm_k, pep_k) combo against iter25_tb1 baseline (k=1/k=1).
"""
import sys, os, importlib
from pathlib import Path
from collections import defaultdict

ROOT = Path("<repo>")
BT_ROOT = ROOT / "chrispyroberts-imc-prosperity-4/backtester"
DATA_ROOT = ROOT / "chrispyroberts-imc-prosperity-4/data"

sys.path.insert(0, str(BT_ROOT))
sys.path.insert(0, str(ROOT / "exploration6"))
sys.path.insert(0, str(ROOT / "exploration4"))

from prosperity3bt import runner as rnr
import prosperity3bt.datamodel as _dm
sys.modules.setdefault("datamodel", _dm)
from prosperity3bt.file_reader import FileSystemReader
from prosperity3bt.models import TradeMatchingMode

reader = FileSystemReader(DATA_ROOT)


def run_one(algo_module_name, osm_k=None, pep_k=None):
    if osm_k is not None:
        os.environ["OSM_PHASE3_K"] = str(osm_k)
    if pep_k is not None:
        os.environ["PEP_PHASE3_K"] = str(pep_k)
    m = importlib.import_module(algo_module_name)
    importlib.reload(m)
    per_day = {}
    for day in (-1, 0, 1):
        trader = m.Trader()
        res = rnr.run_backtest(trader, reader, 2, day, False, TradeMatchingMode.all, True, False)
        last = res.activity_logs[-1].timestamp
        pnl = 0.0
        per = {}
        for row in reversed(res.activity_logs):
            if row.timestamp != last:
                break
            per[row.columns[2]] = row.columns[-1]
            pnl += row.columns[-1]
        per_day[day] = (pnl, per)
    return per_day


# Baseline — iter25_tb1 (no env vars matter for tb1)
print("Baseline: iter25_tb1")
baseline = run_one("iter25_tb1")
for day, (pnl, per) in baseline.items():
    print(f"  day {day:>2}: total={pnl:>10,.0f}  OSM={per.get('ASH_COATED_OSMIUM',0):>9,.0f}  PEP={per.get('INTARIAN_PEPPER_ROOT',0):>9,.0f}")
baseline_total = sum(v[0] for v in baseline.values())
print(f"  3-day total: {baseline_total:,.0f}")

# Sweep
sweep = [
    (1, 1),  # should match baseline (sanity)
    (2, 1), (3, 1), (4, 1), (5, 1), (6, 1),
    (3, 2), (3, 3),
    (5, 2), (5, 3),
    (4, 2),
]
results = {}
for osm_k, pep_k in sweep:
    print(f"\niter27_phase3: OSM_K={osm_k} PEP_K={pep_k}")
    r = run_one("iter27_phase3", osm_k=osm_k, pep_k=pep_k)
    total = sum(v[0] for v in r.values())
    delta = total - baseline_total
    results[(osm_k, pep_k)] = (total, r)
    print(f"  3-day total: {total:,.0f}  Δ vs baseline: {delta:+,.0f}")
    for day in (-1, 0, 1):
        dpnl = r[day][0] - baseline[day][0]
        osmd = r[day][1].get("ASH_COATED_OSMIUM", 0) - baseline[day][1].get("ASH_COATED_OSMIUM", 0)
        pepd = r[day][1].get("INTARIAN_PEPPER_ROOT", 0) - baseline[day][1].get("INTARIAN_PEPPER_ROOT", 0)
        print(f"    day {day:>2}: Δ_total={dpnl:>+7,.0f}  Δ_OSM={osmd:>+7,.0f}  Δ_PEP={pepd:>+7,.0f}")

print("\n\n=== SUMMARY (Δ vs iter25_tb1 3-day baseline) ===")
print(f"{'OSM_K':>6} {'PEP_K':>6} {'Δ total':>10} {'per-day deltas':>30}")
for (osm_k, pep_k), (total, r) in results.items():
    deltas = [r[d][0] - baseline[d][0] for d in (-1, 0, 1)]
    all_pos = all(d > 0 for d in deltas)
    tag = " (all positive)" if all_pos else ""
    print(f"{osm_k:>6} {pep_k:>6} {total - baseline_total:>+10,.0f}  {deltas}{tag}")
