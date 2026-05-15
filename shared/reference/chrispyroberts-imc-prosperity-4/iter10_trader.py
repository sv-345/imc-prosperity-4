"""Iter 10 — adaptive OSM fair via deepest_mid (not constant 10001).

Iter 9 server log (submission 295237) revealed that OSM mid is NOT constant.
Per-segment averages within the 1000-tick slice:
  seg 1  (ts     0..  9900): 10008.37
  seg 3  (ts 20000.. 29900): 10001.75
  seg 7  (ts 60000.. 69900): 10006.20
  seg 10 (ts 90000.. 99900): 10001.73

A ±3–8 tick drift that my hardcoded OSM_FAIR=10001 was completely blind to.
During the elevated segments (~400 ticks), my quotes at 9994 / 10008 sat
below the real market (real bids were ~10000, real asks ~10016), so I didn't
win best-of-book and my fill rate collapsed. The take-threshold was also
anchored to the wrong fair, so some "take above 10002" events were actually
sells AT real fair (zero edge, churn loss).

Change: compute OSM fair as deepest_mid(depth) — (min_bid + max_ask) / 2
using the walls. OSM walls are symmetric at ±10 (per docs/round2_model.md),
so deepest_mid ≈ real_fair within 0.5 ticks. PEP already uses this
estimator; mirror it for OSM.

Parameters unchanged vs iter 9:
  OSM_INNER_OFFSET=8, OSM_EDGE=1, OSM_SKEW_SCALE=40, OSM_TAKE_THRESHOLD=1
  PEP_SWEEP_OFFSET=8, PEP_LONG_TARGET=80, PEP_ASK_AT_WALL=10

The only structural change is dropping the OSM_FAIR constant; the strategy
shape is identical.
"""

from typing import Dict, List

from datamodel import Order, OrderDepth, TradingState


POSITION_LIMIT = 80
QUOTE_SIZE_CAP = 25
TAKER_QTY_MAX = 10

OSM_INNER_OFFSET = 8
OSM_EDGE = 1
OSM_SKEW_SCALE = 40
OSM_TAKE_THRESHOLD = 1

PEP_SWEEP_OFFSET = 8
PEP_LONG_TARGET = 80
PEP_ASK_AT_WALL = 10


def deepest_mid(depth: OrderDepth) -> float:
    if not depth.buy_orders or not depth.sell_orders:
        return 0.0
    return 0.5 * (min(depth.buy_orders) + max(depth.sell_orders))


def quote_osm(
    fair: float,
    depth: OrderDepth,
    position: int,
) -> List[Order]:
    orders: List[Order] = []
    if not depth.buy_orders or not depth.sell_orders:
        return orders

    # Take any bot ask below fair - threshold (buy cheap).
    for ask_price, ask_vol in sorted(depth.sell_orders.items()):
        if ask_price >= fair - OSM_TAKE_THRESHOLD:
            break
        qty = min(-ask_vol, POSITION_LIMIT - position)
        if qty > 0:
            orders.append(Order("ASH_COATED_OSMIUM", ask_price, qty))
            position += qty

    # Take any bot bid above fair + threshold (sell high).
    for bid_price, bid_vol in sorted(depth.buy_orders.items(), reverse=True):
        if bid_price <= fair + OSM_TAKE_THRESHOLD:
            break
        qty = min(bid_vol, position + POSITION_LIMIT)
        if qty > 0:
            orders.append(Order("ASH_COATED_OSMIUM", bid_price, -qty))
            position -= qty

    # Then balanced MM quotes anchored on the adaptive fair.
    shift = position // OSM_SKEW_SCALE
    fair_i = int(fair)
    target_bid = fair_i - (OSM_INNER_OFFSET - OSM_EDGE) - shift
    target_ask = fair_i + (OSM_INNER_OFFSET - OSM_EDGE) - shift

    best_ask = min(depth.sell_orders)
    best_bid = max(depth.buy_orders)
    if target_bid >= best_ask:
        target_bid = best_ask - 1
    if target_ask <= best_bid:
        target_ask = best_bid + 1
    if target_bid >= target_ask:
        return orders

    bid_qty = min(QUOTE_SIZE_CAP, max(0, POSITION_LIMIT - position - TAKER_QTY_MAX))
    ask_qty = min(QUOTE_SIZE_CAP, max(0, POSITION_LIMIT + position - TAKER_QTY_MAX))
    if bid_qty > 0:
        orders.append(Order("ASH_COATED_OSMIUM", target_bid, bid_qty))
    if ask_qty > 0:
        orders.append(Order("ASH_COATED_OSMIUM", target_ask, -ask_qty))
    return orders


def quote_pep_sweep(
    fair: float,
    depth: OrderDepth,
    position: int,
) -> List[Order]:
    orders: List[Order] = []
    if not depth.buy_orders or not depth.sell_orders:
        return orders

    fair_i = int(fair)
    target_bid = fair_i + PEP_SWEEP_OFFSET
    target_ask = fair_i + PEP_ASK_AT_WALL

    if target_bid >= target_ask:
        target_bid = target_ask - 1
        if target_bid <= fair_i:
            return orders

    if position < PEP_LONG_TARGET:
        bid_qty = min(QUOTE_SIZE_CAP, PEP_LONG_TARGET - position)
    else:
        bid_qty = 0
    if position > 0:
        ask_qty = min(QUOTE_SIZE_CAP, position)
    else:
        ask_qty = 0

    if bid_qty > 0:
        orders.append(Order("INTARIAN_PEPPER_ROOT", target_bid, bid_qty))
    if ask_qty > 0:
        orders.append(Order("INTARIAN_PEPPER_ROOT", target_ask, -ask_qty))
    return orders


class Trader:
    def bid(self) -> int:
        return 15

    def run(self, state: TradingState):
        result: Dict[str, List[Order]] = {}
        for product, depth in state.order_depths.items():
            position = state.position.get(product, 0)
            if product == "ASH_COATED_OSMIUM":
                fair = deepest_mid(depth)
                if fair == 0.0:
                    result[product] = []
                    continue
                result[product] = quote_osm(fair, depth, position)
            elif product == "INTARIAN_PEPPER_ROOT":
                fair = deepest_mid(depth)
                if fair == 0.0:
                    result[product] = []
                    continue
                result[product] = quote_pep_sweep(fair, depth, position)
            else:
                result[product] = []
        return result, 0, ""
