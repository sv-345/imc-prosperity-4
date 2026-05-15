"""Find trade opportunities with big edge at specific timestamps.

A $1000 step-up at ts~34.3K would come from either:
  - a single big-qty trade with big edge (e.g., 50 qty × $20 edge)
  - a cluster of mid-size trades over 5-20 ticks

Scan both the submission's 1-day tape and the training 3-day tapes.
"""
from __future__ import annotations
import json, io, csv, pathlib
import numpy as np
import pandas as pd

LOG_JSON = pathlib.Path('/tmp/prosperity_logs/303257/312201.json')


def main():
    d = json.load(open(LOG_JSON))
    act = csv.DictReader(io.StringIO(d['activitiesLog']), delimiter=';')
    by_ts_prod = {}
    for r in act:
        try: ts = int(r['timestamp'])
        except: continue
        by_ts_prod[(ts, r['product'])] = r

    # Sliding 500-ts window PnL changes
    # Get OSM and PEP PnL arrays
    osm_pnl = []
    pep_pnl = []
    for ts in sorted(set(t for t, _ in by_ts_prod)):
        ro = by_ts_prod.get((ts, 'ASH_COATED_OSMIUM'))
        rp = by_ts_prod.get((ts, 'INTARIAN_PEPPER_ROOT'))
        if ro: osm_pnl.append((ts, float(ro.get('profit_and_loss', 0))))
        if rp: pep_pnl.append((ts, float(rp.get('profit_and_loss', 0))))

    # 500-ts (5-tick) windows
    for name, series in (('OSM', osm_pnl), ('PEP', pep_pnl)):
        print(f"\n=== {name} — top 20 500-ts windows by gain ===")
        top = []
        for i in range(len(series) - 5):
            gain = series[i+5][1] - series[i][1]
            top.append((series[i][0], series[i+5][0], gain))
        top.sort(key=lambda x: -x[2])
        for lo, hi, g in top[:20]:
            print(f"  ts=[{lo:>5d}..{hi:>5d}]  gain=${g:>+7.2f}")

    # Window 1 (34-41K) and Window 2 (76-83K): find the actual sharp moment
    print("\n\nSubcutoff OSM PnL deltas in each claimed window, sorted by size:")
    for lo, hi, name in [(34000, 41000, 'Window 1'), (76000, 83000, 'Window 2')]:
        pre_pnl = next((v for t, v in osm_pnl if t >= lo), 0)
        post_pnl = next((v for t, v in osm_pnl if t >= hi), 0)
        print(f"\n{name}: net OSM gain = ${post_pnl-pre_pnl:.2f}")
        # sub-period gains
        subs = []
        prev = pre_pnl; prev_ts = lo
        for t, v in osm_pnl:
            if t < lo: continue
            if t > hi: break
            delta = v - prev
            subs.append((prev_ts, t, delta))
            prev, prev_ts = v, t
        subs.sort(key=lambda x: -abs(x[2]))
        print(f"  top 8 largest 100-ts sub-deltas:")
        for s_lo, s_hi, d_ in subs[:8]:
            r = by_ts_prod.get((s_hi, 'ASH_COATED_OSMIUM'))
            mid = r.get('mid_price') if r else '?'
            print(f"    ts={s_hi}  ΔPnL={d_:+.2f}  mid={mid}")


if __name__ == "__main__":
    main()
