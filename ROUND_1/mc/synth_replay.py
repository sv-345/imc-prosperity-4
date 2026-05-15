"""Synthetic session replay: runs a REAL Trader through synth books, with takers.

Tick semantics (matches IMC Prosperity + book_replay.py):
  (1) Build fresh bot book from synth (walls + inner, fresh volumes).
  (2) Trader.run(state) — returns orders for this tick.
  (3) Trader orders match book:
        - Crossing orders (bid >= best ask, or ask <= best bid) consume bot
          liquidity immediately; remainders rest at the trader's price as
          strat_vol for this tick only.
        - Non-crossing orders rest as strat_vol at their price.
  (4) Takers arrive (0..n per tick), hit the combined book best-price:
        - At each price, BOT fills first, then STRAT (owner priority).
  (5) End of tick: book discarded. Next tick starts fresh.

Strat orders do NOT persist across ticks (Prosperity engine cancels them at
end of tick).
"""
from __future__ import annotations
import io
import statistics
import sys as _sys
from contextlib import redirect_stdout
from dataclasses import dataclass, field

from synth_book import (
    gen_osmium_session, gen_pepper_session, TickSnapshot,
)


class Order:
    def __init__(self, symbol, price, quantity):
        self.symbol = symbol
        self.price = int(price)
        self.quantity = int(quantity)


class OrderDepth:
    def __init__(self):
        self.buy_orders = {}
        self.sell_orders = {}


class Trade:
    def __init__(self, symbol, price, quantity, buyer="", seller="", timestamp=0):
        self.symbol = symbol
        self.price = int(price)
        self.quantity = int(quantity)
        self.buyer = buyer
        self.seller = seller
        self.timestamp = timestamp


class TradingState:
    def __init__(self, timestamp, order_depths, position, market_trades,
                 own_trades=None, trader_data=""):
        self.timestamp = timestamp
        self.order_depths = order_depths
        self.position = position
        self.market_trades = market_trades or {}
        self.own_trades = own_trades or {}
        self.observations = type("O", (), {"conversionObservations": {}})()
        self.listings = {}
        self.traderData = trader_data


@dataclass
class Fill:
    ts: int
    product: str
    side: str  # "BUY" | "SELL"
    price: int
    qty: int
    source: str = ""  # "cross" or "taker"


@dataclass
class SessionResult:
    product: str
    seed: int
    fills: list = field(default_factory=list)
    cash: float = 0.0
    final_pos: int = 0
    final_fv: float = 0.0

    @property
    def pnl(self) -> float:
        return self.cash + self.final_pos * self.final_fv


def _cross_trader_orders(orders, book_buys, book_sells, strat_buys, strat_sells,
                          position, limit, ts):
    """Step (3): match crossing trader orders against bot book; rest remainders.

    Returns (fills, new_position, cash_delta).
    """
    fills = []
    cash = 0.0

    for o in orders:
        if o.quantity == 0:
            continue
        if o.quantity > 0:  # trader BUY
            max_buy = limit - position
            if max_buy <= 0:
                continue
            qty = min(o.quantity, max_buy)
            # Cross: walk asks at price <= o.price
            ask_prices = sorted(p for p in book_sells if p <= o.price)
            for ap in ask_prices:
                if qty <= 0:
                    break
                take = min(qty, book_sells[ap])
                if take > 0:
                    book_sells[ap] -= take
                    if book_sells[ap] == 0:
                        del book_sells[ap]
                    position += take
                    cash -= ap * take
                    fills.append(Fill(ts=ts, product="", side="BUY",
                                      price=ap, qty=take, source="cross"))
                    qty -= take
            if qty > 0:
                strat_buys[o.price] = strat_buys.get(o.price, 0) + qty
        else:  # trader SELL
            max_sell = limit + position
            if max_sell <= 0:
                continue
            qty = min(-o.quantity, max_sell)
            bid_prices = sorted((p for p in book_buys if p >= o.price), reverse=True)
            for bp in bid_prices:
                if qty <= 0:
                    break
                take = min(qty, book_buys[bp])
                if take > 0:
                    book_buys[bp] -= take
                    if book_buys[bp] == 0:
                        del book_buys[bp]
                    position -= take
                    cash += bp * take
                    fills.append(Fill(ts=ts, product="", side="SELL",
                                      price=bp, qty=take, source="cross"))
                    qty -= take
            if qty > 0:
                strat_sells[o.price] = strat_sells.get(o.price, 0) + qty

    return fills, position, cash


