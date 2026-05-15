"""Iter 6 — passive MM with inventory price-skew.

Iter 5 removed the ill-advised take_mispricing path but PEP still suffered
from inventory MTM-risk on its +0.1/tick drift: position drifts to one side,
we get marked on the wrong side of fair as the day progresses.

This iteration adds a single inventory-price-skew term: shift both bid and
ask price down by `position / SKEW_SCALE` ticks. When long, both quotes
step down → we offer a more aggressive sell (lower ask) and a less aggressive
buy (lower bid), which rebalances inventory toward zero. Symmetric behavior
when short.

Tuned parameters per product:
  EDGE                  (1 each)   how many ticks inside the bot inner we quote
  SKEW_SCALE            (1 each)   units of position per 1-tick price shift

Calibration-derived constants (not tuned):
  OSM_FAIR = 10001                 docs/round2_params.json -> OSM.fv.fair_value
  OSM_INNER = 8                    docs/round2_model.md §OSM
  PEP_INNER_BID = 6                docs/round2_model.md §PEP
  PEP_INNER_ASK = 7                docs/round2_model.md §PEP
"""

from typing import Dict, List

from prosperity3bt.datamodel import Order, OrderDepth, TradingState


POSITION_LIMIT = 80
TAKER_QTY_MAX = 10
QUOTE_SIZE_CAP = 25

OSM_FAIR = 10001
OSM_INNER = 8
PEP_INNER_BID = 6
PEP_INNER_ASK = 7

# Tuned per-product (≤ 3 total as required by the overfit gates).
OSM_EDGE = 1
PEP_EDGE = 1
OSM_SKEW_SCALE = 40   # pos of 40 → 1 tick shift. OSM fair static → mild skew fine.
PEP_SKEW_SCALE = 20   # pos of 20 → 1 tick shift. Heavier because PEP drift punishes inventory.


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

    # Integer tick-level skew based on inventory.
    shift = position // skew_scale  # long → positive shift → quotes step DOWN

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
