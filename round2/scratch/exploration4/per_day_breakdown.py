"""Per-day OSM/PEP PnL breakdown comparing iter23 vs iter25_tb1."""
from __future__ import annotations
import subprocess, re, pathlib, tempfile

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
    tmpdir = pathlib.Path(tempfile.mkdtemp())
    iter23 = tmpdir / "iter23.py"; rewrite(ROOT / "ROUND_2" / "iter23_trader.py", iter23)
    iter25 = tmpdir / "iter25.py"; rewrite(ROOT / "exploration4" / "iter25_tb1.py", iter25)

    print(f"{'day':<8} {'trader':<12} {'OSM':>9} {'PEP':>9} {'TOTAL':>9}")
    print('-' * 55)
    for day in ("2--1", "2-0", "2-1"):
        o23, p23, t23 = run_bt(iter23, day)
        o25, p25, t25 = run_bt(iter25, day)
        print(f"{day:<8} iter23       {o23:>9.0f} {p23:>9.0f} {t23:>9.0f}")
        print(f"{day:<8} tb1          {o25:>9.0f} {p25:>9.0f} {t25:>9.0f}")
        print(f"{day:<8} Δ (tb1-23)   {o25-o23:>+9.0f} {p25-p23:>+9.0f} {t25-t23:>+9.0f}")
        print()


if __name__ == "__main__":
    main()
