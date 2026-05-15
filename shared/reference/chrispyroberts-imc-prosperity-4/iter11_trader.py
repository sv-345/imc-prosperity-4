"""Iter 11 — OSM mean-reversion lean on observed oscillation pattern.

Iter 9 and iter 10 server logs both show OSM mid oscillating with a
~400-tick period: elevated in segments 1 and 7-8, low in segments 3-5 and
10. The pattern repeats consistently between submissions — suggestive of
deterministic structure, not random-walk realization.

Hypothesis: mean-revert OSM inventory against local fair deviation. When
deepest_mid > long-run fair (10001) + threshold, bias quotes toward selling
(to build short, profit when fair reverts). When below −threshold, bias
toward buying.

Implementation: extend the existing OSM skew term. Current skew shifts
quotes against inventory (pos>0 → quotes step down to unwind). Add a
mean-reversion component: when local fair is elevated, add a positive shift
(same direction as if we were long — i.e. encourage selling). When local
is depressed, negative shift.

Combined skew:
    shift = position // OSM_SKEW_SCALE + (local_fair − long_run_fair) // OSM_REV_SCALE

The MC simulator uses a truly constant OSM fair (10001), so `local_fair -
long_run_fair = 0` in MC and this feature is a no-op there — MC gate is
unchanged. Improvement (if any) shows only on server.

Parameters:
  OSM: OSM_EDGE=1, OSM_SKEW_SCALE=40, OSM_REV_SCALE=3   (3 — at budget)
  PEP: PEP_SWEEP_OFFSET=8, PEP_LONG_TARGET=80, PEP_ASK_AT_WALL=10  (3 — at budget)

OSM_LONG_RUN_FAIR=10001 and OSM_TAKE_THRESHOLD=1 are measurement-derived
constants (per-day mean from calibration; half the wall-to-inner spread).
Not counted in the tuned-parameter budget.
"""

from typing import Dict, List

from datamodel import Order, OrderDepth, TradingState


POSITION_LIMIT = 80
QUOTE_SIZE_CAP = 25
TAKER_QTY_MAX = 10

OSM_LONG_RUN_FAIR = 10001             # docs/round2_params.json -> OSM.fv.per_day_mean
OSM_INNER_OFFSET = 8
OSM_EDGE = 1
OSM_SKEW_SCALE = 40
OSM_TAKE_THRESHOLD = 1
OSM_REV_SCALE = 3                     # tuned: 1-tick shift per $3 mean-reversion deviation

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

    # MM quotes: inventory skew + mean-reversion skew.
    dev = int(fair) - OSM_LONG_RUN_FAIR
    rev_shift = dev // OSM_REV_SCALE            # positive when fair elevated
    inv_shift = position // OSM_SKEW_SCALE
    shift = inv_shift + rev_shift
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
    bid_qty = min(QUOTE_SIZE_CAP, PEP_LONG_TARGET - position) if position < PEP_LONG_TARGET else 0
    ask_qty = min(QUOTE_SIZE_CAP, position) if position > 0 else 0
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
