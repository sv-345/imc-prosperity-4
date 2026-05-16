"""Find trades at extreme prices (far from current mid).
These could be fills at favorable prices if our quotes were resting there.
"""
from __future__ import annotations
import pathlib
import pandas as pd
import numpy as np

DATA = pathlib.Path("<repo>/ROUND_2")


def main():
    for day in (-1, 0, 1):
        prices = pd.read_csv(DATA / f"prices_round_2_day_{day}.csv", sep=";")
        trades = pd.read_csv(DATA / f"trades_round_2_day_{day}.csv", sep=";")
        for product in ("ASH_COATED_OSMIUM", "INTARIAN_PEPPER_ROOT"):
            pp = prices[prices['product'] == product].sort_values('timestamp').reset_index(drop=True)
            tt = trades[trades['symbol'] == product].sort_values('timestamp').reset_index(drop=True)
            pp['mid'] = (pp['bid_price_1'] + pp['ask_price_1']) / 2.0
            ts_to_mid = {int(t): m for t, m in zip(pp['timestamp'], pp['mid'])}
            ts_to_b1 = {int(t): b for t, b in zip(pp['timestamp'], pp['bid_price_1'])}
            ts_to_a1 = {int(t): a for t, a in zip(pp['timestamp'], pp['ask_price_1'])}
            # Also get the book state (all levels)
            def get_row(ts):
                rows = pp[pp['timestamp'] == ts]
                if len(rows) == 0: return None
                return rows.iloc[0]

            extreme = []  # trades where price is far from mid
            for _, r in tt.iterrows():
                ts = int(r['timestamp'])
                mid = ts_to_mid.get(ts)
                if mid is None or np.isnan(mid): continue
                d = r['price'] - mid
                if abs(d) >= 5:
                    book = get_row(ts)
                    extreme.append((ts, r['price'], r['quantity'], mid, d,
                                    book['bid_price_1'] if book is not None else None,
                                    book['ask_price_1'] if book is not None else None))
            print(f"\n=== day {day} {product}: trades at |price - mid|>=5: {len(extreme)} ===")
            for ts, px, qty, mid, d, b1, a1 in extreme[:15]:
                print(f"  ts={ts}  px={px}  qty={qty}  mid={mid}  off_mid={d:+.1f}  book(bid1/ask1)={b1}/{a1}")


if __name__ == "__main__":
    main()
