"""Training-data replay: run strategy against real R1 training CSVs
(prices + trades) so insider-detection signals can actually fire.

Extended with a taker-flow simulator — strategy's RESTING quotes (not
just aggressive crosses) get hit by calibrated MC takers. Without this,
penny-jump and edge quotes never fill and variant comparison is blind.

Trade stream includes the real qty=8 insider trades from training CSV;
they are passed to strategy via state.market_trades.
"""
from __future__ import annotations
import csv
import random
import statistics
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List

# Calibrated taker params per product (from mc_r1_v1)
TAKER_PARAMS = {
    "ASH_COATED_OSMIUM":     {"rate": 0.042, "qty": (2, 10), "buy_frac": 0.50},
    "INTARIAN_PEPPER_ROOT":  {"rate": 0.033, "qty": (3, 8),  "buy_frac": 0.50},
}

sys.path.insert(0, str(Path(__file__).parent))

DATA_DIR = Path(__file__).parent.parent / "data" / "ROUND1"


@dataclass
class Order:
    symbol: str
    price: int
    quantity: int  # positive = buy, negative = sell


@dataclass
class OrderDepth:
    buy_orders: Dict[int, int] = field(default_factory=dict)
    sell_orders: Dict[int, int] = field(default_factory=dict)


@dataclass
class Trade:
    symbol: str
    price: int
    quantity: int
    buyer: str = ""
    seller: str = ""
    timestamp: int = 0


@dataclass
class TradingState:
    timestamp: int = 0
    order_depths: Dict[str, OrderDepth] = field(default_factory=dict)
    position: Dict[str, int] = field(default_factory=dict)
    own_trades: Dict[str, list] = field(default_factory=dict)
    market_trades: Dict[str, list] = field(default_factory=dict)
    observations: Dict = field(default_factory=dict)
    listings: Dict = field(default_factory=dict)
    traderData: str = ""


def load_day(day: int):
    """Returns (ticks_by_ts, trades_by_ts) where each tick has per-product books."""
    ticks: Dict[int, Dict[str, OrderDepth]] = {}
    with open(DATA_DIR / f"prices_round_1_day_{day}.csv") as f:
        for row in csv.DictReader(f, delimiter=";"):
            ts = int(row["timestamp"])
            product = row["product"]
            od = OrderDepth()
            for i in (1, 2, 3):
                bp, bv = row.get(f"bid_price_{i}", ""), row.get(f"bid_volume_{i}", "")
                ap, av = row.get(f"ask_price_{i}", ""), row.get(f"ask_volume_{i}", "")
                if bp:
                    od.buy_orders[int(bp)] = int(bv)
                if ap:
                    od.sell_orders[int(ap)] = -int(av)  # sell_orders convention: negative qty
            ticks.setdefault(ts, {})[product] = od

    trades: Dict[int, Dict[str, List[Trade]]] = {}
    with open(DATA_DIR / f"trades_round_1_day_{day}.csv") as f:
        for row in csv.DictReader(f, delimiter=";"):
            ts = int(row["timestamp"])
            product = row["symbol"]
            qty = int(row["quantity"])
            price = int(float(row["price"]))
            # Attribute insider trades synthetically for detector compatibility:
            # qty=8 on PEPPER is the known insider signal.
            buyer = "OLIVIA" if (product == "INTARIAN_PEPPER_ROOT" and qty == 8) else "OTHER"
            seller = "OTHER"
            # Classify buyer vs seller by comparing to mid at that tick
            t = Trade(symbol=product, price=price, quantity=qty,
                      buyer=buyer, seller=seller, timestamp=ts)
            trades.setdefault(ts, {}).setdefault(product, []).append(t)

    return ticks, trades


