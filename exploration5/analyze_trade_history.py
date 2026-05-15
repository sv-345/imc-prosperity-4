"""Analyze tradeHistory + activities to find single-tick PnL swings.

Reconstruct per-tick position and MTM change.
"""
from __future__ import annotations
import json, io, csv, pathlib
import numpy as np

LOG = '/tmp/prosperity_logs/316247/325221.log'  # iter26 best $9890.50


def main():
    d = json.load(open(LOG))
    trades = d['tradeHistory']
    # Parse activities for mid
    act = csv.DictReader(io.StringIO(d['activitiesLog']), delimiter=';')
    ts_mid = {}
    for r in act:
        try: ts = int(r['timestamp'])
        except: continue
        try: mid = float(r['mid_price'])
        except: continue
        if r['product'] not in ts_mid: ts_mid[r['product']] = {}
        ts_mid[r['product']][ts] = mid

    # Group our trades by ts
    our = [t for t in trades if t['buyer'] == 'SUBMISSION' or t['seller'] == 'SUBMISSION']
    print(f"Total our trades: {len(our)}")

    # Group by (ts, product)
    by_ts_prod = {}
    for t in our:
        key = (t['timestamp'], t['symbol'])
        by_ts_prod.setdefault(key, []).append(t)

    # Compute per-tick cash flow
    events = []
    for (ts, prod), fills in by_ts_prod.items():
        cash = 0
        qty_bought = 0
        qty_sold = 0
        for f in fills:
            q = f['quantity']
            px = f['price']
            if f['buyer'] == 'SUBMISSION':
                cash -= q * px
                qty_bought += q
            else:
                cash += q * px
                qty_sold += q
        events.append({
            'ts': ts, 'product': prod,
            'cash': cash, 'bought': qty_bought, 'sold': qty_sold,
            'fills': len(fills),
            'prices': [f['price'] for f in fills],
        })

    # Big-cash-flow events
    events.sort(key=lambda x: -abs(x['cash']))
    print("\nTop 10 by |cash|:")
    for e in events[:10]:
        mid = ts_mid.get(e['product'], {}).get(e['ts'], 'n/a')
        print(f"  ts={e['ts']} {e['product']}: cash={e['cash']:+.2f}  bought={e['bought']} sold={e['sold']}  prices={e['prices']}  mid={mid}")

    # Also compute per-tick running position and MTM delta
    # For each timestamp ts, sum our trades -> position change. Then MTM = pos * mid.
    all_ts = sorted(set(t['timestamp'] for t in trades))
    pos = {'ASH_COATED_OSMIUM': 0, 'INTARIAN_PEPPER_ROOT': 0}
    cash = {'ASH_COATED_OSMIUM': 0, 'INTARIAN_PEPPER_ROOT': 0}
    pnl_history = []
    prev_mtm = 0
    for ts in all_ts:
        # Apply trades at this ts
        for t in our:
            if t['timestamp'] != ts: continue
            prod = t['symbol']
            q = t['quantity']
            px = t['price']
            if t['buyer'] == 'SUBMISSION':
                pos[prod] += q
                cash[prod] -= q * px
            else:
                pos[prod] -= q
                cash[prod] += q * px
        # Compute MTM using mid
        mtm = 0
        for prod in pos:
            mid = ts_mid.get(prod, {}).get(ts, 0)
            mtm += cash[prod] + pos[prod] * mid
        delta = mtm - prev_mtm
        pnl_history.append((ts, mtm, delta, pos['ASH_COATED_OSMIUM'], pos['INTARIAN_PEPPER_ROOT']))
        prev_mtm = mtm

    # Top 10 single-tick MTM deltas
    print("\nTop 10 single-tick MTM deltas (positive):")
    top = sorted(pnl_history, key=lambda x: -x[2])[:10]
    for ts, mtm, delta, o_pos, p_pos in top:
        o_mid = ts_mid.get('ASH_COATED_OSMIUM', {}).get(ts, 0)
        p_mid = ts_mid.get('INTARIAN_PEPPER_ROOT', {}).get(ts, 0)
        print(f"  ts={ts}  Δmtm=${delta:+.1f}  mtm=${mtm:.1f}  pos=(OSM={o_pos}, PEP={p_pos})  mids=(OSM={o_mid}, PEP={p_mid})")

    print("\nTop 10 single-tick MTM deltas (negative):")
    top_neg = sorted(pnl_history, key=lambda x: x[2])[:10]
    for ts, mtm, delta, o_pos, p_pos in top_neg:
        o_mid = ts_mid.get('ASH_COATED_OSMIUM', {}).get(ts, 0)
        p_mid = ts_mid.get('INTARIAN_PEPPER_ROOT', {}).get(ts, 0)
        print(f"  ts={ts}  Δmtm=${delta:+.1f}  mtm=${mtm:.1f}  pos=(OSM={o_pos}, PEP={p_pos})  mids=(OSM={o_mid}, PEP={p_mid})")


if __name__ == "__main__":
    main()
