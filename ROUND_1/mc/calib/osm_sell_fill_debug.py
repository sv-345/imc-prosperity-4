"""Why does sell_edge=50 give +3876 live? Trace WHEN sells at extreme prices fill."""
from __future__ import annotations
import io
import sys
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from parametric_trader import make_trader
from synth_replay import (
    Order, TradingState,
    _cross_trader_orders, _apply_taker, _build_order_depth,
)
from server_book_replay import load_ticks, load_market_trades, _mt_to_trade
from server_book_replay_v2 import _trades_to_takers_v2


def trace(trader, product, session="127989"):
    ticks = load_ticks(product, session=session)
    mt_by_ts = load_market_trades(product, session=session)
    position = 0
    cash = 0.0
    trader_data = ""
    sink = io.StringIO()
    high_sell_fills = []  # (ts, price, qty, source) where source is 'cross' or taker side

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

        cross_fills, position, cash_delta = _cross_trader_orders(
            orders, book_buys, book_sells, strat_buys, strat_sells,
            position, limit=80, ts=r["ts"],
        )
        cash += cash_delta
        for f in cross_fills:
            if f.side == "SELL" and f.price >= 10020:
                high_sell_fills.append((r["ts"], f.price, f.qty, f.source))

        for ev in _trades_to_takers_v2(tick_mts, book_buys, book_sells):
            t_fills, position, cash_delta = _apply_taker(
                ev, book_buys, book_sells, strat_buys, strat_sells,
                position, limit=80, ts=r["ts"],
            )
            cash += cash_delta
            for f in t_fills:
                if f.side == "SELL" and f.price >= 10020:
                    high_sell_fills.append((r["ts"], f.price, f.qty, f"taker_{ev.side}"))

    return high_sell_fills, cash, position


t = make_trader(osm={"buy_edge": 12, "sell_edge": 50})
fills, cash, pos = trace(t, "ASH_COATED_OSMIUM")
print(f"OSM with se=50: {len(fills)} high-price sell fills")
print(f"  final cash={cash:.0f}  pos={pos}")
# Show first and last few
for (ts, pr, qty, src) in fills[:10]:
    print(f"    ts={ts:6d}  price={pr}  qty={qty:3d}  src={src}")
print("...")
for (ts, pr, qty, src) in fills[-5:]:
    print(f"    ts={ts:6d}  price={pr}  qty={qty:3d}  src={src}")

# Distribution by price
from collections import Counter
c = Counter(pr for (_, pr, _, _) in fills)
print(f"\n  price distribution of high-sell fills:")
for pr, n in sorted(c.items()):
    print(f"    {pr}: {n}")

# Distribution by source
c2 = Counter(src for (_, _, _, src) in fills)
print(f"\n  source distribution:")
for s, n in sorted(c2.items()):
    print(f"    {s}: {n}")
