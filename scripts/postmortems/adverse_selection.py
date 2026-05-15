"""Quantify adverse-selection cost in submission 294069.

Inputs:
  /tmp/prosperity_logs/294069/302973.log — JSON with tradeHistory + activitiesLog

Definitions:
  Fill = trade with buyer=='SUBMISSION' (BUY) or seller=='SUBMISSION' (SELL).
  mid(t) = activitiesLog mid_price at tick t (top-of-book mid).
  drift_M(fill) = mid(t+M) - mid(t)  where t is the fill tick.
  signed_drift_M = drift_M for BUYs, -drift_M for SELLs (positive = good for us).
  entry_edge = mid(t) - fill_price for BUYs, fill_price - mid(t) for SELLs
              (positive = we got a price better than mid).

A fill is "toxic at (N, M)" iff signed_drift_M <= -N.

  $ adverse-drift cost = qty * |signed_drift_M|   (only counted for toxic fills;
                                                   the loss attributable to drift)
  $ entry-edge capture = qty * entry_edge          (always positive in this submission)
  Net realized M-tick PnL of fill = qty * (entry_edge + signed_drift_M)

Counterfactual: a filter that blocks 100% of toxic fills AND fp_rate of
non-toxic fills (false positives — proxy for an imperfect signal). Skipping
a fill forgoes its full realized M-tick PnL.

  net_upside = -sum(pnl[toxic]) - fp_rate * sum(pnl[non-toxic with positive pnl])

(We model false positives as preferentially hitting profitable fills since
those are the modal case here. A more conservative model would draw uniformly
from non-toxic fills; we report both.)
"""

from __future__ import annotations

import json
import math
import statistics
from collections import defaultdict
from typing import Dict, List


LOG_PATH = '/tmp/prosperity_logs/294069/302973.log'


def load_data():
    with open(LOG_PATH) as f:
        return json.load(f)


def parse_books(activities: str) -> Dict[str, Dict[int, dict]]:
    out: Dict[str, Dict[int, dict]] = defaultdict(dict)
    lines = activities.strip().split('\n')
    cols = {n: i for i, n in enumerate(lines[0].split(';'))}
    for line in lines[1:]:
        f = line.split(';')
        ts = int(f[cols['timestamp']])
        prod = f[cols['product']]
        bid = int(f[cols['bid_price_1']]) if f[cols['bid_price_1']] else None
        ask = int(f[cols['ask_price_1']]) if f[cols['ask_price_1']] else None
        out[prod][ts] = {
            'bid': bid, 'ask': ask,
            'mid': float(f[cols['mid_price']]),
            'pnl': float(f[cols['profit_and_loss']]),
        }
    return out


def get_fills(trade_history: List[dict]) -> List[dict]:
    out = []
    for t in trade_history:
        if t['buyer'] == 'SUBMISSION':
            side = 'BUY'
        elif t['seller'] == 'SUBMISSION':
            side = 'SELL'
        else:
            continue
        out.append({
            'ts': t['timestamp'], 'product': t['symbol'],
            'side': side, 'qty': int(t['quantity']),
            'price': float(t['price']),
        })
    return out


def mid_at(books: Dict[int, dict], ts: int) -> float:
    if ts in books:
        return books[ts]['mid']
    keys = sorted(books.keys())
    if ts >= keys[-1]:
        return books[keys[-1]]['mid']
    if ts <= keys[0]:
        return books[keys[0]]['mid']
    for k in keys:
        if k >= ts:
            return books[k]['mid']
    return books[keys[-1]]['mid']


def annotate_fills(fills: List[dict], books: Dict[str, Dict[int, dict]],
                   horizons_ticks: List[int]) -> List[dict]:
    for f in fills:
        b = books[f['product']]
        ts = f['ts']
        fill_mid = b[ts]['mid'] if ts in b else mid_at(b, ts)
        f['mid_at_fill'] = fill_mid
        if f['side'] == 'BUY':
            f['entry_edge'] = fill_mid - f['price']
        else:
            f['entry_edge'] = f['price'] - fill_mid
        for M in horizons_ticks:
            future_mid = mid_at(b, ts + M * 100)
            drift = future_mid - fill_mid
            if f['side'] == 'BUY':
                signed = drift
            else:
                signed = -drift
            f[f'mid_drift_M{M}'] = drift
            f[f'signed_drift_M{M}'] = signed
            f[f'pnl_M{M}'] = f['qty'] * (f['entry_edge'] + signed)
    return fills


