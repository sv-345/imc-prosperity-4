"""Parse submission 294069 activitiesLog into per-tick book + reconstruct fills.

The IMC server JSON has no own_trades section. We infer fills from per-product
PnL changes. Per chrispyroberts-imc-prosperity-4/backtester/prosperity3bt/runner.py
the activitiesLog row at tick T is written BEFORE trade matching:

    profit_loss(T) = cash_after_trade_T-1 + pos_after_trade_T-1 * mid(T)

So a trade executed at tick T (matching against book(T)) shows up as a PnL
change at tick T+1:

    ΔPnL(T→T+1) = ΔP(T) * (mid(T+1) - fill_price(T))
                  + pos_pre_T(=pos_post_T-1) * (mid(T+1) - mid(T))

We solve for integer ΔP(T) ∈ {-25..25} (QUOTE_SIZE_CAP=25) and integer
fill_price(T). Initial state: pos(0)=0, cash(0)=0.

Output: per-product fills attributed to the tick at which the trade actually
happened (i.e. the tick T whose order_depth was crossed), not the next tick.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from typing import Dict, List


LOG_PATH = '/tmp/prosperity_logs/294069/302973.json'
OUTPUT_PATH = '/tmp/294069_parsed.json'


@dataclass
class BookTick:
    ts: int
    product: str
    bid: int           # best bid price (top of book) at tick T (pre-trade snapshot)
    bid_vol: int
    ask: int           # best ask price
    ask_vol: int
    mid: float
    pnl: float


@dataclass
class Fill:
    ts: int            # tick at which the fill happened (book at this tick was crossed)
    product: str
    side: str          # 'BUY' (we got bought from a seller) or 'SELL' (we got hit by a buyer)
    qty: int
    price: int
    pre_pos: int       # position going INTO this fill
    pre_bid: int       # best bid in book(T) — the book that was crossed
    pre_ask: int       # best ask in book(T)
    pre_mid: float     # mid(T) — pre-fill snapshot
    post_mid: float    # mid(T+1) — first post-fill snapshot
    pnl_jump: float    # observed PnL change attributable to this fill


def parse_activities(raw_log: str) -> Dict[str, List[BookTick]]:
    by_prod: Dict[str, List[BookTick]] = {}
    lines = raw_log.strip().split('\n')
    cols = {name: i for i, name in enumerate(lines[0].split(';'))}
    for line in lines[1:]:
        row = line.split(';')
        ts = int(row[cols['timestamp']])
        prod = row[cols['product']]
        bid = row[cols['bid_price_1']]
        ask = row[cols['ask_price_1']]
        bid_vol = row[cols['bid_volume_1']]
        ask_vol = row[cols['ask_volume_1']]
        by_prod.setdefault(prod, []).append(BookTick(
            ts=ts, product=prod,
            bid=int(bid) if bid else 0,
            bid_vol=int(bid_vol) if bid_vol else 0,
            ask=int(ask) if ask else 0,
            ask_vol=int(ask_vol) if ask_vol else 0,
            mid=float(row[cols['mid_price']]),
            pnl=float(row[cols['profit_and_loss']]),
        ))
    for v in by_prod.values():
        v.sort(key=lambda t: t.ts)
    return by_prod


def infer_fills(ticks: List[BookTick],
                qty_search: int = 30,
                price_tol: float = 0.05) -> List[Fill]:
    """Reconstruct fills from per-tick PnL deltas.

    The trade at tick T affects PnL(T+1):
        ΔPnL = ΔP*(mid(T+1) - fp) + pos_pre_T * (mid(T+1) - mid(T))

    We attribute each detected fill to tick T (the book that was crossed).
    """
    fills: List[Fill] = []
    cash = 0.0
    pos = 0  # position going INTO each tick (= post-trade of previous tick)

    # Sanity: log_pnl(0) should equal 0 + 0 * mid(0) = 0.
    if abs(ticks[0].pnl) > 1e-6:
        print(f'  WARN {ticks[0].product}: pnl(0) = {ticks[0].pnl} != 0')

    for i in range(len(ticks) - 1):
        t = ticks[i]              # book(T) — pre-trade snapshot for tick T
        t_next = ticks[i + 1]     # log row at T+1 reflects post-trade-T state

        # ΔPnL between log rows T and T+1 = effect of trade at tick T.
        d_pnl = t_next.pnl - t.pnl
        d_mid = t_next.mid - t.mid

        # Subtract MTM-on-existing-position component to isolate trade contribution.
        trade_contrib = d_pnl - pos * d_mid
        # trade_contrib = ΔP * (mid(T+1) - fp)

        if abs(trade_contrib) < 1e-6:
            # No trade at tick T.
            continue

        # Search integer ΔP ∈ ±qty_search for which fill_price is integer.
        best = None  # (residual, dP, fp_int)
        for dP in range(-qty_search, qty_search + 1):
            if dP == 0:
                continue
            fp = t_next.mid - trade_contrib / dP
            fp_int = round(fp)
            residual = abs(fp - fp_int)
            if residual > price_tol:
                continue
            # Sanity: fill_price should be in or near the crossed book.
            if abs(fp_int - t.mid) > 30:
                continue
            cand = (residual, dP, fp_int)
            if best is None or cand[0] < best[0]:
                best = cand

        if best is None:
            # Couldn't fit any integer fill. Print for debugging.
            print(f'  UNRESOLVED {t.product} ts={t.ts}: trade_contrib={trade_contrib:.6f} pos_pre={pos} mid(T)={t.mid} mid(T+1)={t_next.mid}')
            continue

        _, dP, fp_int = best
        side = 'BUY' if dP > 0 else 'SELL'
        qty = abs(dP)
        fills.append(Fill(
            ts=t.ts, product=t.product, side=side,
            qty=qty, price=fp_int,
            pre_pos=pos,
            pre_bid=t.bid, pre_ask=t.ask,
            pre_mid=t.mid, post_mid=t_next.mid,
            pnl_jump=trade_contrib,
        ))
        cash -= dP * fp_int
        pos += dP

    return fills, cash, pos


def main():
    with open(LOG_PATH) as f:
        data = json.load(f)
    by_prod = parse_activities(data['activitiesLog'])

    out = {
        'submission_id': '294069',
        'profit_total': data['profit'],
        'final_positions_server': data['positions'],
        'products': {},
    }

    for prod, ticks in by_prod.items():
        fills, cash, pos = infer_fills(ticks)
        # Verify: reconstructed final PnL should match observed (with the
        # post-trade marking caveat — last tick's log row reflects the
        # post-trade state of the second-to-last tick).
        observed = ticks[-1].pnl

        # Reconstruct cumulative PnL at last log row by replaying all fills.
        rep_cash = 0.0
        rep_pos = 0
        for f in fills:
            dP = f.qty if f.side == 'BUY' else -f.qty
            rep_cash -= dP * f.price
            rep_pos += dP
        # The last log row (i = len(ticks)-1) marks post-trade state of the
        # tick BEFORE the last. We replayed all fills including the last tick,
        # but the last tick's fill (if any) wouldn't show in the final log row.
        # However, if our loop included i = len-2 → t = ticks[-2], t_next = ticks[-1],
        # then the fill at ticks[-2] was attributed and DOES contribute to pnl[-1].
        # The fill at ticks[-1] (if any) is NOT detected (no T+1 to compare).
        # So rep_cash + rep_pos * mid_last should match pnl_last.
        recon_pnl = rep_cash + rep_pos * ticks[-1].mid

        # Resolve: do BUY and SELL counts make sense?
        n_buy = sum(1 for f in fills if f.side == 'BUY')
        n_sell = sum(1 for f in fills if f.side == 'SELL')
        q_buy = sum(f.qty for f in fills if f.side == 'BUY')
        q_sell = sum(f.qty for f in fills if f.side == 'SELL')

        print(f'\n{prod}:')
        print(f'  ticks: {len(ticks)}')
        print(f'  fills: {len(fills)}  (BUY={n_buy} qty={q_buy}  SELL={n_sell} qty={q_sell})')
        print(f'  net qty: {q_buy - q_sell}  (server final pos: see below)')
        print(f'  observed pnl(last): {observed:.4f}')
        print(f'  reconstructed pnl(last): {recon_pnl:.4f}')
        print(f'  match: {abs(observed - recon_pnl) < 1e-3}')

        out['products'][prod] = {
            'fills': [asdict(f) for f in fills],
            'ticks': [asdict(t) for t in ticks],
            'reconstructed_final_pnl': recon_pnl,
            'observed_final_pnl': observed,
            'final_position': rep_pos,
            'n_buy': n_buy, 'n_sell': n_sell,
            'qty_buy': q_buy, 'qty_sell': q_sell,
        }

    with open(OUTPUT_PATH, 'w') as f:
        json.dump(out, f)
    n = sum(len(p['fills']) for p in out['products'].values())
    print(f'\nServer reports final positions: {data["positions"]}')
    print(f'Wrote {OUTPUT_PATH} ({n} total fills)')


if __name__ == '__main__':
    main()
