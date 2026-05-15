"""Iter 2 — bot-aware inside-the-inner market-maker.

One tuned parameter per product:
  OSM_EDGE = 1   # how many ticks inside the bot's best price we quote.
                 # Chosen because the bot inner is at ±8 from fair=10001 and
                 # takers route 60% of volume to the inner (docs/round2_model.md
                 # -> OSM.taker.level_split). Quoting one tick inside makes
                 # us best-of-book and wins the queue on inner-level takers.
  PEP_EDGE = 1   # Same logic. PEP inner is asymmetric at -6/+7 from fair but
                 # quoting one tick inside the observed best still places us
                 # top-of-book regardless of which side.

Fair-value sourcing:
  OSM: constant 10001 (docs/round2_params.json -> OSM.fv.fair_value).
  PEP: uses the visible book mid each tick rather than the day-start +
       drift model. This avoids needing to infer which day we are on
       — the mid of the inner (-6/+7 bands) is centered on fair within
       ~0.5 ticks, which is the same accuracy as the drift model but
       needs zero state and zero hardcoded day-start constants.

Every numeric constant here traces back to a measured bot stat or a
derived position-safety heuristic. Nothing is fit to PnL.
"""

from typing import Dict, List

from prosperity3bt.datamodel import Order, OrderDepth, TradingState


POSITION_LIMIT = 80

OSM_FAIR = 10001  # docs/round2_params.json -> OSM.fv.fair_value
OSM_EDGE = 1      # tuned: one tick inside bot inner to win inner-level queue
PEP_EDGE = 1      # same logic as OSM

# Size reserves: leave some room under position limit so a large taker
# doesn't push us over. Not tuned — set equal to the max single-taker qty
# (OSM: 10, PEP: 8; use 10 as a shared safety margin).
TAKER_QTY_MAX = 10


def quote_one_tick_inside(
    product: str,
    fair: float,
    depth: OrderDepth,
    position: int,
    edge: int,
) -> List[Order]:
    """Place passive bid/ask one tick inside the best visible level.

    Takes obvious mispricings first (ask < fair or bid > fair by > 1 tick),
    then places a passive bid/ask one tick inside the current best.
    """
    orders: List[Order] = []

    # Take clearly mispriced offers/bids. Threshold is "more than 1 tick wrong"
    # to avoid round-trip churn on 1-tick noise.
    if depth.sell_orders:
        for ask, ask_vol in sorted(depth.sell_orders.items()):
            if ask < fair - 1 and position < POSITION_LIMIT:
                qty = min(-ask_vol, POSITION_LIMIT - position)
                if qty > 0:
                    orders.append(Order(product, ask, qty))
                    position += qty
            else:
                break
    if depth.buy_orders:
        for bid, bid_vol in sorted(depth.buy_orders.items(), reverse=True):
            if bid > fair + 1 and position > -POSITION_LIMIT:
                qty = min(bid_vol, position + POSITION_LIMIT)
                if qty > 0:
                    orders.append(Order(product, bid, -qty))
                    position -= qty
            else:
                break

    # Place passive quote one tick inside the current best.
    if not depth.buy_orders or not depth.sell_orders:
        return orders

    best_bid = max(depth.buy_orders)
    best_ask = min(depth.sell_orders)
    our_bid = best_bid + edge
    our_ask = best_ask - edge

    # Don't cross our own quotes or the opposite side of the book.
    if our_bid >= our_ask or our_bid >= best_ask or our_ask <= best_bid:
        return orders
    # Keep passive orders on the correct side of fair so we don't pay up.
    if our_bid > fair or our_ask < fair:
        return orders

    bid_qty = max(0, POSITION_LIMIT - position - TAKER_QTY_MAX)
    ask_qty = max(0, POSITION_LIMIT + position - TAKER_QTY_MAX)
    max_quote = 25  # cap per-tick to avoid "infinite liquidity" artifacts
    if bid_qty > 0:
        orders.append(Order(product, int(our_bid), min(bid_qty, max_quote)))
    if ask_qty > 0:
        orders.append(Order(product, int(our_ask), -min(ask_qty, max_quote)))

    return orders


def mid_of_book(depth: OrderDepth) -> float:
    if not depth.buy_orders or not depth.sell_orders:
        return 0.0
    return 0.5 * (max(depth.buy_orders) + min(depth.sell_orders))


def deepest_mid(depth: OrderDepth) -> float:
    """Mid of the widest visible bid and ask levels. For PEP the walls are
    symmetric at ±10 from floor(fair), so when both walls are present this
    returns floor(fair) exactly. Robust against crossing bot-3 noise at the
    top of book (which can be +4/−4 from fair)."""
    if not depth.buy_orders or not depth.sell_orders:
        return 0.0
    return 0.5 * (min(depth.buy_orders) + max(depth.sell_orders))


class Trader:
    def bid(self) -> int:
        # Market Access Fee bid — irrelevant for local MC. See docs/round2_model.md §MAF.
        return 15

    def run(self, state: TradingState):
        result: Dict[str, List[Order]] = {}
        for product, depth in state.order_depths.items():
            position = state.position.get(product, 0)
            if product == "ASH_COATED_OSMIUM":
                fair = float(OSM_FAIR)
                edge = OSM_EDGE
            elif product == "INTARIAN_PEPPER_ROOT":
                # Deepest-mid is robust against crossing bot-3 quotes that
                # contaminate top-of-book mid. See deepest_mid() docstring.
                fair = deepest_mid(depth)
                if fair == 0.0:
                    result[product] = []
                    continue
                edge = PEP_EDGE
            else:
                result[product] = []
                continue
            result[product] = quote_one_tick_inside(product, fair, depth, position, edge)
        return result, 0, ""
