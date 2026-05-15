"""Variant A (window-aware) vs Variant B (always-on K) vs iter25_tb1 baseline.

Windows: ts 34,300-48,100 and 76,100-90,100 per day.

Additionally, test a scaled-to-training variant (×10 windows) since training days
are 10× longer than server sessions.
"""
import sys, os, importlib
from pathlib import Path

ROOT = Path("/Users/svelaga/Documents/IMC Prosperity")
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


def run_one(algo_module_name, env=None):
    if env:
        for k, v in env.items():
            os.environ[k] = str(v)
    m = importlib.import_module(algo_module_name)
    importlib.reload(m)
    per_day = {}
    for day in (-1, 0, 1):
        trader = m.Trader()
        res = rnr.run_backtest(trader, reader, 2, day, False, TradeMatchingMode.all, True, False)
        last = res.activity_logs[-1].timestamp
        pnl = 0.0; per = {}
        for row in reversed(res.activity_logs):
            if row.timestamp != last: break
            per[row.columns[2]] = row.columns[-1]
            pnl += row.columns[-1]
        per_day[day] = (pnl, per)
    return per_day


# Baseline
print("Baseline: iter25_tb1")
baseline = run_one("iter25_tb1")
for day, (pnl, per) in baseline.items():
    print(f"  day {day:>2}: total={pnl:>10,.0f}")
b_total = sum(v[0] for v in baseline.values())
print(f"  3-day total: {b_total:,.0f}")


def report(name, r):
    t = sum(v[0] for v in r.values())
    d = t - b_total
    print(f"\n{name}")
    print(f"  3-day total: {t:,.0f}  Δ vs baseline: {d:+,.0f}")
    for day in (-1, 0, 1):
        dd = r[day][0] - baseline[day][0]
        print(f"    day {day:>2}: Δ={dd:>+7,.0f}")
    return t, d


# Variant B (always-on) — already known: K=3 → +17, K=5 → -104
print("\n=== Variant B reference (always-on OSM_K=3) ===")
for k in (3, 5):
    r = run_one("iter27_phase3", env={"OSM_PHASE3_K": k, "PEP_PHASE3_K": 1})
    report(f"iter27_phase3 K={k}", r)

# Variant A — server-scale windows (ts 34.3K-48.1K, 76.1K-90.1K — 2.78% of day)
print("\n=== Variant A: server-scale windows (2.78% of training day) ===")
# Need to ensure iter27_variant_a loads with correct _WINDOWS = ((34300, 48100), (76100, 90100))
# This is hardcoded; just set Ks.
for kw in (3, 5):
    r = run_one("iter27_variant_a", env={
        "OSM_PHASE3_K_WINDOW": kw, "OSM_PHASE3_K_OUTSIDE": 1,
        "PEP_PHASE3_K_WINDOW": 1, "PEP_PHASE3_K_OUTSIDE": 1,
    })
    report(f"Variant A server-scale OSM_K_window={kw} outside=1", r)

# Also run the INVERSE: widen outside windows (if windows are sell-biased,
# maybe outside is where widening actually helps)
print("\n=== Variant A inverse: widen outside windows ===")
for ko in (3, 5):
    r = run_one("iter27_variant_a", env={
        "OSM_PHASE3_K_WINDOW": 1, "OSM_PHASE3_K_OUTSIDE": ko,
        "PEP_PHASE3_K_WINDOW": 1, "PEP_PHASE3_K_OUTSIDE": 1,
    })
    report(f"Variant A inverse OSM_K_window=1 outside={ko}", r)
