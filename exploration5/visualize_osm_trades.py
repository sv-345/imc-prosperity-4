"""Visualize OSM mid trajectory with trade dots colored by price offset from rolling mid.
Outliers (trades far from rolling mid) are the dislocation events.
"""
from __future__ import annotations
import pathlib
import pandas as pd
import numpy as np
import plotly.graph_objects as go

DATA = pathlib.Path("/Users/svelaga/Documents/IMC Prosperity/ROUND_2")


def main():
    fig = go.Figure()
    for day in (1,):
        prices = pd.read_csv(DATA / f"prices_round_2_day_{day}.csv", sep=";")
        trades = pd.read_csv(DATA / f"trades_round_2_day_{day}.csv", sep=";")
        osm = prices[prices['product'] == 'ASH_COATED_OSMIUM'].sort_values('timestamp').reset_index(drop=True)
        osm['mid'] = (osm['bid_price_1'] + osm['ask_price_1']) / 2.0
        osm['ref'] = osm['mid'].rolling(21, center=True, min_periods=5).median()
        osm_trades = trades[trades['symbol'] == 'ASH_COATED_OSMIUM'].copy()
        # Merge ref mid into trades
        osm_trades['ref'] = osm_trades['timestamp'].map(lambda t: osm[osm['timestamp'] == t]['ref'].iloc[0] if len(osm[osm['timestamp'] == t]) > 0 else np.nan)
        osm_trades['offset'] = osm_trades['price'] - osm_trades['ref']

        fig.add_trace(go.Scatter(x=osm['timestamp'], y=osm['mid'], name=f'day {day} OSM mid', mode='lines', line=dict(color='black', width=1)))
        fig.add_trace(go.Scatter(x=osm['timestamp'], y=osm['ref'], name=f'day {day} rolling mid', mode='lines', line=dict(color='gray', width=0.5, dash='dot')))

        # Trade dots colored by offset
        fig.add_trace(go.Scattergl(
            x=osm_trades['timestamp'], y=osm_trades['price'],
            mode='markers',
            marker=dict(
                color=osm_trades['offset'], size=6, symbol='circle',
                colorscale='RdBu', cmid=0, showscale=True
            ),
            name=f'day {day} trades',
            text=[f"off={o:.1f} qty={q}" for o, q in zip(osm_trades['offset'], osm_trades['quantity'])],
        ))

    fig.update_layout(title='OSM mid + trades colored by offset from rolling mid',
                      xaxis_title='timestamp', yaxis_title='price',
                      height=700)
    out = pathlib.Path('/Users/svelaga/Documents/IMC Prosperity/exploration5/viz_osm_trades.html')
    fig.write_html(out, include_plotlyjs='cdn')
    print(f"wrote {out}")

    # Print biggest-offset trades on day 1 OSM
    for day in (-1, 0, 1):
        prices = pd.read_csv(DATA / f"prices_round_2_day_{day}.csv", sep=";")
        trades = pd.read_csv(DATA / f"trades_round_2_day_{day}.csv", sep=";")
        osm = prices[prices['product'] == 'ASH_COATED_OSMIUM'].sort_values('timestamp').reset_index(drop=True)
        osm['mid'] = (osm['bid_price_1'] + osm['ask_price_1']) / 2.0
        osm['ref'] = osm['mid'].rolling(21, center=True, min_periods=5).median()
        ref_map = dict(zip(osm['timestamp'], osm['ref']))
        osm_trades = trades[trades['symbol'] == 'ASH_COATED_OSMIUM'].copy()
        osm_trades['ref'] = osm_trades['timestamp'].map(ref_map.get)
        osm_trades['offset'] = osm_trades['price'] - osm_trades['ref']
        # top 10 by |offset|
        print(f"\nday {day} OSM top trades by |offset from rolling mid|:")
        sorted_trades = osm_trades.nlargest(10, 'offset', keep='all')
        for _, r in sorted_trades.head(10).iterrows():
            print(f"  ts={int(r['timestamp'])} px={r['price']} ref={r['ref']:.1f} offset={r['offset']:.1f} qty={int(r['quantity'])}")
        # Smallest
        print(f"  most negative offsets:")
        for _, r in osm_trades.nsmallest(10, 'offset').iterrows():
            print(f"    ts={int(r['timestamp'])} px={r['price']} ref={r['ref']:.1f} offset={r['offset']:.1f} qty={int(r['quantity'])}")


if __name__ == "__main__":
    main()