def split_at_threshold(fills, prod, N, M):
    pf = [f for f in fills if f['product'] == prod]
    toxic = [f for f in pf if f[f'signed_drift_M{M}'] <= -N]
    nontoxic = [f for f in pf if f[f'signed_drift_M{M}'] > -N]
    return pf, toxic, nontoxic


def filter_upside(fills, prod, N, M, fp_rate, fp_target='profitable'):
    """Net $ change if we install a filter blocking all toxic + fp_rate of non-toxic.

    fp_target:
      'profitable' — false positives drawn from non-toxic fills with positive PnL
                     (worst case for the filter)
      'uniform'    — false positives drawn uniformly from all non-toxic fills
    """
    pf, toxic, nontoxic = split_at_threshold(fills, prod, N, M)
    # We forgo the realized PnL of every blocked fill.
    forgone_toxic = sum(f[f'pnl_M{M}'] for f in toxic)  # negative numbers for losers
    if fp_target == 'profitable':
        prof_pool = [f for f in nontoxic if f[f'pnl_M{M}'] > 0]
        forgone_fp = fp_rate * sum(f[f'pnl_M{M}'] for f in prof_pool)
    else:
        forgone_fp = fp_rate * sum(f[f'pnl_M{M}'] for f in nontoxic)
    # Filter benefit = -forgone (skipping a losing fill is good).
    net = -(forgone_toxic + forgone_fp)
    return {
        'count_toxic': len(toxic),
        'count_nontoxic': len(nontoxic),
        'forgone_toxic_pnl': forgone_toxic,
        'forgone_fp_pnl': forgone_fp,
        'net_upside': net,
    }


def adverse_drift_cost(fills, prod, N, M):
    """Sum of qty * |signed_drift| for toxic fills (the drift-only component
    of the loss, NOT net of entry edge)."""
    _, toxic, _ = split_at_threshold(fills, prod, N, M)
    cost = sum(f['qty'] * abs(f[f'signed_drift_M{M}']) for f in toxic)
    qty = sum(f['qty'] for f in toxic)
    return cost, qty, len(toxic)