def run_replay(day: int, trader, product_filter=None, position_limit: int = 80,
               verbose: bool = False, max_ticks: int = None, seed: int = 0,
               band_width: int = 5):
    """Run a Trader instance through day's ticks. Returns {product: pnl}.

    Strategy orders fill via TWO mechanisms:
      1. Aggressive match against current book (taking existing liquidity)
      2. Resting quotes get hit by simulated taker flow (calibrated rate/qty
         from mc_r1_v1), with prices clipped to ±band_width of recorded L1.
    """
    ticks, trades = load_day(day)
    ts_sorted = sorted(ticks.keys())
    if max_ticks is not None:
        ts_sorted = ts_sorted[:max_ticks]

    rng = random.Random(seed)
    positions: Dict[str, int] = defaultdict(int)
    cash: Dict[str, float] = defaultdict(float)
    last_mid: Dict[str, float] = {}

    # Strategy resting quotes: {product: {"BID": {price: qty}, "ASK": {price: qty}}}
    # Reset each tick to match live semantics (quotes are IOC-per-tick).
    trader_data = ""

    for ts in ts_sorted:
        od_by_product = ticks[ts]
        mt_by_product = trades.get(ts, {})

        for p, od in od_by_product.items():
            if od.buy_orders and od.sell_orders:
                bb = max(od.buy_orders)
                ba = min(od.sell_orders)
                last_mid[p] = (bb + ba) / 2.0

        if product_filter:
            od_by_product = {k: v for k, v in od_by_product.items() if k in product_filter}

        state = TradingState(
            timestamp=ts,
            order_depths=od_by_product,
            position=dict(positions),
            market_trades=mt_by_product,
            traderData=trader_data,
        )

        result, conversions, trader_data = trader.run(state)
        if trader_data is None:
            trader_data = ""

        # Track strategy resting quotes per product after aggressive matching
        resting: Dict[str, Dict[str, Dict[int, int]]] = {}

        for product, orders in result.items():
            if product not in od_by_product:
                continue
            od = od_by_product[product]
            resting[product] = {"BID": {}, "ASK": {}}
            for order in orders:
                if order.quantity > 0:  # BUY
                    qty_rem = order.quantity
                    max_buy = position_limit - positions[product]
                    qty_rem = min(qty_rem, max_buy)
                    for ap in sorted(od.sell_orders):
                        if ap > order.price or qty_rem <= 0:
                            break
                        avail = -od.sell_orders[ap]
                        if avail <= 0:
                            continue
                        take = min(qty_rem, avail)
                        od.sell_orders[ap] = -(avail - take)
                        if od.sell_orders[ap] == 0:
                            del od.sell_orders[ap]
                        qty_rem -= take
                        positions[product] += take
                        cash[product] -= ap * take
                    # Rest remainder
                    if qty_rem > 0:
                        resting[product]["BID"][order.price] = \
                            resting[product]["BID"].get(order.price, 0) + qty_rem
                else:  # SELL
                    qty_rem = -order.quantity
                    max_sell = position_limit + positions[product]
                    qty_rem = min(qty_rem, max_sell)
                    for bp in sorted(od.buy_orders, reverse=True):
                        if bp < order.price or qty_rem <= 0:
                            break
                        avail = od.buy_orders[bp]
                        if avail <= 0:
                            continue
                        take = min(qty_rem, avail)
                        od.buy_orders[bp] = avail - take
                        if od.buy_orders[bp] == 0:
                            del od.buy_orders[bp]
                        qty_rem -= take
                        positions[product] -= take
                        cash[product] += bp * take
                    if qty_rem > 0:
                        resting[product]["ASK"][order.price] = \
                            resting[product]["ASK"].get(order.price, 0) + qty_rem

        # Simulate taker flow hitting strategy's resting quotes
        # (takers follow owner-priority: bot volume at a given price fills
        # before strategy volume. We approximate by only giving strategy
        # the L1 flow when strategy's price is strictly better than book L1.)
        for product, od in od_by_product.items():
            if product not in TAKER_PARAMS:
                continue
            tp = TAKER_PARAMS[product]
            if rng.random() >= tp["rate"]:
                continue
            is_buy = rng.random() < tp["buy_frac"]
            qty = rng.randint(*tp["qty"])
            # Recorded L1 band (for price-band clipping, prevents exploiting
            # absurd fallback quotes when book is one-sided)
            rec_bb = max(od.buy_orders) if od.buy_orders else None
            rec_ba = min(od.sell_orders) if od.sell_orders else None
            low = (rec_bb if rec_bb is not None else int(last_mid.get(product, 0)) - 1) - band_width
            high = (rec_ba if rec_ba is not None else int(last_mid.get(product, 0)) + 1) + band_width

            strat_quotes = resting.get(product, {})
            if is_buy:
                # Taker is buying → hits asks. L1 = lowest ask across (book, strat).
                book_l1 = rec_ba
                strat_l1 = min(strat_quotes.get("ASK", {}).keys(), default=None)
                cands = [p for p in (book_l1, strat_l1) if p is not None and p <= high]
                if not cands:
                    continue
                l1 = min(cands)
                # Bot (book) has priority at same price
                bot_vol = -od.sell_orders.get(l1, 0) if l1 in od.sell_orders else 0
                strat_vol = strat_quotes.get("ASK", {}).get(l1, 0)
                bot_take = min(qty, bot_vol)
                qty -= bot_take
                if qty > 0 and strat_vol > 0:
                    st = min(qty, strat_vol)
                    qty -= st
                    positions[product] -= st
                    cash[product] += l1 * st
                # Sweep walks if qty remaining — skip deeper levels (small effect)
            else:
                # Taker selling → hits bids
                book_l1 = rec_bb
                strat_l1 = max(strat_quotes.get("BID", {}).keys(), default=None)
                cands = [p for p in (book_l1, strat_l1) if p is not None and p >= low]
                if not cands:
                    continue
                l1 = max(cands)
                bot_vol = od.buy_orders.get(l1, 0)
                strat_vol = strat_quotes.get("BID", {}).get(l1, 0)
                bot_take = min(qty, bot_vol)
                qty -= bot_take
                if qty > 0 and strat_vol > 0:
                    st = min(qty, strat_vol)
                    qty -= st
                    positions[product] += st
                    cash[product] -= l1 * st

    # Final MTM
    result_pnl = {}
    for p in positions:
        mid = last_mid.get(p, 0)
        result_pnl[p] = cash[p] + positions[p] * mid
    return result_pnl


def silence_stdout():
    """Silence the Logger-spam print() in submission files."""
    import io, builtins
    builtins.print = lambda *a, **kw: None


if __name__ == "__main__":
    import builtins
    real_print = builtins.print
    silence_stdout()

    import importlib.util
    spec = importlib.util.spec_from_file_location("sub127989",
        Path(__file__).parent.parent / "submissions" / "127989" / "127989.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    for day in (-2, -1, 0):
        for max_ticks in (1000, None):
            trader = mod.Trader()
            pnl = run_replay(day, trader, max_ticks=max_ticks)
            builtins.print = real_print
            mt_tag = f"first{max_ticks}" if max_ticks else "full"
            real_print(f"\nDay {day} ({mt_tag}) replay of 127989:")
            for k, v in sorted(pnl.items()):
                real_print(f"  {k:30s}: {v:+8.2f}")
            real_print(f"  {'TOTAL':30s}: {sum(pnl.values()):+8.2f}")
            silence_stdout()
