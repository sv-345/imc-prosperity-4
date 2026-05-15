"""Why does wall_fv give +3713 on day=-2 training?

Compare fill profile: baseline vs wall_fv.
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
    TradingState, _cross_trader_orders, _build_order_depth,
)
from training_book_replay import load_day_ticks, load_day_trades
from server_book_replay_v2 import _apply_trade


def trace(trader, product, day="-2"):
    all_ticks = load_day_ticks(day)
    all_trades = load_day_trades(day)
    prod_ticks = sorted(
        [t for (p, ts), t in all_ticks.items() if p == product],
        key=lambda r: r["ts"],
    )
    position = 0
    cash = 0.0
    trader_data = ""
    sink = io.StringIO()
    all_fills = []

    for r in prod_ticks:
        book_buys = {int(p): int(v) for p, v in r["bids"]}
        book_sells = {int(p): int(v) for p, v in r["asks"]}
        strat_buys: dict = {}
        strat_sells: dict = {}
        tick_mts = all_trades.get((product, r["ts"]), [])

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


for label, osm in [("baseline", {}), ("wall_fv", {"use_wall_fv": True})]:
    t = make_trader(osm=osm)
    fills, cash, pos = trace(t, "ASH_COATED_OSMIUM")
    buys = [(p, q) for (_, s, p, q, _) in fills if s == "BUY"]
    sells = [(p, q) for (_, s, p, q, _) in fills if s == "SELL"]
    bq = sum(q for _, q in buys)
    sq = sum(q for _, q in sells)
    bp = sum(p*q for p, q in buys)/bq if bq else 0
    sp = sum(p*q for p, q in sells)/sq if sq else 0
    print(f"{label:>10}: fills={len(fills)} buys={len(buys)}/q={bq} avg_p={bp:.2f}  "
          f"sells={len(sells)}/q={sq} avg_p={sp:.2f}  pos={pos}  cash={cash:.0f}")
    # By source
    srcs = Counter(f[4] for f in fills)
    print(f"           sources: {dict(srcs)}")
    # Sells by price
    sell_prices = Counter(p for p, _ in sells)
    print(f"           sell prices: {sorted(sell_prices.items())[:15]}")
