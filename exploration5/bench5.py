"""Bench: compare each candidate vs tb1 baseline across 3 R2 training days."""
from __future__ import annotations
import sys, subprocess, pathlib, re, tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "chrispyroberts-imc-prosperity-4" / "data"
BT = ROOT / "chrispyroberts-imc-prosperity-4" / "backtester" / ".venv" / "bin" / "prosperity3bt"


def rewrite(src, dst):
    t = src.read_text()
    t = re.sub(r"^from datamodel import", "from prosperity3bt.datamodel import", t, flags=re.M)
    dst.write_text(t)


def run_bt(path, day):
    cmd = [str(BT), str(path), day, "--data", str(DATA), "--no-out"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    out = r.stdout + r.stderr
    osm = pep = tot = None
    for line in out.splitlines():
        m = re.search(r"ASH_COATED_OSMIUM:\s*([-\d,]+\.?\d*)", line)
        if m: osm = float(m.group(1).replace(",", ""))
        m = re.search(r"INTARIAN_PEPPER_ROOT:\s*([-\d,]+\.?\d*)", line)
        if m: pep = float(m.group(1).replace(",", ""))
        m = re.search(r"Total profit:\s*([-\d,]+\.?\d*)", line)
        if m: tot = float(m.group(1).replace(",", ""))
    return osm, pep, tot


def main():
    cands = sys.argv[1:] if len(sys.argv) > 1 else [
        "exploration4/iter25_tb1.py",
        "exploration5/iter26_c1_outer_edge.py",
        "exploration5/iter26_c2_size_boost.py",
        "exploration5/iter26_c3_middle_layer.py",
        "exploration5/iter26_c4_conditional_take.py",
    ]
    tmpdir = pathlib.Path(tempfile.mkdtemp(prefix="exp5_"))

    # Baselines
    iter23_tmp = tmpdir / "iter23.py"
    rewrite(ROOT / "ROUND_2" / "iter23_trader.py", iter23_tmp)
    tb1_tmp = tmpdir / "tb1.py"
    rewrite(ROOT / "exploration4" / "iter25_tb1.py", tb1_tmp)

    base23 = []; baset = []
    for day in ("2--1", "2-0", "2-1"):
        _, _, t23 = run_bt(iter23_tmp, day)
        _, _, tt = run_bt(tb1_tmp, day)
        base23.append(t23); baset.append(tt)
    tot23 = sum(base23); tott = sum(baset)
    print(f"iter23 3-day: {tot23:.0f}")
    print(f"tb1    3-day: {tott:.0f}  (Δ vs iter23: {tott-tot23:+.0f})")

    print(f"\n{'candidate':<45} {'d=-1':>9} {'d=0':>9} {'d=1':>9} {'3-day':>9} {'Δ vs tb1':>9} {'Δ vs iter23':>13}")
    for c in cands:
        p = ROOT / c
        staged = tmpdir / p.name
        rewrite(p, staged)
        row = []; tot = 0
        for day in ("2--1", "2-0", "2-1"):
            _, _, t = run_bt(staged, day)
            row.append(t or 0)
            tot += t or 0
        dt_tb1 = tot - tott
        dt_23 = tot - tot23
        print(f"{p.name:<45} {row[0]:>9.0f} {row[1]:>9.0f} {row[2]:>9.0f} {tot:>9.0f} {dt_tb1:>+9.0f} {dt_23:>+13.0f}")


if __name__ == "__main__":
    main()
