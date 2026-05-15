"""Deterministic server-book replay: use REAL market_trades from 127989 log as takers.

Unlike v1 (RNG-sampled taker side), v2 infers side from trade price vs book
state AND caps fills at the actual trade price. Our sells at price > trade.price
can't fill (a real hidden seller was at a lower price); our buys at price <
trade.price can't fill (a real hidden buyer was at a higher price).

This eliminates two bugs:
- v1: fake BUY taker at one-sided ticks → fills deep sell
- early v2: one-sided fill at our inflated price → wide-edge monotonic gains
"""
from __future__ import annotations
import io
import json
from contextlib import redirect_stdout
from pathlib import Path

from synth_replay import (
    Order, OrderDepth, TradingState, Trade,
    Fill, SessionResult, _cross_trader_orders, _build_order_depth,
)
from server_book_replay import DATA, load_ticks, load_market_trades, _mt_to_trade


def _trade_side(trade_price, book_buys, book_sells):
    best_bid = max(book_buys) if book_buys else None
    best_ask = min(book_sells) if book_sells else None
    if best_bid is not None and best_ask is not None:
        mid = (best_bid + best_ask) / 2
        return "BUY" if trade_price > mid else "SELL"
    if best_bid is not None:
        return "BUY" if trade_price > best_bid else "SELL"
    if best_ask is not None:
        return "BUY" if trade_price >= best_ask else "SELL"
    return None


def _apply_trade(trade, book_buys, book_sells, strat_buys, strat_sells,
                 position, limit, ts):
    """Apply one market_trade as a taker event, capped at trade price.

    If side=BUY (taker buys), our SELL at price ≤ trade_price can fill at our price.
    If side=SELL (taker sells), our BUY at price ≥ trade_price can fill at our price.
    Bot book fills first at tied price; remaining qty hits strat orders.
    """
    side = _trade_side(trade.price, book_buys, book_sells)
    if side is None:
        return [], position, 0.0

    fills = []
    cash = 0.0
    qty = trade.quantity
    tp = trade.price

    if side == "BUY":
        # Walk asks at price ≤ trade_price (the taker was willing to pay tp).
        ask_prices = sorted(p for p in set(book_sells) | set(strat_sells) if p <= tp)
        for px in ask_prices:
            if qty <= 0:
                break
            bot_vol = book_sells.get(px, 0)
            if bot_vol > 0:
                take = min(qty, bot_vol)
                book_sells[px] -= take
                if book_sells[px] == 0:
                    del book_sells[px]
                qty -= take
            if qty <= 0:
                break
            strat_vol = strat_sells.get(px, 0)
            if strat_vol > 0:
                cap = limit + position
                take = min(qty, strat_vol, max(0, cap))
                if take > 0:
                    strat_sells[px] -= take
                    if strat_sells[px] == 0:
                        del strat_sells[px]
                    position -= take
                    cash += px * take
                    fills.append(Fill(ts=ts, product="", side="SELL",
                                      price=px, qty=take, source="taker"))
                    qty -= take
    else:  # SELL
        bid_prices = sorted((p for p in set(book_buys) | set(strat_buys) if p >= tp),
                            reverse=True)
        for px in bid_prices:
            if qty <= 0:
                break
            bot_vol = book_buys.get(px, 0)
            if bot_vol > 0:
                take = min(qty, bot_vol)
                book_buys[px] -= take
                if book_buys[px] == 0:
                    del book_buys[px]
                qty -= take
            if qty <= 0:
                break
            strat_vol = strat_buys.get(px, 0)
            if strat_vol > 0:
                cap = limit - position
                take = min(qty, strat_vol, max(0, cap))
                if take > 0:
                    strat_buys[px] -= take
                    if strat_buys[px] == 0:
                        del strat_buys[px]
                    position += take
                    cash -= px * take
                    fills.append(Fill(ts=ts, product="", side="BUY",
                                      price=px, qty=take, source="taker"))
                    qty -= take

    return fills, position, cash


def run_server_session_v2(trader, product, session="127989"):
    ticks = load_ticks(product, session=session)
    mt_by_ts = load_market_trades(product, session=session)
    result = SessionResult(product=product, seed=0)
    position = 0
    cash = 0.0
    trader_data = ""
    sink = io.StringIO()

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
    last_mid = ticks[-1].get("mid_price", 10000)
    result.final_fv = last_mid or 10000
    return result


# Back-compat for pep_position_trace etc. that imported _trades_to_takers_v2
def _trades_to_takers_v2(trades_at_tick, book_buys, book_sells):
    """Back-compat shim — returns TakerEvent list for scripts still using old API.
    Note: these TakerEvents are NOT used by run_server_session_v2 anymore (fix above)."""
    from synth_book import TakerEvent
    takers = []
    for t in trades_at_tick:
        side = _trade_side(t.price, book_buys, book_sells)
        if side is None:
            continue
        takers.append(TakerEvent(side=side, qty=t.quantity, price_tol=0))
    return takers


if __name__ == "__main__":
    from parametric_trader import make_trader
    print("Server ground-truth: 127989 OSM=3144 PEP=7577")
    for edge in [12, 16, 22, 30, 40, 100]:
        t = make_trader(osm={"quote_edge": edge})
        r = run_server_session_v2(t, "ASH_COATED_OSMIUM")
        print(f"  edge={edge:3d}: OSM v2 PnL={r.pnl:7.0f}  fills={len(r.fills)}")
    for thr in [55, 60, 65, 70, 75]:
        t = make_trader(pep={"accumulate_threshold": thr})
        r = run_server_session_v2(t, "INTARIAN_PEPPER_ROOT")
        print(f"  thr={thr:3d}: PEP v2 PnL={r.pnl:7.0f}  fills={len(r.fills)}")
