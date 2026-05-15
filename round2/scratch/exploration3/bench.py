"""Backtest harness for exploration3. One variant vs iter23 baseline.

Usage: python3 bench.py <candidate_file.py> [<candidate2.py> ...]

Rewrites 'from datamodel import' -> 'from prosperity3bt.datamodel import'.
Runs prosperity3bt on 2-{-1,0,1}. Prints per-day and 3-day delta vs iter23.
"""
from __future__ import annotations
import sys, subprocess, pathlib, re, tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
R2 = ROOT / "ROUND_2"
DATA = ROOT / "chrispyroberts-imc-prosperity-4" / "data"
BT = ROOT / "chrispyroberts-imc-prosperity-4" / "backtester" / ".venv" / "bin" / "prosperity3bt"


def rewrite(src: pathlib.Path, dst: pathlib.Path):
    t = src.read_text()
    t = re.sub(r"^from datamodel import", "from prosperity3bt.datamodel import", t, flags=re.M)
    dst.write_text(t)


def run_bt(path: pathlib.Path, day: str) -> dict:
    cmd = [str(BT), str(path), day, "--data", str(DATA), "--no-out"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    out = r.stdout + r.stderr
    osm = pep = tot = None
    for line in out.splitlines():
        m = re.search(r"^\s*ASH_COATED_OSMIUM:\s*([-\d,]+\.?\d*)", line)
        if m: osm = float(m.group(1).replace(",", ""))
        m = re.search(r"^\s*INTARIAN_PEPPER_ROOT:\s*([-\d,]+\.?\d*)", line)
        if m: pep = float(m.group(1).replace(",", ""))
        m = re.search(r"^\s*Total profit:\s*([-\d,]+\.?\d*)", line)
        if m: tot = float(m.group(1).replace(",", ""))
    return dict(osm=osm, pep=pep, total=tot, raw=out[-300:])


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: bench.py <candidate.py> [<candidate2.py>...]"); return 2
    cands = [pathlib.Path(a) for a in sys.argv[1:]]
    tmpdir = pathlib.Path(tempfile.mkdtemp(prefix="exp3_"))

    iter23_tmp = tmpdir / "iter23.py"
    rewrite(R2 / "iter23_trader.py", iter23_tmp)
    cand_tmps = []
    for c in cands:
        t = tmpdir / c.name
        rewrite(c, t)
        cand_tmps.append((c.name, t))

    days = ("2--1", "2-0", "2-1")
    base = {}
    for d in days:
        base[d] = run_bt(iter23_tmp, d)
    base_total = sum(base[d]["total"] or 0 for d in days)

    print(f"\niter23 baseline 3-day total: {base_total:.0f}\n")
    print(f"{'variant':<40}  {'d=-1':>9}  {'d=0':>9}  {'d=1':>9}  {'3-day':>9}  {'Δ':>8}")
    for name, path in cand_tmps:
        row = []
        tot = 0
        for d in days:
            r = run_bt(path, d)
            row.append(r["total"] or 0)
            tot += r["total"] or 0
        delta = tot - base_total
        print(f"{name:<40}  {row[0]:>9.0f}  {row[1]:>9.0f}  {row[2]:>9.0f}  {tot:>9.0f}  {delta:>+8.0f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
