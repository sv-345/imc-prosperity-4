"""Sweep PEP_SKIP_THRESH to find best setting."""
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

def run(name, env=None):
    if env:
        for k, v in env.items(): os.environ[k] = str(v)
    m = importlib.import_module(name); importlib.reload(m)
    per = {}
    for day in (-1, 0, 1):
        trader = m.Trader()
        res = rnr.run_backtest(trader, reader, 2, day, False, TradeMatchingMode.all, True, False)
        last = res.activity_logs[-1].timestamp
        pnl = 0.0; per_prod = {}
        for row in reversed(res.activity_logs):
            if row.timestamp != last: break
            per_prod[row.columns[2]] = row.columns[-1]
            pnl += row.columns[-1]
        per[day] = (pnl, per_prod)
    return per

base = run("iter25_tb1")
bt = sum(v[0] for v in base.values())
print(f"iter25_tb1 baseline: {bt:,.0f}")
print(f"  PEP: {sum(v[1].get('INTARIAN_PEPPER_ROOT',0) for v in base.values()):,.0f}")

print()
for skip in (0, 1, 2, 3):
    r = run("iter29_pep", env={"PEP_SKIP_THRESH": skip, "PEP_AGG_THRESH": 3})
    t = sum(v[0] for v in r.values())
    pep = sum(v[1].get('INTARIAN_PEPPER_ROOT', 0) for v in r.values())
    pep_b = sum(v[1].get('INTARIAN_PEPPER_ROOT', 0) for v in base.values())
    d = t - bt
    per_day = [r[d][0] - base[d][0] for d in (-1, 0, 1)]
    print(f"PEP_SKIP={skip}: total={t:,.0f}  Δ={d:+,.0f}  ΔPEP={pep-pep_b:+,.0f}  per-day={per_day}")
