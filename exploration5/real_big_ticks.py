"""Redo: find single-tick PnL swings using the CSV's actual cumulative profit_and_loss.
Aggregate OSM + PEP correctly.
"""
from __future__ import annotations
import json, io, csv, pathlib
import numpy as np

LOGS = {
    'iter23-303257 (9231)': '/tmp/prosperity_logs/303257/312201.json',
    'iter23-303280 (9514)': '/tmp/prosperity_logs/303280/312224.json',
    'tb1-313880 (9568)': '/tmp/prosperity_logs/313880/322847.json',
    'iter26-316247 (9890)': '/tmp/prosperity_logs/316247/325221.json',
    'iter26-316195 (9411)': '/tmp/prosperity_logs/316195/325169.json',
}


def main():
    for label, path in LOGS.items():
        d = json.load(open(path))
        act = csv.DictReader(io.StringIO(d['activitiesLog']), delimiter=';')
        # (ts, product) -> pnl
        pnl_map = {}
        for r in act:
            try: ts = int(r['timestamp'])
            except: continue
            try: pnl = float(r.get('profit_and_loss', 0))
            except: pnl = 0
            pnl_map[(ts, r['product'])] = pnl

        all_ts = sorted(set(ts for ts, _ in pnl_map))
        total_pnl = []
        for ts in all_ts:
            o = pnl_map.get((ts, 'ASH_COATED_OSMIUM'), 0)
            p = pnl_map.get((ts, 'INTARIAN_PEPPER_ROOT'), 0)
            total_pnl.append((ts, o + p))

        # Single-tick deltas (only where ts gap == 100)
        deltas = []
        for i in range(1, len(total_pnl)):
            gap = total_pnl[i][0] - total_pnl[i-1][0]
            if gap == 100:
                deltas.append((total_pnl[i][0], total_pnl[i][1] - total_pnl[i-1][1]))

        print(f"\n=== {label} ===")
        top = sorted(deltas, key=lambda x: -x[1])[:10]
        print("  Top 10 positive single-tick Δ (OSM+PEP cumulative):")
        for ts, d_ in top:
            print(f"    ts={ts}  Δ=${d_:+.1f}")
        top_neg = sorted(deltas, key=lambda x: x[1])[:5]
        print("  Top 5 negative:")
        for ts, d_ in top_neg:
            print(f"    ts={ts}  Δ=${d_:+.1f}")
        # Distribution
        arr = np.array([d for _, d in deltas])
        print(f"  n={len(arr)}  max={arr.max():.1f}  min={arr.min():.1f}  mean={arr.mean():.2f}")
        print(f"  Count of |Δ|≥500: {np.sum(np.abs(arr) >= 500)}")
        print(f"  Count of Δ≥500: {np.sum(arr >= 500)}")
        print(f"  Count of Δ≥300: {np.sum(arr >= 300)}")
        print(f"  Count of Δ≥200: {np.sum(arr >= 200)}")


if __name__ == "__main__":
    main()
