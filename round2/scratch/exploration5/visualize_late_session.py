"""Visualize late-session dynamics: mid, pos, cumulative PnL for iter26 best sample."""
from __future__ import annotations
import json, io, csv, pathlib
import plotly.graph_objects as go

LOG = '/tmp/prosperity_logs/316247/325221.log'


def main():
    d = json.load(open(LOG))
    # Parse activities
    act = csv.DictReader(io.StringIO(d['activitiesLog']), delimiter=';')
    osm_ts = []; osm_mid = []; osm_pnl = []
    pep_ts = []; pep_mid = []; pep_pnl = []
    for r in act:
        try: ts = int(r['timestamp'])
        except: continue
        try: mid = float(r['mid_price'])
        except: mid = 0
        try: pnl = float(r['profit_and_loss'])
        except: pnl = 0
        if mid == 0: continue
        if r['product'] == 'ASH_COATED_OSMIUM':
            osm_ts.append(ts); osm_mid.append(mid); osm_pnl.append(pnl)
        else:
            pep_ts.append(ts); pep_mid.append(mid); pep_pnl.append(pnl)

    # Reconstruct position trajectory
    trades = d['tradeHistory']
    pos_osm_hist = []; pos_pep_hist = []
    pos_osm = 0; pos_pep = 0
    all_ts = sorted(set([t['timestamp'] for t in trades] + osm_ts + pep_ts))
    for ts in all_ts:
        for t in trades:
            if t['timestamp'] != ts: continue
            q = t['quantity']
            if t['buyer'] == 'SUBMISSION':
                if t['symbol'] == 'ASH_COATED_OSMIUM': pos_osm += q
                else: pos_pep += q
            else:
                if t['symbol'] == 'ASH_COATED_OSMIUM': pos_osm -= q
                else: pos_pep -= q
        pos_osm_hist.append((ts, pos_osm))
        pos_pep_hist.append((ts, pos_pep))

    # Total PnL = sum of OSM + PEP
    total_ts = sorted(set(osm_ts))
    total_pnl = []
    osm_by_ts = dict(zip(osm_ts, osm_pnl))
    pep_by_ts = dict(zip(pep_ts, pep_pnl))
    for ts in total_ts:
        o = osm_by_ts.get(ts, 0)
        p = pep_by_ts.get(ts, 0)
        total_pnl.append(o + p)

    # Single-tick deltas
    import numpy as np
    total_arr = np.array(total_pnl)
    total_ts_arr = np.array(total_ts)
    deltas = np.diff(total_arr)
    # Top 15 positive deltas
    top_idx = np.argsort(-deltas)[:15]
    print("Top 15 single-tick cumulative PnL gains:")
    for i in top_idx:
        ts_pre = total_ts_arr[i]; ts = total_ts_arr[i+1]; d_ = deltas[i]
        # find position at ts
        p_osm = next((p for t, p in pos_osm_hist if t == ts), 0)
        p_pep = next((p for t, p in pos_pep_hist if t == ts), 0)
        o_mid = osm_by_ts.get(ts) or next((m for t, m in zip(osm_ts, osm_mid) if t <= ts), 0)
        print(f"  ts={ts}  Δ=${d_:+.1f}  pos=(OSM={p_osm}, PEP={p_pep})  o_pnl={osm_by_ts.get(ts, 'n/a')}  p_pnl={pep_by_ts.get(ts, 'n/a')}")

    # Visualize: mid + pos + cumulative PnL
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=osm_ts, y=osm_mid, name='OSM mid', yaxis='y1', line=dict(color='red')))
    fig.add_trace(go.Scatter(x=pep_ts, y=[m for m in pep_mid], name='PEP mid (÷1000)', yaxis='y1',
                              line=dict(color='orange'), customdata=pep_mid,
                              hovertemplate='PEP mid=%{customdata}<extra></extra>'))
    # pos traces
    fig.add_trace(go.Scatter(x=[t for t, _ in pos_osm_hist], y=[p for _, p in pos_osm_hist],
                              name='OSM pos', yaxis='y2', line=dict(color='green')))
    fig.add_trace(go.Scatter(x=[t for t, _ in pos_pep_hist], y=[p for _, p in pos_pep_hist],
                              name='PEP pos', yaxis='y2', line=dict(color='blue')))
    # cumulative PnL
    fig.add_trace(go.Scatter(x=total_ts, y=total_pnl, name='total PnL', yaxis='y3', line=dict(color='black', width=2)))
    fig.update_layout(
        title="iter26 best sample (316247, $9890.50): mid + pos + total PnL",
        xaxis_title='timestamp',
        yaxis=dict(title='mid', domain=[0, 0.33]),
        yaxis2=dict(title='pos', domain=[0.33, 0.66]),
        yaxis3=dict(title='cum PnL', domain=[0.66, 1.0]),
        height=900,
        legend=dict(orientation='h')
    )
    out = pathlib.Path('<repo>/exploration5/viz_iter26_best.html')
    fig.write_html(out, include_plotlyjs='cdn')
    print(f"wrote {out}")

    # Also: sliding-window PnL per 10K ts for session-half analysis
    print("\nCumulative PnL by 10K-ts window:")
    for b_start in range(0, 100000, 10000):
        b_end = b_start + 10000
        in_win = [(t, p) for t, p in zip(total_ts, total_pnl) if b_start <= t < b_end]
        if not in_win: continue
        gain = in_win[-1][1] - in_win[0][1]
        print(f"  [{b_start:>6d}..{b_end:>6d}]  gain=${gain:+.1f}")


if __name__ == "__main__":
    main()
