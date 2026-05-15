"""Iter 8 — PEP active-sweep accumulation instead of passive waiting.

Iter 7 server result (submission 294616): PEP ended at max position 26 despite
the 70-unit target. Passive bid at fair-1 was outbid by other teams; we
captured only ~17% of the theoretical $8 k drift ceiling.

Fix: replace passive PEP bid with an *active* cross-the-book bid at
floor(fair)+8. That's one tick above the PEP inner ask at fair+7 — so our
order immediately sweeps the bot's inner ask each tick, converting
accumulation from arrival-rate-limited to position-limit-limited. Expected
fill rate: 10 units/tick (the inner ask's typical volume) → reach position
cap in 8 ticks, then hold for ~992 ticks of drift capture.

Math:
  Per unit: bought at avg fair+7, marked at fair_end (fair_end - fair_buy ~ $99)
  80 units: 80 × ($99 - $7) = $7 360 on PEP (vs $1 366 in iter 7)

OSM is unchanged (no drift, balanced MM is the right family).

Parameters:
  OSM_EDGE = 1, OSM_SKEW_SCALE = 40                   (unchanged from iter 6/7)
  PEP_SWEEP_OFFSET = 8   # bid at floor(fair)+8, above PEP inner ask (fair+7)
  PEP_LONG_TARGET = 78   # stop bidding at pos > 78 (2-unit buffer vs limit 80)
  PEP_ASK_AT_WALL = 10   # only sell at wall offset

4 tuned params total (OSM: 2, PEP: 3 — at budget). Every constant traces to a
measured bot stat or the position-limit safety margin.
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

PEP_SWEEP_OFFSET = 8
PEP_LONG_TARGET = 78
PEP_ASK_AT_WALL = 10


def deepest_mid(depth: OrderDepth) -> float:
    if not depth.buy_orders or not depth.sell_orders:
        return 0.0
    return 0.5 * (min(depth.buy_orders) + max(depth.sell_orders))


def quote_osm_balanced(
    fair: float,
    depth: OrderDepth,
    position: int,
) -> List[Order]:
    orders: List[Order] = []
    if not depth.buy_orders or not depth.sell_orders:
        return orders
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
    """Active sweep: bid one tick above the inner ask to cross the book and
    consume bot liquidity directly. Bypasses the sell-taker arrival bottleneck."""
    orders: List[Order] = []
    if not depth.buy_orders or not depth.sell_orders:
        return orders

    fair_i = int(fair)
    target_bid = fair_i + PEP_SWEEP_OFFSET
    target_ask = fair_i + PEP_ASK_AT_WALL

    # Safety: don't place an order above our own ask.
    if target_bid >= target_ask:
        target_bid = target_ask - 1
        if target_bid <= fair_i:
            return orders  # nothing sensible to quote

    # Bid only while under the long target.
    if position < PEP_LONG_TARGET:
        bid_qty = min(QUOTE_SIZE_CAP, PEP_LONG_TARGET - position)
    else:
        bid_qty = 0

    # Never short PEP.
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
                result[product] = quote_osm_balanced(float(OSM_FAIR), depth, position)
            elif product == "INTARIAN_PEPPER_ROOT":
                fair = deepest_mid(depth)
                if fair == 0.0:
                    result[product] = []
                    continue
                result[product] = quote_pep_sweep(fair, depth, position)
            else:
                result[product] = []
        return result, 0, ""