def _apply_taker(taker, book_buys, book_sells, strat_buys, strat_sells,
                  position, limit, ts):
    """Step (4): taker hits combined book at best price, bot-first at tied price.

    Returns (strat_fills, new_position, cash_delta).
    strat_fills = only those where taker hit our resting orders (our flow).
    """
    fills = []
    cash = 0.0

    if taker.side == "BUY":
        all_prices = set(book_sells) | set(strat_sells)
        if not all_prices:
            return fills, position, cash
        best = min(all_prices)
        prices = sorted(p for p in all_prices if p <= best + taker.price_tol)
    else:
        all_prices = set(book_buys) | set(strat_buys)
        if not all_prices:
            return fills, position, cash
        best = max(all_prices)
        prices = sorted((p for p in all_prices if p >= best - taker.price_tol),
                        reverse=True)

    qty = taker.qty
    for px in prices:
        if qty <= 0:
            break
        if taker.side == "BUY":
            bot_pool = book_sells
            strat_pool = strat_sells
        else:
            bot_pool = book_buys
            strat_pool = strat_buys

        # Bot first
        bot_vol = bot_pool.get(px, 0)
        if bot_vol > 0:
            take = min(qty, bot_vol)
            bot_pool[px] -= take
            if bot_pool[px] == 0:
                del bot_pool[px]
            qty -= take

        # Then strat (our resting orders)
        if qty <= 0:
            continue
        strat_vol = strat_pool.get(px, 0)
        if strat_vol > 0:
            # Cap by position limit
            if taker.side == "BUY":
                # Taker buys ⇒ our ask fills ⇒ we sell
                cap = limit + position
            else:
                cap = limit - position
            take = min(qty, strat_vol, max(0, cap))
            if take > 0:
                strat_pool[px] -= take
                if strat_pool[px] == 0:
                    del strat_pool[px]
                if taker.side == "BUY":
                    position -= take
                    cash += px * take
                    fills.append(Fill(ts=ts, product="", side="SELL",
                                      price=px, qty=take, source="taker"))
                else:
                    position += take
                    cash -= px * take
                    fills.append(Fill(ts=ts, product="", side="BUY",
                                      price=px, qty=take, source="taker"))
                qty -= take

    return fills, position, cash


def _build_order_depth(book_buys, book_sells):
    od = OrderDepth()
    od.buy_orders = dict(book_buys)
    od.sell_orders = {p: -q for p, q in book_sells.items()}
    return od


