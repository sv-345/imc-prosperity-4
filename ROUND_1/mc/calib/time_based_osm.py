"""Time-aware OSM: does PnL accumulate differently across session phases?

Hypothesis: maybe early-session needs different params than late. Check PnL
profile across phases.
"""
from __future__ import annotations
import io
import sys
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from parametric_trader import make_trader
from synth_replay import (
    TradingState, _cross_trader_orders, _build_order_depth,
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
    trajectory = []  # (ts, pos, cash, mid, mark)

    for r in ticks:
        book_buys = {int(p): int(v) for p, v in r["bids"]}
        book_sells = {int(p): int(v) for p, v in r["asks"]}
        strat_buys: dict = {}
        strat_sells: dict = {}
        tick_mts = [_mt_to_trade(m) for m in mt_by_ts.get(r["ts"], [])]

        od = _build_order_depth(book_buys, book_sells)
        state = TradingState(
            timestamp=r["ts"], order_depths={product: od},
            position={product: position},
            market_trades={product: tick_mts}, own_trades={product: []},
            trader_data=trader_data,
        )
        with redirect_stdout(sink):
            rd, _conv, trader_data = trader.run(state)
        orders = rd.get(product, []) or []
        _, position, cash_delta = _cross_trader_orders(
            orders, book_buys, book_sells, strat_buys, strat_sells,
            position, limit=80, ts=r["ts"])
        cash += cash_delta
        for t in tick_mts:
            _, position, cash_delta = _apply_trade(
                t, book_buys, book_sells, strat_buys, strat_sells,
                position, limit=80, ts=r["ts"])
            cash += cash_delta
        bb = max(book_buys) if book_buys else None
        ba = min(book_sells) if book_sells else None
        mid = (bb + ba) / 2 if bb and ba else 10000
        mark = cash + position * mid
        trajectory.append((r["ts"], position, cash, mid, mark))

    return trajectory


for label, osm in [
    ("baseline", {}),
    ("wall_fv+ema5+e22", {"use_wall_fv": True, "wall_fv_ema_alpha": 0.5, "quote_edge": 22}),
]:
    t = make_trader(osm=osm)
    tj = trace(t, "ASH_COATED_OSMIUM")
    marks = [m for _, _, _, _, m in tj]
    # Per-quartile PnL accumulation
    q = len(marks) // 4
    print(f"\n{label}")
    print(f"  mark at 25%: {marks[q]:.0f}")
    print(f"  mark at 50%: {marks[2*q]:.0f}")
    print(f"  mark at 75%: {marks[3*q]:.0f}")
    print(f"  mark final:   {marks[-1]:.0f}")
    # PnL delta per quartile
    print(f"  Δ Q1: {marks[q] - 0:+.0f}")
    print(f"  Δ Q2: {marks[2*q] - marks[q]:+.0f}")
    print(f"  Δ Q3: {marks[3*q] - marks[2*q]:+.0f}")
    print(f"  Δ Q4: {marks[-1] - marks[3*q]:+.0f}")
