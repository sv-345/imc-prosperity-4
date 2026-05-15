"""Benchmark iter23 vs iter24 on R2 training days using prosperity3bt.

Rewrites 'from datamodel import ...' to 'from prosperity3bt.datamodel import ...'
in a temp copy, then invokes prosperity3bt programmatically.
"""
from __future__ import annotations
import subprocess
import pathlib
import re
import tempfile
import shutil
import json
import re as re_mod

ROOT = pathlib.Path(__file__).resolve().parent.parent
R2 = ROOT / "ROUND_2"
DATA = ROOT / "chrispyroberts-imc-prosperity-4" / "data"
BT_VENV = ROOT / "chrispyroberts-imc-prosperity-4" / "backtester" / ".venv" / "bin"
BT = BT_VENV / "prosperity3bt"


def rewrite_imports(src: pathlib.Path, dst: pathlib.Path) -> None:
    text = src.read_text()
    text = re.sub(r"^from datamodel import", "from prosperity3bt.datamodel import", text, flags=re.M)
    text = re.sub(r"^import datamodel\b", "import prosperity3bt.datamodel as datamodel", text, flags=re.M)
    dst.write_text(text)


def run_bt(trader_path: pathlib.Path, day_arg: str) -> dict:
    """Run prosperity3bt and parse output for OSM/PEP PnL."""
    cmd = [str(BT), str(trader_path), day_arg, "--data", str(DATA), "--no-out"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    out = result.stdout + result.stderr
    # Parse tail summary
    osm_pnl = None
    pep_pnl = None
    total_pnl = None
    for line in out.splitlines():
        m = re.search(r"^\s*ASH_COATED_OSMIUM:\s*([-\d,]+\.?\d*)", line)
        if m: osm_pnl = float(m.group(1).replace(",", ""))
        m = re.search(r"^\s*INTARIAN_PEPPER_ROOT:\s*([-\d,]+\.?\d*)", line)
        if m: pep_pnl = float(m.group(1).replace(",", ""))
        m = re.search(r"^\s*Total profit:\s*([-\d,]+\.?\d*)", line)
        if m: total_pnl = float(m.group(1).replace(",", ""))
    return dict(osm=osm_pnl, pep=pep_pnl, total=total_pnl, raw=out[-500:])


def main() -> None:
    tmpdir = pathlib.Path(tempfile.mkdtemp(prefix="iter_bench_"))
    iter23_src = R2 / "iter23_trader.py"
    iter24_src = R2 / "iter24_dynamic_gate_trader.py"
    iter23_tmp = tmpdir / "iter23.py"
    iter24_tmp = tmpdir / "iter24.py"
    rewrite_imports(iter23_src, iter23_tmp)
    rewrite_imports(iter24_src, iter24_tmp)

    print("iter23:", iter23_tmp)
    print("iter24:", iter24_tmp)

    results = {"iter23": {}, "iter24": {}}
    for day in ("2--1", "2-0", "2-1"):
        print(f"\n==== day {day} ====")
        for name, path in (("iter23", iter23_tmp), ("iter24", iter24_tmp)):
            r = run_bt(path, day)
            results[name][day] = r
            print(f"  {name}: OSM={r['osm']}  PEP={r['pep']}  total={r['total']}")

    # Summary
    print("\n\n==== DELTA (iter24 - iter23) per day ====")
    total_delta_osm = 0; total_delta_pep = 0; total_delta_total = 0
    for day in ("2--1", "2-0", "2-1"):
        r23 = results["iter23"][day]
        r24 = results["iter24"][day]
        if r23["osm"] is None or r24["osm"] is None:
            print(f"  day {day}: MISSING")
            continue
        dosm = r24["osm"] - r23["osm"]
        dpep = r24["pep"] - r23["pep"]
        dtot = r24["total"] - r23["total"]
        total_delta_osm += dosm
        total_delta_pep += dpep
        total_delta_total += dtot
        print(f"  day {day}: ΔOSM={dosm:+.0f}  ΔPEP={dpep:+.0f}  Δtotal={dtot:+.0f}")
    print(f"\n  3-day Δtotal: {total_delta_total:+.0f}  (ΔOSM={total_delta_osm:+.0f}, ΔPEP={total_delta_pep:+.0f})")
    print(f"  avg per day: {total_delta_total/3:+.0f}")

    # Save full JSON
    with open(ROOT / "exploration" / "bench_iter23_vs_24.json", "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nwrote {ROOT / 'exploration' / 'bench_iter23_vs_24.json'}")


if __name__ == "__main__":
    main()