def run_session(
    trader, product: str, seed: int, n_ticks: int = 1000,
    taker_rate: float = None, qty_range: tuple = None, fv0: float = None,
) -> SessionResult:
    if product == "ASH_COATED_OSMIUM":
        kwargs = {"seed": seed, "n_ticks": n_ticks}
        if taker_rate is not None: kwargs["taker_rate"] = taker_rate
        if qty_range is not None: kwargs["qty_range"] = qty_range
        if fv0 is not None: kwargs["fv0"] = fv0
        ticks = gen_osmium_session(**kwargs)
    elif product == "INTARIAN_PEPPER_ROOT":
        kwargs = {"seed": seed, "n_ticks": n_ticks}
        if taker_rate is not None: kwargs["taker_rate"] = taker_rate
        if qty_range is not None: kwargs["qty_range"] = qty_range
        if fv0 is not None: kwargs["fv0"] = fv0
        ticks = gen_pepper_session(**kwargs)
    else:
        raise ValueError(f"unknown product {product}")

    result = SessionResult(product=product, seed=seed)
    position = 0
    cash = 0.0
    trader_data = ""

    # Suppress Trader's logger.flush stdout noise
    sink = io.StringIO()

    for snap in ticks:
        # (1) fresh bot book this tick
        book_buys = dict(snap.buy_orders)
        book_sells = {p: -q for p, q in snap.sell_orders.items()}
        strat_buys: dict = {}
        strat_sells: dict = {}

        # (2) Trader computes orders given the bot-only book
        od = _build_order_depth(book_buys, book_sells)
        state = TradingState(
            timestamp=snap.ts,
            order_depths={product: od},
            position={product: position},
            market_trades={product: []},
            own_trades={product: []},
            trader_data=trader_data,
        )
        with redirect_stdout(sink):
            result_dict, _conv, trader_data = trader.run(state)
        orders = result_dict.get(product, []) or []

        # (3) cross/rest trader orders
        cross_fills, position, cash_delta = _cross_trader_orders(
            orders, book_buys, book_sells, strat_buys, strat_sells,
            position, limit=80, ts=snap.ts,
        )
        cash += cash_delta
        for f in cross_fills:
            f.product = product
            result.fills.append(f)

        # (4) takers arrive; owner priority (bot first, then strat)
        for ev in snap.takers:
            t_fills, position, cash_delta = _apply_taker(
                ev, book_buys, book_sells, strat_buys, strat_sells,
                position, limit=80, ts=snap.ts,
            )
            cash += cash_delta
            for f in t_fills:
                f.product = product
                result.fills.append(f)

    result.cash = cash
    result.final_pos = position
    result.final_fv = ticks[-1].fv_true
    return result


def _load_trader_from_path(path: str):
    import importlib.util
    import sys as _sys
    import types

    fake_dm = types.ModuleType("datamodel")
    fake_dm.Order = Order
    fake_dm.OrderDepth = OrderDepth
    fake_dm.TradingState = TradingState
    fake_dm.Trade = Trade
    fake_dm.Symbol = str
    _sys.modules["datamodel"] = fake_dm

    spec = importlib.util.spec_from_file_location("submission_mod", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.Trader()


def summarize(results: list[SessionResult], name: str = ""):
    pnls = [r.pnl for r in results]
    n_fills = [len(r.fills) for r in results]
    buy_qty = sum(f.qty for r in results for f in r.fills if f.side == "BUY")
    sell_qty = sum(f.qty for r in results for f in r.fills if f.side == "SELL")
    print(f"== {name} ({len(results)} sessions) ==")
    if pnls:
        print(f"  PnL: mean={statistics.mean(pnls):.0f}  "
              f"stdev={statistics.stdev(pnls) if len(pnls)>1 else 0:.0f}  "
              f"min={min(pnls):.0f}  max={max(pnls):.0f}")
    print(f"  fills/session: mean={statistics.mean(n_fills):.1f}  "
          f"total_buy={buy_qty} total_sell={sell_qty} "
          f"per-session buy_qty={buy_qty/len(results):.1f} sell_qty={sell_qty/len(results):.1f}")


if __name__ == "__main__":
    path = ("/Users/svelaga/Documents/IMC Prosperity/ROUND_1/"
            "submissions/v15_wall_aware/v15_wall_aware.py")
    trader = _load_trader_from_path(path)
    osm = [run_session(trader, "ASH_COATED_OSMIUM", seed=s) for s in range(20)]
    trader = _load_trader_from_path(path)
    pep = [run_session(trader, "INTARIAN_PEPPER_ROOT", seed=s) for s in range(20)]
    summarize(osm, "OSMIUM v15 (default params)")
    summarize(pep, "PEPPER v15 (default params)")