def wilson_ci(k, n, z=1.96):
    """Wilson score interval for binomial proportion (95% CI)."""
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def main():
    data = load_data()
    books = parse_books(data['activitiesLog'])
    fills = annotate_fills(get_fills(data['tradeHistory']),
                           books, [3, 5, 10, 20])
    fills.sort(key=lambda f: (f['product'], f['ts']))

    with open('/tmp/294069_fills.json', 'w') as f:
        json.dump({'fills': fills, 'horizons': [3, 5, 10, 20]}, f)

    print('=== Per-product fill summary ===')
    for prod in ('ASH_COATED_OSMIUM', 'INTARIAN_PEPPER_ROOT'):
        pf = [f for f in fills if f['product'] == prod]
        n_buy = sum(1 for f in pf if f['side'] == 'BUY')
        n_sell = sum(1 for f in pf if f['side'] == 'SELL')
        q_buy = sum(f['qty'] for f in pf if f['side'] == 'BUY')
        q_sell = sum(f['qty'] for f in pf if f['side'] == 'SELL')
        edges = [f['entry_edge'] for f in pf]
        print(f'\n{prod}:')
        print(f'  fills: {len(pf)}  (BUY={n_buy} qty={q_buy}, SELL={n_sell} qty={q_sell})')
        print(f'  entry edge: avg={statistics.mean(edges):.2f}  median={statistics.median(edges):.2f}  '
              f'min={min(edges):.1f}  max={max(edges):.1f}')

    # Toxic-fill rate and adverse-drift $ cost (per the user's spec).
    print('\n=== (3) Adverse-drift $ cost per product (raw qty * adverse drift) ===')
    print(f'{"N":>3} {"M":>3} | {"product":25} | {"tox":>3} {"tot":>3} {"%":>5} | '
          f'{"95% CI":>15} | {"qty_tox":>7} | {"adv $ cost":>10}')
    for N, M in [(2, 5), (3, 10), (1, 3)]:
        for prod in ('ASH_COATED_OSMIUM', 'INTARIAN_PEPPER_ROOT'):
            pf = [f for f in fills if f['product'] == prod]
            cost, qty, n_tox = adverse_drift_cost(fills, prod, N, M)
            tot = len(pf)
            pct = 100 * n_tox / max(1, tot)
            lo, hi = wilson_ci(n_tox, tot)
            print(f'{N:>3} {M:>3} | {prod:25} | {n_tox:>3} {tot:>3} {pct:>4.0f}% | '
                  f'[{lo*100:>4.0f}%, {hi*100:>4.0f}%] | {qty:>7} | {cost:>10.2f}')

    # Counterfactual: filter upside at various FP rates.
    print('\n=== (4) Filter counterfactual at (N=2 ticks, M=5 ticks) ===')
    print(f'  fp_rate  | OSM gain  PEP gain  | OSM loss  PEP loss  | NET upside')
    for fp in (0.0, 0.10, 0.20, 0.30):
        osm = filter_upside(fills, 'ASH_COATED_OSMIUM', 2, 5, fp, 'profitable')
        pep = filter_upside(fills, 'INTARIAN_PEPPER_ROOT', 2, 5, fp, 'profitable')
        # gain from blocking toxic = -forgone_toxic if forgone is negative
        osm_save = -osm['forgone_toxic_pnl']
        pep_save = -pep['forgone_toxic_pnl']
        osm_lose = -osm['forgone_fp_pnl']  # negative number (we lost money)
        pep_lose = -pep['forgone_fp_pnl']
        total = osm['net_upside'] + pep['net_upside']
        print(f'  {fp:.2f}     | {osm_save:>+8.2f}  {pep_save:>+8.2f}  | {osm_lose:>+8.2f}  {pep_lose:>+8.2f}  | {total:>+10.2f}')

    print('\n=== (5) Sensitivity sweep — combined NET upside ($) ===')
    print(f'  {"setting":>10}  fp=0%   fp=10%  fp=20%  fp=30%')
    settings = [(1, 3), (2, 3), (2, 5), (2, 10), (3, 5), (3, 10), (4, 10), (5, 20)]
    for N, M in settings:
        row = []
        for fp in (0.0, 0.10, 0.20, 0.30):
            osm = filter_upside(fills, 'ASH_COATED_OSMIUM', N, M, fp, 'profitable')
            pep = filter_upside(fills, 'INTARIAN_PEPPER_ROOT', N, M, fp, 'profitable')
            row.append(osm['net_upside'] + pep['net_upside'])
        print(f'  N={N},M={M:>2}  ' + ' '.join(f'{x:>+7.1f}' for x in row))

    # Bootstrap CI for the filter upside at (N=2, M=5).
    print('\n=== Bootstrap 95% CI for combined net upside (N=2, M=5, fp=0%) ===')
    import random
    random.seed(0)
    all_fills = fills
    n_bootstrap = 2000
    samples = []
    for _ in range(n_bootstrap):
        # Resample fills with replacement, by product (preserve product mix).
        boot = []
        for prod in ('ASH_COATED_OSMIUM', 'INTARIAN_PEPPER_ROOT'):
            pf = [f for f in all_fills if f['product'] == prod]
            boot.extend(random.choices(pf, k=len(pf)))
        osm = filter_upside(boot, 'ASH_COATED_OSMIUM', 2, 5, 0.0, 'profitable')
        pep = filter_upside(boot, 'INTARIAN_PEPPER_ROOT', 2, 5, 0.0, 'profitable')
        samples.append(osm['net_upside'] + pep['net_upside'])
    samples.sort()
    p2_5 = samples[int(0.025 * n_bootstrap)]
    p50 = samples[int(0.50 * n_bootstrap)]
    p97_5 = samples[int(0.975 * n_bootstrap)]
    print(f'  median: ${p50:+.2f}   95% CI: [${p2_5:+.2f}, ${p97_5:+.2f}]')

    # Detailed dump of toxic fills at (N=2, M=5) for the report.
    print('\n=== Toxic-fill detail at (N=2, M=5) ===')
    for prod in ('ASH_COATED_OSMIUM', 'INTARIAN_PEPPER_ROOT'):
        _, toxic, _ = split_at_threshold(fills, prod, 2, 5)
        print(f'\n{prod}:')
        if not toxic:
            print('  (none)')
        for f in toxic:
            print(f'  ts={f["ts"]:>6} {f["side"]:>4} qty={f["qty"]:>2} px={f["price"]:>7.1f} '
                  f'mid={f["mid_at_fill"]:>7.1f} entry_edge=${f["entry_edge"]:+.1f} '
                  f'drift_M5=${f["mid_drift_M5"]:+.1f} signed=${f["signed_drift_M5"]:+.1f} '
                  f'pnl_M5=${f["pnl_M5"]:+.1f}')


if __name__ == '__main__':
    main()
