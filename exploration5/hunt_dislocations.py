"""Hunt for price dislocations in training data: asks far below rolling-mid
or bids far above rolling-mid. These are take-logic alpha opportunities.

A trade at $500+ edge in one tick = something like 50 qty × $10 edge OR
less-but-with-big-edges.

Goal: find the largest single-tick dislocations across all 3 days.
"""
from __future__ import annotations
import pathlib
import pandas as pd
import numpy as np

DATA = pathlib.Path("/Users/svelaga/Documents/IMC Prosperity/ROUND_2")


def main():
    for day in (-1, 0, 1):
        prices = pd.read_csv(DATA / f"prices_round_2_day_{day}.csv", sep=";")
        trades = pd.read_csv(DATA / f"trades_round_2_day_{day}.csv", sep=";")
        for product in ("ASH_COATED_OSMIUM", "INTARIAN_PEPPER_ROOT"):
            pp = prices[prices['product'] == product].sort_values('timestamp').reset_index(drop=True)
            pp['mid'] = (pp['bid_price_1'] + pp['ask_price_1']) / 2.0
            # rolling median mid (robust)
            pp['ref_mid'] = pp['mid'].rolling(21, center=True, min_periods=5).median()
            # Look at all 3 bid levels and 3 ask levels for dislocations
            print(f"\n=== day {day} {product} ===")
            disloc_asks = []
            disloc_bids = []
            for _, r in pp.iterrows():
                ref = r['ref_mid']
                if pd.isna(ref): continue
                ts = int(r['timestamp'])
                for k in (1, 2, 3):
                    ap = r[f'ask_price_{k}']; av = r[f'ask_volume_{k}']
                    bp = r[f'bid_price_{k}']; bv = r[f'bid_volume_{k}']
                    if pd.notna(ap) and ap < ref - 5:
                        disloc_asks.append((ts, ap, av, ref, ref - ap, k))
                    if pd.notna(bp) and bp > ref + 5:
                        disloc_bids.append((ts, bp, bv, ref, bp - ref, k))
            # top disloc asks by (edge × volume)
            disloc_asks_sorted = sorted(disloc_asks, key=lambda x: -(x[4] * x[2]))
            print(f"  top 15 ask dislocations (edge × vol), n={len(disloc_asks)} total:")
            for ts, px, vol, ref, edge, lvl in disloc_asks_sorted[:15]:
                print(f"    ts={ts} L{lvl} ask={px}  vol={int(vol)}  ref={ref:.1f}  edge={edge:.1f}  potential={edge*vol:.0f}")
            disloc_bids_sorted = sorted(disloc_bids, key=lambda x: -(x[4] * x[2]))
            print(f"  top 15 bid dislocations, n={len(disloc_bids)}:")
            for ts, px, vol, ref, edge, lvl in disloc_bids_sorted[:15]:
                print(f"    ts={ts} L{lvl} bid={px}  vol={int(vol)}  ref={ref:.1f}  edge={edge:.1f}  potential={edge*vol:.0f}")


if __name__ == "__main__":
    main()
