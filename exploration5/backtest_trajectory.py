"""Run iter23 and iter25_tb1 via prosperity3bt on day 0, capture trajectory,
identify per-window differences.

prosperity3bt can dump a log file; parse that for per-tick PnL.
"""
from __future__ import annotations
import subprocess, re, pathlib, tempfile, json, io, csv

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "chrispyroberts-imc-prosperity-4" / "data"
BT = ROOT / "chrispyroberts-imc-prosperity-4" / "backtester" / ".venv" / "bin" / "prosperity3bt"


def rewrite_imports(src, dst):
    t = src.read_text()
    t = re.sub(r"^from datamodel import", "from prosperity3bt.datamodel import", t, flags=re.M)
    dst.write_text(t)


def run_bt_and_capture(trader_path, day):
    tmpdir = pathlib.Path(tempfile.mkdtemp())
    staged = tmpdir / trader_path.name
    rewrite_imports(trader_path, staged)
    out_log = tmpdir / "out.log"
    cmd = [str(BT), str(staged), day, "--data", str(DATA), "--out", str(out_log)]
    subprocess.run(cmd, capture_output=True, text=True)
    return out_log


def parse_log(log_path):
    """Extract per-timestamp OSM/PEP PnL from the backtester's output log."""
    # The out.log is a JSON with activitiesLog inside
    text = log_path.read_text()
    # Try to find an activitiesLog CSV section
    # Simpler: the log might be a CSV-like activities dump
    # Actually prosperity3bt outputs a log file with activities section
    # Let me check format
    return text[:500]


def main():
    iter23 = ROOT / "ROUND_2" / "iter23_trader.py"
    tb1 = ROOT / "exploration4" / "iter25_tb1.py"

    for day in ("2-0",):   # just day 0 first
        log23 = run_bt_and_capture(iter23, day)
        log25 = run_bt_and_capture(tb1, day)
        print(f"iter23 log: {log23}, size: {log23.stat().st_size}")
        print(f"tb1 log: {log25}, size: {log25.stat().st_size}")
        print("iter23 log head:", parse_log(log23))


if __name__ == "__main__":
    main()
