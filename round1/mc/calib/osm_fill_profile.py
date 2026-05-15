"""Profile OSM fills in fixed v2: how do we make the 1387?

Server actual got 3144. We predict 1387 — where are the missing fills?
"""
from __future__ import annotations
import io
import sys
from collections import Counter
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from parametric_trader import make_trader
from synth_replay import (
    Order, OrderDepth, TradingState, Trade,
    _cross_trader_orders, _build_order_depth,
)
from server_book_replay import load_ticks, load_market_trades, _mt_to_trade
from server_book_replay_v2 import _apply_trade


def trace(trader, product, session="127989"):
    ticks = load_ticks(product, session=session)
    mt_by_ts = load_market_trades(product, session=session)
    position = 0
    cash = 0.0
    trader_data = ""
    sink = io.StringIO()
    all_fills = []
    orders_placed = Counter()  # (side, price_offset_from_fv)

    for r in ticks:
        book_buys = {int(p): int(v) for p, v in r["bids"]}
        book_sells = {int(p): int(v) for p, v in r["asks"]}
        strat_buys: dict = {}
        strat_sells: dict = {}
        tick_mts = [_mt_to_trade(m) for m in mt_by_ts.get(r["ts"], [])]

        od = _build_order_depth(book_buys, book_sells)
        state = TradingState(
            timestamp=r["ts"],
            order_depths={product: od},
            position={product: position},
            market_trades={product: tick_mts},
            own_trades={product: []},
            trader_data=trader_data,
        )
        with redirect_stdout(sink):
            rd, _conv, trader_data = trader.run(state)
        orders = rd.get(product, []) or []
        for o in orders:
            side = "B" if o.quantity > 0 else "S"
            orders_placed[(side, o.price - 10000)] += 1

        cross_fills, position, cash_delta = _cross_trader_orders(
            orders, book_buys, book_sells, strat_buys, strat_sells,
            position, limit=80, ts=r["ts"],
        )
        cash += cash_delta
        for f in cross_fills:
            all_fills.append((r["ts"], f.side, f.price, f.qty, f.source))

        for t in tick_mts:
            t_fills, position, cash_delta = _apply_trade(
                t, book_buys, book_sells, strat_buys, strat_sells,
                position, limit=80, ts=r["ts"],
            )
            cash += cash_delta
            for f in t_fills:
                all_fills.append((r["ts"], f.side, f.price, f.qty, f.source))

    return all_fills, cash, position


t = make_trader()  # baseline
fills, cash, pos = trace(t, "ASH_COATED_OSMIUM")
print(f"Baseline OSM v2: cash={cash:.0f}  pos={pos}  fills={len(fills)}")

# Fills by price and side
buys = [(f[2], f[3]) for f in fills if f[1] == "BUY"]
sells = [(f[2], f[3]) for f in fills if f[1] == "SELL"]

print(f"\n  buys: {len(buys)}  total_qty={sum(q for _, q in buys)}")
c = Counter(p for p, _ in buys)
for p in sorted(c):
    qty = sum(q for pp, q in buys if pp == p)
    print(f"    price={p}: {c[p]} fills, qty={qty}")

print(f"\n  sells: {len(sells)}  total_qty={sum(q for _, q in sells)}")
c = Counter(p for p, _ in sells)
for p in sorted(c):
    qty = sum(q for pp, q in sells if pp == p)
    print(f"    price={p}: {c[p]} fills, qty={qty}")

# By source
src_c = Counter(f[4] for f in fills)
print(f"\n  sources: {dict(src_c)}")

# Break down buys/sells by source
for src in ("cross", "taker"):
    b = [(p, q) for (_, s, p, q, so) in fills if s == "BUY" and so == src]
    s = [(p, q) for (_, s, p, q, so) in fills if s == "SELL" and so == src]
    print(f"  {src}:")
    if b:
        print(f"    buys: {len(b)} fills qty={sum(q for _, q in b)} avg_p={sum(p*q for p,q in b)/sum(q for _,q in b):.2f}")
    if s:
        print(f"    sells: {len(s)} fills qty={sum(q for _, q in s)} avg_p={sum(p*q for p,q in s)/sum(q for _,q in s):.2f}")

# Mean entry cost
buy_qty = sum(q for _, q in buys)
buy_cost = sum(p*q for p, q in buys)
if buy_qty:
    print(f"\n  avg buy price: {buy_cost/buy_qty:.2f}")
sell_qty = sum(q for _, q in sells)
sell_cost = sum(p*q for p, q in sells)
if sell_qty:
    print(f"  avg sell price: {sell_cost/sell_qty:.2f}")
print(f"  net_qty: {buy_qty - sell_qty} (pos: {pos})")
