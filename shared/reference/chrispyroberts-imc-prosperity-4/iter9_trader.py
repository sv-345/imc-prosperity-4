"""Iter 9 — squeeze remaining headroom: PEP target=80, OSM take-crossings.

Iter 8 server: $7 748 total (OSM 613, PEP 7 135). PEP captured 96% of its
theoretical $7 400 max on the 1000-tick slice. Further PEP gains are
marginal (raising the long target 78 → 80 adds ~$200). Further OSM gains
must come from taking mispriced levels, not from tuning the MM spread
(which is already locally optimal at edge=1).

Changes vs iter 8:
  1. PEP_LONG_TARGET: 78 → 80  (capture the last 2 units × $99 drift = +$200)
  2. OSM: add take-crossings — buy any bot ask below fair-1, sell any bot
     bid above fair+1. OSM fair is constant (10001), so each crossing is a
     free $N/unit where N = offset magnitude. Expected +$200–400 over 1000
     ticks. Threshold ±1 (not ±0) to avoid churning on half-tick rounding.

The take logic explicitly SKIPS PEP (PEP-crossings would sell into drift —
the iter 5 failure mode).

Parameters:
  OSM: OSM_EDGE=1, OSM_SKEW_SCALE=40, OSM_TAKE_THRESHOLD=1   (3 — budget)
  PEP: PEP_SWEEP_OFFSET=8, PEP_LONG_TARGET=80, PEP_ASK_AT_WALL=10  (3 — budget)
"""

from typing import Dict, List

from datamodel import Order, OrderDepth, TradingState


POSITION_LIMIT = 80
QUOTE_SIZE_CAP = 25
TAKER_QTY_MAX = 10

OSM_FAIR = 10001
OSM_INNER_OFFSET = 8
OSM_EDGE = 1
OSM_SKEW_SCALE = 40
OSM_TAKE_THRESHOLD = 1  # take any bot level > 1 tick off fair

PEP_SWEEP_OFFSET = 8
PEP_LONG_TARGET = 80
PEP_ASK_AT_WALL = 10


def deepest_mid(depth: OrderDepth) -> float:
    if not depth.buy_orders or not depth.sell_orders:
        return 0.0
    return 0.5 * (min(depth.buy_orders) + max(depth.sell_orders))


def quote_osm_with_take(
    fair: float,
    depth: OrderDepth,
    position: int,
) -> List[Order]:
    """OSM has a constant fair — any bot quote more than 1 tick off is a free
    take. Do take-first, then place MM quotes."""
    orders: List[Order] = []
    if not depth.buy_orders or not depth.sell_orders:
        return orders

    # Take any bot ask below fair - OSM_TAKE_THRESHOLD (buy cheap).
    for ask_price, ask_vol in sorted(depth.sell_orders.items()):
        if ask_price >= fair - OSM_TAKE_THRESHOLD:
            break
        qty = min(-ask_vol, POSITION_LIMIT - position)
        if qty > 0:
            orders.append(Order("ASH_COATED_OSMIUM", ask_price, qty))
            position += qty

    # Take any bot bid above fair + OSM_TAKE_THRESHOLD (sell high).
    for bid_price, bid_vol in sorted(depth.buy_orders.items(), reverse=True):
        if bid_price <= fair + OSM_TAKE_THRESHOLD:
            break
        qty = min(bid_vol, position + POSITION_LIMIT)
        if qty > 0:
            orders.append(Order("ASH_COATED_OSMIUM", bid_price, -qty))
            position -= qty

    # Then place the usual balanced MM quotes.
    shift = position // OSM_SKEW_SCALE
    target_bid = int(fair) - (OSM_INNER_OFFSET - OSM_EDGE) - shift
    target_ask = int(fair) + (OSM_INNER_OFFSET - OSM_EDGE) - shift

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
    """Unchanged from iter 8 except PEP_LONG_TARGET bumped to 80. No
    take-crossings on PEP — PEP drifts up, so selling into crossing bids is
    the iter 5 failure mode."""
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
                result[product] = quote_osm_with_take(float(OSM_FAIR), depth, position)
            elif product == "INTARIAN_PEPPER_ROOT":
                fair = deepest_mid(depth)
                if fair == 0.0:
                    result[product] = []
                    continue
                result[product] = quote_pep_sweep(fair, depth, position)
            else:
                result[product] = []
        return result, 0, ""
