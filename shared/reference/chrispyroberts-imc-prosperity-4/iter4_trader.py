"""Iter 4 — explicit inner-inside quoting anchored to measured fair.

Earlier attempts used `best_bid + 1` / `best_ask - 1` for placement, which
fails on PEP because 54% of ticks have a *crossing* bot-3 bid at
`floor(fair)+4`. That inflates best_bid above fair and an "inside fair" guard
kills half our bids, leaving a structural sell bias that blows up as PEP
drifts up.

This version anchors our quotes to the *known* inner-level offsets from fair
(docs/round2_model.md):

  OSM: inner at ±8 → we quote one inside at floor(fair)±7.
  PEP: inner at −6/+7 → we quote one inside at floor(fair)−5 / floor(fair)+6.

Parameters per product (one each, both derived from calibration):

  OSM_QUOTE_OFFSET = 7   # inner offset (8) minus edge (1). Edge=1 chosen
                         # because OSM takers hit inner 60% (OSM.taker.level_split)
                         # — first-in-queue at one-tick-inside wins the flow.
  PEP_QUOTE_OFFSET_BID = 5   # PEP bid inner offset (6) − 1.
  PEP_QUOTE_OFFSET_ASK = 6   # PEP ask inner offset (7) − 1.

Fair-value sourcing:
  OSM: constant 10001 (docs/round2_params.json -> OSM.fv.fair_value).
  PEP: deepest_mid (wall-mid, i.e. (min(bids) + max(asks)) / 2). The PEP walls
       are symmetric at ±10 around floor(fair), so when both walls are visible
       this returns floor(fair). When one wall is dropped, the inner stands in
       and deepest_mid returns floor(fair) + 0.5 — accurate enough for quoting.
"""

from typing import Dict, List

from prosperity3bt.datamodel import Order, OrderDepth, TradingState


POSITION_LIMIT = 80
TAKER_QTY_MAX = 10      # bound on a single incoming taker size
QUOTE_SIZE_CAP = 25     # ceiling on per-tick quote size

OSM_FAIR = 10001                # docs/round2_params.json -> OSM.fv.fair_value
OSM_QUOTE_OFFSET = 7            # inner(8) − edge(1)
PEP_QUOTE_OFFSET_BID = 5        # inner_bid(6) − edge(1)
PEP_QUOTE_OFFSET_ASK = 6        # inner_ask(7) − edge(1)


def deepest_mid(depth: OrderDepth) -> float:
    if not depth.buy_orders or not depth.sell_orders:
        return 0.0
    return 0.5 * (min(depth.buy_orders) + max(depth.sell_orders))


def take_mispricing(
    product: str,
    fair: float,
    depth: OrderDepth,
    position: int,
    orders: List[Order],
) -> int:
    """Take clearly mispriced book levels (price off by ≥ 2 ticks from fair).
    Returns the updated position."""
    for ask, ask_vol in sorted(depth.sell_orders.items()):
        if ask < fair - 1 and position < POSITION_LIMIT:
            qty = min(-ask_vol, POSITION_LIMIT - position)
            if qty > 0:
                orders.append(Order(product, ask, qty))
                position += qty
        else:
            break
    for bid, bid_vol in sorted(depth.buy_orders.items(), reverse=True):
        if bid > fair + 1 and position > -POSITION_LIMIT:
            qty = min(bid_vol, position + POSITION_LIMIT)
            if qty > 0:
                orders.append(Order(product, bid, -qty))
                position -= qty
        else:
            break
    return position


def quote_at_offsets(
    product: str,
    fair: float,
    depth: OrderDepth,
    position: int,
    bid_off: int,
    ask_off: int,
) -> List[Order]:
    orders: List[Order] = []
    position = take_mispricing(product, fair, depth, position, orders)

    if not depth.buy_orders or not depth.sell_orders:
        return orders

    target_bid = int(fair) - bid_off
    target_ask = int(fair) + ask_off

    # Safety: don't cross the book — if the opposite side is already inside
    # our target, step back one tick.
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
        # Market-Access-Fee bid. Game-theory only; not simulated locally.
        return 15

    def run(self, state: TradingState):
        result: Dict[str, List[Order]] = {}
        for product, depth in state.order_depths.items():
            position = state.position.get(product, 0)
            if product == "ASH_COATED_OSMIUM":
                fair = float(OSM_FAIR)
                result[product] = quote_at_offsets(
                    product, fair, depth, position,
                    bid_off=OSM_QUOTE_OFFSET, ask_off=OSM_QUOTE_OFFSET,
                )
            elif product == "INTARIAN_PEPPER_ROOT":
                fair = deepest_mid(depth)
                if fair == 0.0:
                    result[product] = []
                    continue
                result[product] = quote_at_offsets(
                    product, fair, depth, position,
                    bid_off=PEP_QUOTE_OFFSET_BID, ask_off=PEP_QUOTE_OFFSET_ASK,
                )
            else:
                result[product] = []
        return result, 0, ""
