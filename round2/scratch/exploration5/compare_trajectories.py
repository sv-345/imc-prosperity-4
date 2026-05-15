"""Compare iter23 vs tb1 PnL trajectories from server logs.
Identify where tb1 gains (mechanism working) and where gaps remain.
"""
from __future__ import annotations
import json, io, csv, pathlib
import numpy as np

ITER23_LOGS = [
    '/tmp/prosperity_logs/303257/312201.json',
    '/tmp/prosperity_logs/303280/312224.json',
    '/tmp/prosperity_logs/314059/323026.log',  # .log not .json for these
    '/tmp/prosperity_logs/314132/323099.log',
]
TB1_LOGS = [
    '/tmp/prosperity_logs/313880/322847.json',
    '/tmp/prosperity_logs/313935/322902.json',
    '/tmp/prosperity_logs/313995/322962.json',
]


def load_json(path):
    return json.load(open(path))


def load_pnl_and_mid(d):
    """Return dict ts -> (pnl_total, osm_mid, osm_pnl, pep_mid, pep_pnl)."""
    # PnL per product comes from activitiesLog
    act = csv.DictReader(io.StringIO(d['activitiesLog']), delimiter=';')
    out = {}
    for r in act:
        try: ts = int(r['timestamp'])
        except: continue
        prod = r['product']
        mid = float(r['mid_price']) if r.get('mid_price') else None
        pnl = float(r['profit_and_loss']) if r.get('profit_and_loss') else None
        if ts not in out: out[ts] = {}
        if prod == 'ASH_COATED_OSMIUM':
            out[ts]['osm_mid'] = mid
            out[ts]['osm_pnl'] = pnl
        else:
            out[ts]['pep_mid'] = mid
            out[ts]['pep_pnl'] = pnl
    return out


def main():
    iter23_data = load_pnl_and_mid(load_json(ITER23_LOGS[0]))
    tb1_data = load_pnl_and_mid(load_json(TB1_LOGS[0]))
    tb1_2 = load_pnl_and_mid(load_json(TB1_LOGS[1]))

    # Check that timestamps align
    its = set(iter23_data.keys())
    t1 = set(tb1_data.keys())
    print(f"iter23 ts count: {len(its)}  tb1 ts count: {len(t1)}  common: {len(its & t1)}")

    # Sliding 5000-ts windows: compare per-product OSM PnL
    iter23_profit = load_json(ITER23_LOGS[0])['profit']
    tb1_profit = load_json(TB1_LOGS[0])['profit']
    print(f"iter23 total: ${iter23_profit:.2f}")
    print(f"tb1 total: ${tb1_profit:.2f}")
    print(f"Δ: ${tb1_profit - iter23_profit:+.2f}")

    # Per-5K-ts-window OSM PnL comparison
    print("\n=== Per 5000-ts window: OSM PnL comparison (iter23 vs tb1 sample 1) ===")
    print(f"{'window':<15} {'iter23_osm':>11} {'tb1_osm':>11} {'Δ_osm':>9} {'osm_mid_avg':>11} {'tb1_pep':>9} {'iter23_pep':>11}")
    for b_start in range(0, 100000, 5000):
        b_end = b_start + 5000
        # iter23 values
        osm_pnls_i = [iter23_data[ts].get('osm_pnl') for ts in sorted(iter23_data) if b_start <= ts < b_end]
        osm_pnls_i = [v for v in osm_pnls_i if v is not None]
        pep_pnls_i = [iter23_data[ts].get('pep_pnl') for ts in sorted(iter23_data) if b_start <= ts < b_end]
        pep_pnls_i = [v for v in pep_pnls_i if v is not None]
        mids = [iter23_data[ts].get('osm_mid') for ts in sorted(iter23_data) if b_start <= ts < b_end]
        mids = [v for v in mids if v is not None]

        osm_pnls_t = [tb1_data[ts].get('osm_pnl') for ts in sorted(tb1_data) if b_start <= ts < b_end]
        osm_pnls_t = [v for v in osm_pnls_t if v is not None]
        pep_pnls_t = [tb1_data[ts].get('pep_pnl') for ts in sorted(tb1_data) if b_start <= ts < b_end]
        pep_pnls_t = [v for v in pep_pnls_t if v is not None]

        if not osm_pnls_i or not osm_pnls_t: continue
        iter23_gain = osm_pnls_i[-1] - osm_pnls_i[0]
        tb1_gain = osm_pnls_t[-1] - osm_pnls_t[0]
        pep_gain_i = pep_pnls_i[-1] - pep_pnls_i[0] if pep_pnls_i else 0
        pep_gain_t = pep_pnls_t[-1] - pep_pnls_t[0] if pep_pnls_t else 0
        mid_avg = np.mean(mids) if mids else 0
        print(f"[{b_start:>5d}..{b_end:>5d}] {iter23_gain:>11.1f} {tb1_gain:>11.1f} {tb1_gain-iter23_gain:>+9.1f} {mid_avg:>11.1f} {pep_gain_t:>9.1f} {pep_gain_i:>11.1f}")


if __name__ == "__main__":
    main()
