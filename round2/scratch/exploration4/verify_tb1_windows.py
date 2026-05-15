"""Verify iter25_tb1 (dynamic_fv anchor) captures gains in Window 2
by running it against iter23 on a single training day and inspecting
per-window PnL.
"""
from __future__ import annotations
import subprocess, re, pathlib, tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "chrispyroberts-imc-prosperity-4" / "data"
BT = ROOT / "chrispyroberts-imc-prosperity-4" / "backtester" / ".venv" / "bin" / "prosperity3bt"


def rewrite(src, dst):
    t = src.read_text()
    t = re.sub(r"^from datamodel import", "from prosperity3bt.datamodel import", t, flags=re.M)
    dst.write_text(t)


def run_bt_output_capture(path, day):
    cmd = [str(BT), str(path), day, "--data", str(DATA), "--out", "/tmp/bt_out.log"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    # read the log
    out = pathlib.Path("/tmp/bt_out.log").read_text() if pathlib.Path("/tmp/bt_out.log").exists() else ""
    return out


def main():
    tmpdir = pathlib.Path(tempfile.mkdtemp())
    iter23 = tmpdir / "iter23.py"
    iter25 = tmpdir / "iter25.py"
    rewrite(ROOT / "ROUND_2" / "iter23_trader.py", iter23)
    rewrite(ROOT / "exploration4" / "iter25_tb1.py", iter25)

    for day in ("2-0", "2-1"):
        print(f"\n==== day {day} ====")
        for name, path in (("iter23", iter23), ("iter25_tb1", iter25)):
            out = run_bt_output_capture(path, day)
            # Grab OSM profit per-section or total
            for l in out.splitlines()[-20:]:
                if 'ASH_COATED_OSMIUM' in l or 'INTARIAN_PEPPER_ROOT' in l or 'Total' in l:
                    print(f"  {name}: {l.strip()}")


if __name__ == "__main__":
    main()
