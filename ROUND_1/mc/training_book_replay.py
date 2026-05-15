"""Replay a submission Trader against training-day book snapshots (day -2, -1, 0).

Unlike server_book_replay.py (1000-tick live session from 127989's log), this uses
10000-tick training CSVs. Takers are derived from real trades_round_1_day_X.csv
— no MC randomness — giving a fully deterministic per-day replay.

This is our closest analog to running the strategy on a full live session.
"""
from __future__ import annotations
import csv
import io
import json
from contextlib import redirect_stdout
from dataclasses import dataclass, field
from pathlib import Path

from synth_replay import (
    Order, OrderDepth, TradingState, Trade,
    Fill, SessionResult, _cross_trader_orders, _apply_taker, _build_order_depth,
)
from synth_book import TakerEvent


DATA_DIR = Path(__file__).parent.parent / "data" / "ROUND1"


def load_day_ticks(day):
    path = DATA_DIR / f"prices_round_1_day_{day}.csv"
    by_prod_ts: dict = {}
    with open(path) as f:
        reader = csv.DictReader(f, delimiter=";")
        for r in reader:
            ts = int(r["timestamp"])
            prod = r["product"]
            def i(key):
                v = r[key]
                return int(v) if v else None
            bids = []
            for pi, vi in [("bid_price_1", "bid_volume_1"),
                            ("bid_price_2", "bid_volume_2"),
                            ("bid_price_3", "bid_volume_3")]:
                bp, bv = i(pi), i(vi)
                if bp is not None:
                    bids.append([bp, bv])
            asks = []
            for pi, vi in [("ask_price_1", "ask_volume_1"),
                            ("ask_price_2", "ask_volume_2"),
                            ("ask_price_3", "ask_volume_3")]:
                ap, av = i(pi), i(vi)
                if ap is not None:
                    asks.append([ap, av])
            mid = float(r["mid_price"]) if r["mid_price"] else None
            by_prod_ts[(prod, ts)] = {
                "ts": ts, "product": prod, "bids": bids, "asks": asks,
                "mid_price": mid,
            }
    return by_prod_ts


def load_day_trades(day):
    """Trades from CSV. Return {ts: [Trade,...]} per product."""
    path = DATA_DIR / f"trades_round_1_day_{day}.csv"
    by_prod_ts: dict = {}
    with open(path) as f:
        reader = csv.DictReader(f, delimiter=";")
        for r in reader:
            prod = r["symbol"]
            ts = int(r["timestamp"])
            price = float(r["price"])
            qty = int(r["quantity"])
            trade = Trade(symbol=prod, price=price, quantity=qty,
                          buyer=r.get("buyer", ""), seller=r.get("seller", ""),
                          timestamp=ts)
            by_prod_ts.setdefault((prod, ts), []).append(trade)
    return by_prod_ts


def _trades_to_takers(trades_at_tick, strat_buys, strat_sells, book_buys, book_sells):
    """Convert trades to TakerEvents by inferring side from price vs mid.
    A trade at price closer to ask = BUY (taker bought); closer to bid = SELL.
    """
    takers = []
    if not book_buys and not book_sells:
        return takers
    best_bid = max(book_buys) if book_buys else None
    best_ask = min(book_sells) if book_sells else None
    mid = None
    if best_bid is not None and best_ask is not None:
        mid = (best_bid + best_ask) / 2
    for t in trades_at_tick:
        side = "BUY"
        if mid is not None:
            # Trade at price > mid → someone lifted an ask → BUY taker
            # Trade at price < mid → someone hit a bid → SELL taker
            side = "BUY" if t.price > mid else "SELL"
        takers.append(TakerEvent(side=side, qty=t.quantity, price_tol=0))
    return takers


def run_training_session(trader, product, day):
    """Deterministic replay of one training day for one product."""
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

        # Prior-tick market trades (like server format)
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

        # Apply takers from real trades (deterministic)
        for ev in _trades_to_takers(tick_mts, strat_buys, strat_sells, book_buys, book_sells):
            t_fills, position, cash_delta = _apply_taker(
                ev, book_buys, book_sells, strat_buys, strat_sells,
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
    for day in ["-2", "-1", "0"]:
        for prod in ["ASH_COATED_OSMIUM", "INTARIAN_PEPPER_ROOT"]:
            t = make_trader()
            r = run_training_session(t, prod, day)
            print(f"day={day} {prod}: PnL={r.pnl:.0f} fills={len(r.fills)} final_pos={r.final_pos}")
