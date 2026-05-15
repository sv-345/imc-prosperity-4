"""Iter 7 — PEP directional long-lean, OSM balanced MM unchanged.

The iter6 strategy earned $0.71/tick on PEP by neutralising inventory with a
tight skew (scale=20). But PEP has a *deterministic* +$0.10/tick fair drift
(docs/round2_params.json -> PEP.fv.drift_per_tick = 0.10, confirmed on all
three calibration days). If we accumulate a long position and hold, each unit
held earns $0.10/tick — so 80 units (position limit) held for a 1000-tick
server slice captures $8 000 from drift alone, independent of spread income.

The change: replace the balanced PEP MM with a one-sided "accumulate long,
hold" strategy. Bid aggressively (at fair-1, above the inner bid at fair-6
so we win the sell-taker queue whenever no crossing bot-3 is present). Ask
only at the wall (fair+10) so we don't voluntarily unwind the long for small
gain. Stop bidding when position crosses PEP_LONG_TARGET so we keep a safety
margin against the position limit.

OSM is unchanged from iter6 — the product has no drift (constant fair=10001)
so balanced MM is the right family; PEP's drift was the missed structural
edge, not OSM.

Parameters (each tied to a measured bot stat or a safety margin):

  OSM_EDGE = 1               # quote 1 tick inside bot inner to win queue
  OSM_SKEW_SCALE = 40        # inventory price-skew, same as iter6
  PEP_BID_INSIDE_FAIR = 1    # aggressive; at fair-1 we beat PEP inner (fair-6)
                             #   whenever no crossing bot-3 is present
  PEP_LONG_TARGET = 70       # stop bidding at pos > 70 (safety margin vs limit 80)
  PEP_ASK_AT_WALL = 10       # match the measured PEP ask wall offset; never
                             #   unwind below that

4 tuned params total across both products (OSM: 2, PEP: 3). Within the
budget of ≤ 3 tuned per product. All traceable.
"""

from typing import Dict, List

from datamodel import Order, OrderDepth, TradingState


POSITION_LIMIT = 80
QUOTE_SIZE_CAP = 25
TAKER_QTY_MAX = 10

# OSM (unchanged from iter6)
OSM_FAIR = 10001                  # docs/round2_params.json -> OSM.fv.fair_value
OSM_INNER_OFFSET = 8              # docs/round2_model.md §OSM
OSM_EDGE = 1
OSM_SKEW_SCALE = 40

# PEP (new: directional long-lean)
PEP_BID_INSIDE_FAIR = 1
PEP_LONG_TARGET = 70
PEP_ASK_AT_WALL = 10              # docs/round2_model.md §PEP (wall ask offset)


def deepest_mid(depth: OrderDepth) -> float:
    if not depth.buy_orders or not depth.sell_orders:
        return 0.0
    return 0.5 * (min(depth.buy_orders) + max(depth.sell_orders))


def quote_osm_balanced(
    fair: float,
    depth: OrderDepth,
    position: int,
) -> List[Order]:
    """Unchanged from iter6: balanced MM at fair ± (inner − edge), with
    integer-tick inventory price-skew."""
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


def quote_pep_long_lean(
    fair: float,
    depth: OrderDepth,
    position: int,
) -> List[Order]:
    """Directional strategy: accumulate long PEP to capture +$0.10/tick drift.
    Bid at fair-1 (above inner at fair-6) to catch sell-takers; ask only at
    wall (fair+10). Stop bidding when position > PEP_LONG_TARGET."""
    orders: List[Order] = []
    if not depth.buy_orders or not depth.sell_orders:
        return orders

    fair_i = int(fair)
    target_bid = fair_i - PEP_BID_INSIDE_FAIR
    target_ask = fair_i + PEP_ASK_AT_WALL

    best_ask = min(depth.sell_orders)
    best_bid = max(depth.buy_orders)
    # Don't cross; step back if opposite side is already inside target.
    if target_bid >= best_ask:
        target_bid = best_ask - 1
    if target_ask <= best_bid:
        target_ask = best_bid + 1
    if target_bid >= target_ask:
        return orders

    # Bid only while we have headroom below PEP_LONG_TARGET.
    if position < PEP_LONG_TARGET:
        bid_qty = min(QUOTE_SIZE_CAP, PEP_LONG_TARGET - position)
    else:
        bid_qty = 0

    # Never short PEP (drift is up). Only sell if long.
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
        # MAF bid — offered low because the R2 rules note the fee is only
        # meaningful if it clears the median and we don't have market data on
        # other entrants' bids.
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
                result[product] = quote_pep_long_lean(fair, depth, position)
            else:
                result[product] = []
        return result, 0, ""
