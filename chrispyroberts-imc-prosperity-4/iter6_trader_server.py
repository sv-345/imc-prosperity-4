"""Server-ready version of iter6_trader.py.

Only difference from iter6_trader.py: the import line uses the bare
`datamodel` module that the IMC server exposes, rather than the local
`prosperity3bt.datamodel` alias used by the chrispyroberts backtester.

Submission 296164 ERROR_FINISHED on the IMC server with
`Runtime.ImportModuleError: No module named 'prosperity3bt'` on every tick.
The trader logic itself is unchanged — same strategy, same parameters, same
behavior. This file is safe to submit.
"""

from typing import Dict, List

from datamodel import Order, OrderDepth, TradingState


POSITION_LIMIT = 80
TAKER_QTY_MAX = 10
QUOTE_SIZE_CAP = 25

OSM_FAIR = 10001
OSM_INNER = 8
PEP_INNER_BID = 6
PEP_INNER_ASK = 7

OSM_EDGE = 1
PEP_EDGE = 1
OSM_SKEW_SCALE = 40
PEP_SKEW_SCALE = 20


def deepest_mid(depth: OrderDepth) -> float:
    if not depth.buy_orders or not depth.sell_orders:
        return 0.0
    return 0.5 * (min(depth.buy_orders) + max(depth.sell_orders))


def quote_with_skew(
    product: str,
    fair: float,
    depth: OrderDepth,
    position: int,
    bid_off: int,
    ask_off: int,
    skew_scale: int,
) -> List[Order]:
    orders: List[Order] = []
    if not depth.buy_orders or not depth.sell_orders:
        return orders

    shift = position // skew_scale

    target_bid = int(fair) - bid_off - shift
    target_ask = int(fair) + ask_off - shift

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
        orders.append(Order(product, target_bid, bid_qty))
    if ask_qty > 0:
        orders.append(Order(product, target_ask, -ask_qty))
    return orders


class Trader:
    def bid(self) -> int:
        return 15

    def run(self, state: TradingState):
        result: Dict[str, List[Order]] = {}
        for product, depth in state.order_depths.items():
            position = state.position.get(product, 0)
            if product == "ASH_COATED_OSMIUM":
                result[product] = quote_with_skew(
                    product, float(OSM_FAIR), depth, position,
                    bid_off=OSM_INNER - OSM_EDGE,
                    ask_off=OSM_INNER - OSM_EDGE,
                    skew_scale=OSM_SKEW_SCALE,
                )
            elif product == "INTARIAN_PEPPER_ROOT":
                fair = deepest_mid(depth)
                if fair == 0.0:
                    result[product] = []
                    continue
                result[product] = quote_with_skew(
                    product, fair, depth, position,
                    bid_off=PEP_INNER_BID - PEP_EDGE,
                    ask_off=PEP_INNER_ASK - PEP_EDGE,
                    skew_scale=PEP_SKEW_SCALE,
                )
            else:
                result[product] = []
        return result, 0, ""
