"""Fixed version of training_book_replay.

Fix: at one-sided ticks (no_ask or no_bid), don't default trade side to BUY.
Instead, use best_bid/best_ask as reference for side classification.
Empty side → use other side's top price:
  - asks=[] → mid ~ best_bid. Trade at price <= best_bid is SELL, > best_bid is BUY
  - bids=[] → mid ~ best_ask. Trade at price >= best_ask is BUY, < best_ask is SELL
"""
from __future__ import annotations
import csv
import io
import json
from contextlib import redirect_stdout
from pathlib import Path

from synth_replay import (
    Order, OrderDepth, TradingState, Trade,
    Fill, SessionResult, _cross_trader_orders, _build_order_depth,
)
from training_book_replay import DATA_DIR, load_day_ticks, load_day_trades
from server_book_replay_v2 import _apply_trade


def _trades_to_takers_v2(trades_at_tick, book_buys, book_sells):
    """Infer taker side even on one-sided books using best-bid or best-ask reference."""
    takers = []
    best_bid = max(book_buys) if book_buys else None
    best_ask = min(book_sells) if book_sells else None

    for t in trades_at_tick:
        side = None
        if best_bid is not None and best_ask is not None:
            mid = (best_bid + best_ask) / 2
            side = "BUY" if t.price > mid else "SELL"
        elif best_bid is not None:  # asks=[]
            # Use bid as reference. Trade above best_bid → BUY (IOC ask-sweep). Trade at/below → SELL.
            side = "BUY" if t.price > best_bid else "SELL"
        elif best_ask is not None:  # bids=[]
            side = "BUY" if t.price >= best_ask else "SELL"
        else:
            # both empty: skip (can't infer)
            continue
        takers.append(TakerEvent(side=side, qty=t.quantity, price_tol=0))
    return takers


def run_training_session_v2(trader, product, day):
    """Same as v1 but with fixed taker-side inference."""
    all_ticks = load_day_ticks(day)
    all_trades = load_day_trades(day)
    prod_ticks = sorted(
        [t for (p, ts), t in all_ticks.items() if p == product],
        key=lambda r: r["ts"],
    )

    result = SessionResult(product=product, seed=0)
    position = 0
    cash = 0.0
    trader_data = ""
    sink = io.StringIO()

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
            f.product = product
            result.fills.append(f)

        for t in tick_mts:
            t_fills, position, cash_delta = _apply_trade(
                t, book_buys, book_sells, strat_buys, strat_sells,
                position, limit=80, ts=r["ts"],
            )
            cash += cash_delta
            for f in t_fills:
                f.product = product
                result.fills.append(f)

    result.cash = cash
    result.final_pos = position
    last_mid = prod_ticks[-1].get("mid_price", 10000)
    result.final_fv = last_mid or 10000
    return result


if __name__ == "__main__":
    from parametric_trader import make_trader
    import sys

    # Compare v1 vs v2 at several edges to see impact of the fix
    from training_book_replay import run_training_session as v1_run

    for day in ["-2", "-1", "0"]:
        print(f"\n=== day={day} ===")
        for edge in [12, 22, 40, 100]:
            t = make_trader(osm={"quote_edge": edge})
            p1 = v1_run(t, "ASH_COATED_OSMIUM", day).pnl
            t = make_trader(osm={"quote_edge": edge})
            p2 = run_training_session_v2(t, "ASH_COATED_OSMIUM", day).pnl
            print(f"  edge={edge:3d}: v1={p1:6.0f}  v2={p2:6.0f}  Δ={p2-p1:+5.0f}")
