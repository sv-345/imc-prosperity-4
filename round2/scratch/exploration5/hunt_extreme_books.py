"""Hunt for extreme book events: crossed books, asks far below mid, bids far above mid.
These could be $500+ one-tick alpha opportunities.
"""
from __future__ import annotations
import pathlib
import pandas as pd
import numpy as np

DATA = pathlib.Path("/Users/svelaga/Documents/IMC Prosperity/ROUND_2")


def main():
    for day in (-1, 0, 1):
        p = pd.read_csv(DATA / f"prices_round_2_day_{day}.csv", sep=";")
        for product in ("ASH_COATED_OSMIUM", "INTARIAN_PEPPER_ROOT"):
            pp = p[p['product'] == product].sort_values('timestamp').reset_index(drop=True)
            print(f"\n=== day {day} {product} ===")
            # Check for crossed book: bid1 >= ask1
            crossed = pp[(pp['bid_price_1'].notna()) & (pp['ask_price_1'].notna()) & (pp['bid_price_1'] >= pp['ask_price_1'])]
            print(f"  crossed books (bid1 >= ask1): {len(crossed)}")
            # Check for ask far below mid
            pp['mid'] = (pp['bid_price_1'] + pp['ask_price_1']) / 2.0
            # ask_price_1 well below typical mid
            extreme_low_ask = pp[(pp['ask_price_1'].notna()) & (pp['bid_price_1'].notna()) & ((pp['ask_price_1'] - pp['bid_price_1']) <= 2)]
            print(f"  tight spread (ask1 - bid1 <= 2): {len(extreme_low_ask)}")
            # Very wide mid swings from tick to tick
            pp['mid_diff'] = pp['mid'].diff()
            big_moves = pp[pp['mid_diff'].abs() >= 10]
            print(f"  big single-tick mid moves (|Δmid|>=10): {len(big_moves)}")
            if len(big_moves) > 0:
                print(f"  samples of big moves:")
                for _, r in big_moves.head(5).iterrows():
                    print(f"    ts={int(r['timestamp'])}  mid={r['mid']}  Δmid={r['mid_diff']:+.1f}  bid1={r['bid_price_1']} ask1={r['ask_price_1']}")
            # Max individual L2/L3 prices — are there wild prices deep?
            for side in ('bid', 'ask'):
                for lvl in (1, 2, 3):
                    px = pp[f'{side}_price_{lvl}']
                    if product == 'ASH_COATED_OSMIUM':
                        # OSM normal range 9985-10015 — anything outside?
                        weird = pp[px.notna() & ((px < 9985) | (px > 10020))]
                    else:
                        # PEP drifts 11000-14000
                        day_start = {-1: 11000, 0: 12000, 1: 13000}[day]
                        expected_lo = day_start
                        expected_hi = day_start + 1100
                        weird = pp[px.notna() & ((px < expected_lo - 20) | (px > expected_hi + 20))]
                    if len(weird) > 0:
                        print(f"  {side}_L{lvl} out-of-range: {len(weird)}  samples:")
                        for _, r in weird.head(3).iterrows():
                            print(f"    ts={int(r['timestamp'])}  px={r[f'{side}_price_{lvl}']}  mid={r['mid']}  vol={r[f'{side}_volume_{lvl}']}")

            # Biggest single-tick discrepancy between (ask_1) and typical-mid
            # e.g., ask_1 far below what we'd expect
            # look at ask1 vs rolling median
            med = pp['mid'].rolling(21, center=True, min_periods=5).median()
            pp['ref'] = med
            # asks way below ref (can be taken for big edge)
            bargain_ask = pp[(pp['ask_price_1'].notna()) & (pp['ask_price_1'] < pp['ref'] - 5)]
            print(f"  asks > 5 below rolling-mid: {len(bargain_ask)}")
            if len(bargain_ask) > 0:
                # Check top 5 by discrepancy
                bargain_ask = bargain_ask.copy()
                bargain_ask['discount'] = bargain_ask['ref'] - bargain_ask['ask_price_1']
                top = bargain_ask.nlargest(5, 'discount')
                for _, r in top.iterrows():
                    print(f"    ts={int(r['timestamp'])}  ref={r['ref']:.1f}  ask1={r['ask_price_1']}  vol={r['ask_volume_1']}  discount={r['discount']:.1f}")
            bargain_bid = pp[(pp['bid_price_1'].notna()) & (pp['bid_price_1'] > pp['ref'] + 5)]
            print(f"  bids > 5 above rolling-mid: {len(bargain_bid)}")
            if len(bargain_bid) > 0:
                bargain_bid = bargain_bid.copy()
                bargain_bid['premium'] = bargain_bid['bid_price_1'] - bargain_bid['ref']
                top = bargain_bid.nlargest(5, 'premium')
                for _, r in top.iterrows():
                    print(f"    ts={int(r['timestamp'])}  ref={r['ref']:.1f}  bid1={r['bid_price_1']}  vol={r['bid_volume_1']}  premium={r['premium']:.1f}")


if __name__ == "__main__":
    main()
