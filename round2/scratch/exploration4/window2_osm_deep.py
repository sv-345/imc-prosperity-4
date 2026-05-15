"""Window 2 (ts=76-83K) deep dive on OSM.

iter23 loses $13 on OSM here while leaderboard player gains ~$500-1000.
What's happening?
"""
from __future__ import annotations
import json, io, csv, pathlib
import numpy as np

LOG_JSON = pathlib.Path('/tmp/prosperity_logs/303257/312201.json')
LOG = pathlib.Path('/tmp/prosperity_logs/303257/312201.log')


def main():
    d = json.load(open(LOG_JSON))
    # Also: activitiesLog has per-tick running PnL + book depth.
    # We can tell when iter23's position changed by reading mid & PnL together
    # But actually: our orders/fills are embedded in the .log file (lambdaLog).
    log_raw = json.load(open(LOG))
    # The log file is itself a JSON record containing 'logs' list — each with lambdaLog
    # Let me check
    # Actually LOG is the raw log; let me parse by lines

    # Parse activitiesLog
    act = csv.DictReader(io.StringIO(d['activitiesLog']), delimiter=';')
    # index by ts
    by_ts_prod = {}
    for r in act:
        try: ts = int(r['timestamp'])
        except: continue
        by_ts_prod[(ts, r['product'])] = r

    # Print book state for OSM every 500 ts in window 2
    print("=== OSM book state in Window 2 (ts=76000..83000), every 500 ts ===")
    for ts in range(76000, 83001, 500):
        r = by_ts_prod.get((ts, 'ASH_COATED_OSMIUM'))
        if not r: continue
        bid1 = r.get('bid_price_1') or '-'
        ask1 = r.get('ask_price_1') or '-'
        mid = r.get('mid_price') or '-'
        pnl = r.get('profit_and_loss') or '-'
        bid2 = r.get('bid_price_2') or ''
        ask2 = r.get('ask_price_2') or ''
        bidv1 = r.get('bid_volume_1') or ''
        askv1 = r.get('ask_volume_1') or ''
        bidv2 = r.get('bid_volume_2') or ''
        askv2 = r.get('ask_volume_2') or ''
        print(f"  ts={ts}: bid={bid1}({bidv1})/{bid2}({bidv2})  ask={ask1}({askv1})/{ask2}({askv2})  mid={mid}  cum_pnl={pnl}")

    # Same for Window 1 so we can compare
    print("\n=== OSM book state in Window 1 (ts=34000..41000), every 500 ts ===")
    for ts in range(34000, 41001, 500):
        r = by_ts_prod.get((ts, 'ASH_COATED_OSMIUM'))
        if not r: continue
        bid1 = r.get('bid_price_1') or '-'
        ask1 = r.get('ask_price_1') or '-'
        mid = r.get('mid_price') or '-'
        pnl = r.get('profit_and_loss') or '-'
        bidv1 = r.get('bid_volume_1') or ''
        askv1 = r.get('ask_volume_1') or ''
        bid2 = r.get('bid_price_2') or ''
        ask2 = r.get('ask_price_2') or ''
        bidv2 = r.get('bid_volume_2') or ''
        askv2 = r.get('ask_volume_2') or ''
        print(f"  ts={ts}: bid={bid1}({bidv1})/{bid2}({bidv2})  ask={ask1}({askv1})/{ask2}({askv2})  mid={mid}  cum_pnl={pnl}")

    # Check window 2 for 100-ts ticks where PnL changed significantly
    osm_rows = [r for r in [by_ts_prod[(ts, 'ASH_COATED_OSMIUM')] for ts in sorted(set(t for t, _ in by_ts_prod)) if (ts, 'ASH_COATED_OSMIUM') in by_ts_prod]]
    # look at cumulative pnl deltas inside windows
    for win_name, lo, hi in [('Window 1', 34000, 41000), ('Window 2', 76000, 83000), ('OSM big win', 83000, 87000)]:
        in_win = [r for r in osm_rows if lo <= int(r['timestamp']) <= hi]
        pnl_series = [float(r['profit_and_loss']) for r in in_win]
        if len(pnl_series) < 2: continue
        deltas = np.diff(pnl_series)
        # ticks with big deltas
        big = [(int(in_win[i+1]['timestamp']), deltas[i]) for i in range(len(deltas)) if abs(deltas[i]) >= 20]
        print(f"\n{win_name} ({lo}..{hi}): OSM cum PnL deltas >= 20 (tick events):")
        for ts, d_ in big[:30]:
            r = by_ts_prod.get((ts, 'ASH_COATED_OSMIUM'))
            bid1 = r.get('bid_price_1') or '-' if r else '?'
            ask1 = r.get('ask_price_1') or '-' if r else '?'
            mid = r.get('mid_price') or '-' if r else '?'
            print(f"  ts={ts}  ΔPnL={d_:+.2f}  mid={mid}  bid={bid1} ask={ask1}")


if __name__ == "__main__":
    main()
