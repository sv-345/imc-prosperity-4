"""Backtest iter29_window_a, iter29_window_b vs iter25_tb1 and iter27_k5."""
import sys, importlib
from pathlib import Path

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

def run(name):
    m = importlib.import_module(name); importlib.reload(m)
    per = {}
    for day in (-1, 0, 1):
        trader = m.Trader()
        res = rnr.run_backtest(trader, reader, 2, day, False, TradeMatchingMode.all, True, False)
        last = res.activity_logs[-1].timestamp
        pnl = 0.0; prods = {}
        for row in reversed(res.activity_logs):
            if row.timestamp != last: break
            prods[row.columns[2]] = row.columns[-1]
            pnl += row.columns[-1]
        per[day] = (pnl, prods)
    return per

for name in ("iter25_tb1", "iter27_k5", "iter29_window_a", "iter29_window_b"):
    r = run(name)
    t = sum(v[0] for v in r.values())
    pep = sum(v[1].get("INTARIAN_PEPPER_ROOT", 0) for v in r.values())
    osm = sum(v[1].get("ASH_COATED_OSMIUM", 0) for v in r.values())
    print(f"{name:20s}: total={t:>10,.0f}  OSM={osm:>8,.0f}  PEP={pep:>8,.0f}")
