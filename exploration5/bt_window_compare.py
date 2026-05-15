"""Run iter23 and iter25_tb1 via prosperity3bt, parse per-timestamp PnL,
compare per 5K-ts window to identify where tb1 wins vs loses.
"""
from __future__ import annotations
import subprocess, re, pathlib, tempfile, io, csv
import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "chrispyroberts-imc-prosperity-4" / "data"
BT = ROOT / "chrispyroberts-imc-prosperity-4" / "backtester" / ".venv" / "bin" / "prosperity3bt"


def rewrite(src, dst):
    t = src.read_text()
    t = re.sub(r"^from datamodel import", "from prosperity3bt.datamodel import", t, flags=re.M)
    dst.write_text(t)


def run_bt(trader_path, day):
    tmpdir = pathlib.Path(tempfile.mkdtemp())
    staged = tmpdir / trader_path.name
    rewrite(trader_path, staged)
    out_log = tmpdir / "out.log"
    cmd = [str(BT), str(staged), day, "--data", str(DATA), "--out", str(out_log)]
    subprocess.run(cmd, capture_output=True, text=True)
    return out_log


def parse_activities(log_path):
    text = log_path.read_text()
    idx = text.find("Activities log:")
    section = text[idx:].split('\n', 1)[1]
    # find end via looking for lines that don't match CSV pattern
    end = section.find('\n\n')
    if end < 0:
        end = section.find('Trade History')
    if end < 0: end = len(section)
    section = section[:end]
    reader = csv.DictReader(io.StringIO(section), delimiter=';')
    out = {}
    for r in reader:
        try: ts = int(r['timestamp'])
        except: continue
        prod = r['product']
        pnl = None; mid = None
        try: pnl = float(r['profit_and_loss']) if r.get('profit_and_loss') else None
        except: pass
        try: mid = float(r['mid_price']) if r.get('mid_price') else None
        except: pass
        # skip corrupt rows (mid == 0 or negative)
        if mid is not None and mid < 1000: continue
        out[(ts, prod)] = {'mid': mid, 'pnl': pnl}
    return out


def compare(iter23_data, tb1_data, day_label):
    # All timestamps
    all_ts = sorted(set(ts for (ts, _) in iter23_data))
    osm_ts = [ts for ts in all_ts if (ts, 'ASH_COATED_OSMIUM') in iter23_data]

    print(f"\n=== {day_label} — 5K-ts window comparison (iter23 vs tb1 OSM PnL) ===")
    print(f"{'window':<15} {'iter23':>9} {'tb1':>9} {'Δ':>8} {'mid_avg':>9}")
    for b_start in range(0, 1000000, 50000):
        b_end = b_start + 50000
        in_win = [ts for ts in osm_ts if b_start <= ts < b_end]
        if not in_win: continue
        t_lo, t_hi = in_win[0], in_win[-1]
        i23_lo = iter23_data[(t_lo, 'ASH_COATED_OSMIUM')]['pnl']
        i23_hi = iter23_data[(t_hi, 'ASH_COATED_OSMIUM')]['pnl']
        t_lo_k = tb1_data.get((t_lo, 'ASH_COATED_OSMIUM'), {}).get('pnl', 0)
        t_hi_k = tb1_data.get((t_hi, 'ASH_COATED_OSMIUM'), {}).get('pnl', 0)
        i23_g = i23_hi - i23_lo
        t_g = t_hi_k - t_lo_k
        mids = [iter23_data[(ts, 'ASH_COATED_OSMIUM')]['mid'] for ts in in_win if iter23_data[(ts, 'ASH_COATED_OSMIUM')]['mid'] is not None]
        mid_avg = np.mean(mids) if mids else 0
        print(f"[{b_start:>5d}..{b_end:>5d}] {i23_g:>9.1f} {t_g:>9.1f} {t_g-i23_g:>+8.1f} {mid_avg:>9.1f}")


def main():
    iter23 = ROOT / "ROUND_2" / "iter23_trader.py"
    tb1 = ROOT / "exploration4" / "iter25_tb1.py"

    for day in ("2-0", "2-1", "2--1"):
        log23 = run_bt(iter23, day)
        log25 = run_bt(tb1, day)
        d23 = parse_activities(log23)
        d25 = parse_activities(log25)
        compare(d23, d25, day)


if __name__ == "__main__":
    main()
