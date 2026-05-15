"""Visualize OSM mid trajectory + iter23 PnL + big mid-jump events.
Look for patterns in what precedes big jumps.
"""
from __future__ import annotations
import pathlib, json, io, csv
import numpy as np
import plotly.graph_objects as go

LOG = pathlib.Path('/tmp/prosperity_logs/303257/312201.json')
DATA = pathlib.Path('/Users/svelaga/Documents/IMC Prosperity/ROUND_2')


def main():
    d = json.load(open(LOG))
    act = csv.DictReader(io.StringIO(d['activitiesLog']), delimiter=';')
    osm_ts = []; osm_mid = []; osm_pnl = []; osm_bid1 = []; osm_ask1 = []
    osm_bid2 = []; osm_ask2 = []; osm_bid_vols = []; osm_ask_vols = []
    for r in act:
        if r.get('product') != 'ASH_COATED_OSMIUM': continue
        try: ts = int(r['timestamp'])
        except: continue
        try: mid = float(r['mid_price'])
        except: mid = None
        try: pnl = float(r['profit_and_loss'])
        except: pnl = 0
        if mid is None or mid == 0: continue
        osm_ts.append(ts); osm_mid.append(mid); osm_pnl.append(pnl)
        osm_bid1.append(float(r['bid_price_1']) if r.get('bid_price_1') else None)
        osm_ask1.append(float(r['ask_price_1']) if r.get('ask_price_1') else None)
        osm_bid_vols.append(int(r['bid_volume_1']) if r.get('bid_volume_1') else 0)
        osm_ask_vols.append(int(r['ask_volume_1']) if r.get('ask_volume_1') else 0)

    # Mid diffs
    mid_arr = np.array(osm_mid)
    ts_arr = np.array(osm_ts)
    mid_diffs = np.diff(mid_arr)
    big_jumps = np.where(np.abs(mid_diffs) >= 5)[0]
    print(f"Big mid jumps (|Δmid|≥5): {len(big_jumps)}")
    for idx in big_jumps[:20]:
        pre = osm_ts[idx]; post = osm_ts[idx+1]
        print(f"  ts={post}  mid: {osm_mid[idx]} → {osm_mid[idx+1]}  Δ={mid_diffs[idx]:+.1f}  "
              f"pre bid1={osm_bid1[idx]}v{osm_bid_vols[idx]} ask1={osm_ask1[idx]}v{osm_ask_vols[idx]}  "
              f"post bid1={osm_bid1[idx+1]}v{osm_bid_vols[idx+1]} ask1={osm_ask1[idx+1]}v{osm_ask_vols[idx+1]}")

    # Visualize: mid + PnL, with jump markers
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=osm_ts, y=osm_mid, name='OSM mid', mode='lines', yaxis='y1', line=dict(color='black')))
    fig.add_trace(go.Scatter(x=osm_ts, y=osm_pnl, name='iter23 OSM PnL', mode='lines', yaxis='y2', line=dict(color='blue')))
    # Mark big jumps
    jump_ts = [osm_ts[idx+1] for idx in big_jumps]
    jump_mid = [osm_mid[idx+1] for idx in big_jumps]
    fig.add_trace(go.Scatter(x=jump_ts, y=jump_mid, name='big jump', mode='markers', yaxis='y1',
                              marker=dict(color='red', size=10, symbol='star')))
    fig.update_layout(
        title=f"iter23 sample 303257 — OSM mid + PnL, big jumps marked (n={len(big_jumps)})",
        xaxis_title='timestamp',
        yaxis=dict(title='mid', side='left'),
        yaxis2=dict(title='iter23 PnL', side='right', overlaying='y'),
        height=700,
    )
    out = pathlib.Path('/Users/svelaga/Documents/IMC Prosperity/exploration5/viz_osm_jumps.html')
    fig.write_html(out, include_plotlyjs='cdn')
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
