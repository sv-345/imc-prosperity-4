"""Iter 5 — passive-only quoting at inner-inside offsets.

Drop the take_mispricing path entirely. It was harmful on PEP because the
"mispriced" crossing bot-3 levels are transient noise (they vanish the next
tick), not genuine fair-relative alpha. Selling into them ramps short
position to the limit within a few hundred ticks, then PEP's +0.1/tick drift
marks the -80 position down by ~1000 ticks over a day → ~-80k MTM loss.

With the take path removed the strategy is pure market-making: place
passive quotes at one tick inside the measured inner offsets, let taker
flow fill us organically.

Parameters (unchanged from iter 4):
  OSM_QUOTE_OFFSET = 7      # inner(8) − 1
  PEP_QUOTE_OFFSET_BID = 5  # PEP bid inner(6) − 1
  PEP_QUOTE_OFFSET_ASK = 6  # PEP ask inner(7) − 1

All offsets traced to docs/round2_model.md §2 and docs/round2_params.json.
"""

from typing import Dict, List

from prosperity3bt.datamodel import Order, OrderDepth, TradingState


POSITION_LIMIT = 80
TAKER_QTY_MAX = 10
QUOTE_SIZE_CAP = 25

OSM_FAIR = 10001
OSM_QUOTE_OFFSET = 7
PEP_QUOTE_OFFSET_BID = 5
PEP_QUOTE_OFFSET_ASK = 6


def deepest_mid(depth: OrderDepth) -> float:
    if not depth.buy_orders or not depth.sell_orders:
        return 0.0
    return 0.5 * (min(depth.buy_orders) + max(depth.sell_orders))


def quote_passive(
    product: str,
    fair: float,
    depth: OrderDepth,
    position: int,
    bid_off: int,
    ask_off: int,
) -> List[Order]:
    orders: List[Order] = []
    if not depth.buy_orders or not depth.sell_orders:
        return orders

    target_bid = int(fair) - bid_off
    target_ask = int(fair) + ask_off

    # Don't cross the book — step back one tick if the opposite side sits
    # inside our target.
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
                result[product] = quote_passive(
                    product, float(OSM_FAIR), depth, position,
                    bid_off=OSM_QUOTE_OFFSET, ask_off=OSM_QUOTE_OFFSET,
                )
            elif product == "INTARIAN_PEPPER_ROOT":
                fair = deepest_mid(depth)
                if fair == 0.0:
                    result[product] = []
                    continue
                result[product] = quote_passive(
                    product, fair, depth, position,
                    bid_off=PEP_QUOTE_OFFSET_BID, ask_off=PEP_QUOTE_OFFSET_ASK,
                )
            else:
                result[product] = []
        return result, 0, ""
