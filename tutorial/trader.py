"""
trader_v14.py — FV rounding fix from v13 log analysis

Changes from v13:
  - TOMATOES FV: (fb+fa)//2 instead of (fb+fa+1)//2
    The +1 created a systematic upward bias (~0.5 tick above true FV),
    which made bids 0.5 tick closer to FV → more buy fills → chronic
    long position (72-95% of ticks positive, avg_pos ~20-45).
    This cost ~540 std and ~1100 worst-case PnL to inventory losses.
  - EMERALDS: unchanged (zero losing trades, near-optimal)
  - Quoting: unchanged (penny-jump + dual-level proven effective)

Results vs v13 (100-session MC, two seeds):
  Mean PnL:   +266  (+1.6%)
  Std:        -540  (-24%)
  Min:        +1136 (+11%)
  Tomato R²:  0.97 mean (was 0.94), 0.65 min (was 0.44)
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional

@dataclass
class Order:
    symbol: str
    price: int
    quantity: int

@dataclass
class OrderDepth:
    buy_orders: Dict[int, int] = field(default_factory=dict)
    sell_orders: Dict[int, int] = field(default_factory=dict)

@dataclass
class TradingState:
    timestamp: int
    order_depths: Dict[str, "OrderDepth"]
    position: Dict[str, int]
    own_trades: Dict = field(default_factory=dict)
    market_trades: Dict = field(default_factory=dict)
    observations: Dict = field(default_factory=dict)
    traderData: str = ""

EMERALDS_FV = 10_000
EMERALDS_LIMIT = 80
TOMATOES_LIMIT = 80

EM_ACC_THRESH = 0
TOM_ACC_THRESH = 0

MIN_INSIDE_QTY = 10


class Trader:
    def __init__(self):
        pass

    @staticmethod
    def _bb(d):
        return max(d.buy_orders) if d.buy_orders else None

    @staticmethod
    def _ba(d):
        return min(d.sell_orders) if d.sell_orders else None

    def _fv_tom(self, d):
        if not d.buy_orders or not d.sell_orders:
            return None
        wb = min(d.buy_orders.keys())
        wa = max(d.sell_orders.keys())
        fb = wb + 8
        fa = wa - 8
        if abs(fb - fa) <= 1:
            return (fb + fa) // 2          # was (fb + fa + 1) // 2 in v13
        return None

    def _smart_sweep(self, product, d, pos, fv, lim, acc_thresh):
        orders = []
        opos = pos

        for ap in sorted(d.sell_orders):
            if ap >= fv:
                break
            f = min(-d.sell_orders[ap], lim - pos)
            if f > 0:
                orders.append(Order(product, ap, f))
                pos += f

        for bp in sorted(d.buy_orders, reverse=True):
            if bp <= fv:
                break
            f = min(d.buy_orders[bp], lim + pos)
            if f > 0:
                orders.append(Order(product, bp, -f))
                pos -= f

        buy_at_fv = (pos < 0) or (pos < acc_thresh)
        sell_at_fv = (pos > 0) or (pos > -acc_thresh)

        if buy_at_fv:
            for ap in sorted(d.sell_orders):
                if ap != fv:
                    continue
                f = min(-d.sell_orders[ap], lim - pos)
                if f > 0:
                    orders.append(Order(product, ap, f))
                    pos += f

        if sell_at_fv:
            for bp in sorted(d.buy_orders, reverse=True):
                if bp != fv:
                    continue
                f = min(d.buy_orders[bp], lim + pos)
                if f > 0:
                    orders.append(Order(product, bp, -f))
                    pos -= f

        return orders, opos, pos

    def _trade_emeralds(self, d, pos):
        fv, lim = EMERALDS_FV, EMERALDS_LIMIT
        orders, opos, pos = self._smart_sweep("EMERALDS", d, pos, fv, lim, EM_ACC_THRESH)

        buy_sweep = max(0, pos - opos)
        sell_sweep = max(0, opos - pos)
        buy_cap = max(0, lim - opos - buy_sweep)
        sell_cap = max(0, lim + opos - sell_sweep)

        if buy_cap > 0:
            orders.append(Order("EMERALDS", fv - 7, buy_cap))
        if sell_cap > 0:
            orders.append(Order("EMERALDS", fv + 7, -sell_cap))

        return orders

    def _trade_tomatoes(self, d, pos):
        lim = TOMATOES_LIMIT
        bb = self._bb(d)
        ba = self._ba(d)
        if bb is None or ba is None:
            return []

        fv = self._fv_tom(d)

        if fv is None:
            orders = []
            bid1 = bb + 1
            ask1 = ba - 1
            if bid1 >= ask1:
                mid = (bb + ba) // 2
                bid1, ask1 = mid, mid + 1
            br = max(0, lim - pos)
            sr = max(0, lim + pos)
            if br > 0:
                orders.append(Order("TOMATOES", bid1, br))
            if sr > 0:
                orders.append(Order("TOMATOES", ask1, -sr))
            return orders

        orders, opos, pos = self._smart_sweep("TOMATOES", d, pos, fv, lim, TOM_ACC_THRESH)

        buy_sweep = max(0, pos - opos)
        sell_sweep = max(0, opos - pos)
        buy_cap = max(0, lim - opos - buy_sweep)
        sell_cap = max(0, lim + opos - sell_sweep)

        # Level 2 prices: penny-jump inside with FV clamping
        bid_L2 = bb + 1
        ask_L2 = ba - 1
        if bid_L2 >= ask_L2:
            bid_L2, ask_L2 = fv - 1, fv + 1
        bid_L2 = min(bid_L2, fv - 1)
        ask_L2 = max(ask_L2, fv + 1)

        # Level 1 prices: at BB/BA with FV clamping
        bid_L1 = min(bb, fv - 1)
        ask_L1 = max(ba, fv + 1)

        # Only use dual-level if L1 and L2 are at different prices
        if bid_L1 == bid_L2:
            if buy_cap > 0:
                orders.append(Order("TOMATOES", bid_L2, buy_cap))
        else:
            buy_L2 = min(MIN_INSIDE_QTY, buy_cap)
            buy_L1 = buy_cap - buy_L2
            if buy_L1 > 0:
                orders.append(Order("TOMATOES", bid_L1, buy_L1))
            if buy_L2 > 0:
                orders.append(Order("TOMATOES", bid_L2, buy_L2))

        if ask_L1 == ask_L2:
            if sell_cap > 0:
                orders.append(Order("TOMATOES", ask_L2, -sell_cap))
        else:
            sell_L2 = min(MIN_INSIDE_QTY, sell_cap)
            sell_L1 = sell_cap - sell_L2
            if sell_L1 > 0:
                orders.append(Order("TOMATOES", ask_L1, -sell_L1))
            if sell_L2 > 0:
                orders.append(Order("TOMATOES", ask_L2, -sell_L2))

        return orders

    def run(self, state):
        r = {}
        if "EMERALDS" in state.order_depths:
            r["EMERALDS"] = self._trade_emeralds(
                state.order_depths["EMERALDS"],
                state.position.get("EMERALDS", 0),
            )
        if "TOMATOES" in state.order_depths:
            r["TOMATOES"] = self._trade_tomatoes(
                state.order_depths["TOMATOES"],
                state.position.get("TOMATOES", 0),
            )
        return r, 0, ""
