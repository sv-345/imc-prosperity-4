"""Backtest iter28_combo vs iter25_tb1 baseline and iter26_c4_best."""
import sys, importlib
from pathlib import Path

ROOT = Path("/Users/svelaga/Documents/IMC Prosperity")
BT_ROOT = ROOT / "chrispyroberts-imc-prosperity-4/backtester"
DATA_ROOT = ROOT / "chrispyroberts-imc-prosperity-4/data"
sys.path.insert(0, str(BT_ROOT))
sys.path.insert(0, str(ROOT / "exploration6"))
sys.path.insert(0, str(ROOT / "exploration5"))
sys.path.insert(0, str(ROOT / "exploration4"))

from prosperity3bt import runner as rnr
import prosperity3bt.datamodel as _dm
sys.modules.setdefault("datamodel", _dm)
from prosperity3bt.file_reader import FileSystemReader
from prosperity3bt.models import TradeMatchingMode

reader = FileSystemReader(DATA_ROOT)


def run(name):
    m = importlib.import_module(name)
    importlib.reload(m)
    per = {}
    for day in (-1, 0, 1):
        trader = m.Trader()
        res = rnr.run_backtest(trader, reader, 2, day, False, TradeMatchingMode.all, True, False)
        last = res.activity_logs[-1].timestamp
        pnl = 0.0
        for row in reversed(res.activity_logs):
            if row.timestamp != last: break
            pnl += row.columns[-1]
        per[day] = pnl
    return per


base = run("iter25_tb1")
c4 = run("iter26_c4_best")
combo = run("iter28_combo")

bt = sum(base.values())
ct = sum(c4.values())
mt = sum(combo.values())
print("="*70)
print(f"iter25_tb1 (baseline):  3-day = {bt:>10,.0f}")
print(f"iter26_c4_best:         3-day = {ct:>10,.0f}  Δ vs tb1 = {ct-bt:+,.0f}")
print(f"iter28_combo (k5+c4):   3-day = {mt:>10,.0f}  Δ vs tb1 = {mt-bt:+,.0f}  Δ vs c4 = {mt-ct:+,.0f}")
print()
print(f"Per day:")
for d in (-1, 0, 1):
    print(f"  day {d:>2}: tb1={base[d]:>9,.0f}  c4={c4[d]:>9,.0f} (Δ={c4[d]-base[d]:+,.0f})  combo={combo[d]:>9,.0f} (Δ_tb1={combo[d]-base[d]:+,.0f})")
