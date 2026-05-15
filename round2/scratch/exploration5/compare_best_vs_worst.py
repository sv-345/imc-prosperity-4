"""Compare iter26 best sample (316247, $9,890) vs worst (316195, $9,411).
Same strategy, different 80% random tape. Find what's different in the best sample.
"""
from __future__ import annotations
import json, io, csv, pathlib
import numpy as np

BEST = '/tmp/prosperity_logs/316247/325221.json'
WORST = '/tmp/prosperity_logs/316195/325169.json'


def load(path):
    d = json.load(open(path))
    act = csv.DictReader(io.StringIO(d['activitiesLog']), delimiter=';')
    osm = []; pep = []
    for r in act:
        try: ts = int(r['timestamp'])
        except: continue
        try: pnl = float(r.get('profit_and_loss', 0))
        except: pnl = 0
        try: mid = float(r.get('mid_price', 0))
        except: mid = 0
        rec = (ts, pnl, mid, r)
        if r['product'] == 'ASH_COATED_OSMIUM': osm.append(rec)
        else: pep.append(rec)
    return osm, pep, d


def main():
    best_osm, best_pep, db = load(BEST)
    worst_osm, worst_pep, dw = load(WORST)
    print(f"Best profit: {db['profit']}")
    print(f"Worst profit: {dw['profit']}")
    print(f"Δ: {db['profit'] - dw['profit']}")

    # Align by ts
    best_osm_pnl = {t: p for t, p, m, _ in best_osm}
    worst_osm_pnl = {t: p for t, p, m, _ in worst_osm}
    best_pep_pnl = {t: p for t, p, m, _ in best_pep}
    worst_pep_pnl = {t: p for t, p, m, _ in worst_pep}

    # Per 50K-ts window: delta
    print("\n50K-ts window: OSM/PEP deltas (best - worst) ===")
    for b_start in range(0, 1000000, 50000):
        b_end = b_start + 50000
        def winner_gain(pnl_dict, lo, hi):
            pnls = [(t, v) for t, v in pnl_dict.items() if lo <= t < hi]
            if not pnls: return 0
            pnls.sort()
            return pnls[-1][1] - pnls[0][1]
        b_osm = winner_gain(best_osm_pnl, b_start, b_end)
        w_osm = winner_gain(worst_osm_pnl, b_start, b_end)
        b_pep = winner_gain(best_pep_pnl, b_start, b_end)
        w_pep = winner_gain(worst_pep_pnl, b_start, b_end)
        print(f"  [{b_start:>5d}..{b_end:>5d}] OSM best={b_osm:>7.1f} worst={w_osm:>7.1f} Δ={b_osm-w_osm:>+7.1f}  |  PEP best={b_pep:>7.1f} worst={w_pep:>7.1f} Δ={b_pep-w_pep:>+7.1f}")

    # biggest single-tick gains in best sample on OSM
    print("\nBest sample — top 15 OSM single-tick ΔPnL:")
    sorted_osm = sorted(best_osm, key=lambda x: x[0])
    deltas = [(sorted_osm[i][0], sorted_osm[i][1] - sorted_osm[i-1][1], sorted_osm[i][2], sorted_osm[i][3]) for i in range(1, len(sorted_osm))]
    top = sorted(deltas, key=lambda x: -x[1])[:15]
    for ts, d, mid, r in top:
        print(f"  ts={ts}  ΔPnL={d:+.1f}  mid={mid}  bid1={r.get('bid_price_1')}/{r.get('bid_volume_1')} ask1={r.get('ask_price_1')}/{r.get('ask_volume_1')}")

    # Same for worst
    print("\nWorst sample — top 15 OSM single-tick ΔPnL:")
    sorted_osm_w = sorted(worst_osm, key=lambda x: x[0])
    deltas_w = [(sorted_osm_w[i][0], sorted_osm_w[i][1] - sorted_osm_w[i-1][1], sorted_osm_w[i][2], sorted_osm_w[i][3]) for i in range(1, len(sorted_osm_w))]
    top_w = sorted(deltas_w, key=lambda x: -x[1])[:15]
    for ts, d, mid, r in top_w:
        print(f"  ts={ts}  ΔPnL={d:+.1f}  mid={mid}  bid1={r.get('bid_price_1')}/{r.get('bid_volume_1')} ask1={r.get('ask_price_1')}/{r.get('ask_volume_1')}")


if __name__ == "__main__":
    main()
