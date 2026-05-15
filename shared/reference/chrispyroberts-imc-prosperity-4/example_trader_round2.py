"""
Example Round 2 Trader — reasonable (not optimal) market-maker
===============================================================
Round 2 adds two products:

  * ASH_COATED_OSMIUM (OSM)     — stationary around fair = 10001.
  * INTARIAN_PEPPER_ROOT (PEP)  — linear drift +0.10/tick, day-start
                                  exactly 11000/12000/13000 on days -1/0/1.

This trader quotes one tick inside the nearest bot-2 (inner) level on each
side. Round 1 analysis (ROUND_1/notes/PHASE2_DATA_PROFILE.md §2.6) showed
that ~76% of OSM takes hit the inner level; if you co-quote at the inner
price Bot 2 has owner priority and fills first. Quoting one tick inside
makes the strategy the best bid/ask and gives it first pick on inner-level
takers.

It is deliberately simple and will not beat a tuned strategy — use it as a
smoke-test that the R2 data-generation pipeline is wired end-to-end and
that a Round-2-aware Trader.run() is plausible.

Usage (data generation only; strategy runner is Round-0 for now):

    rust_simulator/target/release/rust_simulator \\
        --round 2 --fv-mode simulate --trade-mode simulate \\
        --output tmp/round2_gen

Then load the CSVs in tmp/round2_gen/round2/ with your preferred MC loop
(the Round-1 tools under ROUND_1/mc/ already accept this schema).
"""

from typing import Dict, List

from prosperity3bt.datamodel import Order, OrderDepth, TradingState


POSITION_LIMIT = 80

# Deterministic fair values per docs/round2_params.json.
# OSM is stationary. PEP drifts linearly; recompute per tick.
OSM_FAIR = 10001
PEP_DAY_STARTS = {-1: 11000.0, 0: 12000.0, 1: 13000.0}
PEP_DRIFT_PER_TICK = 0.10


def pep_fair(timestamp: int) -> float:
    # The MC pipeline reruns each day in a fresh session, so the timestamp
    # resets to 0 at the start of a day. We pick day 0 starting fair (12000)
    # as the most representative default; override via trader_data if you
    # want per-day calibration.
    day_start = PEP_DAY_STARTS[0]
    tick = timestamp // 100
    return day_start + PEP_DRIFT_PER_TICK * tick


def market_make(
    product: str,
    fair: float,
    depth: OrderDepth,
    position: int,
) -> List[Order]:
    orders: List[Order] = []

    # Take obvious mispricings.
    for ask, ask_vol in sorted(depth.sell_orders.items()):
        if ask < fair - 1 and position < POSITION_LIMIT:
            qty = min(-ask_vol, POSITION_LIMIT - position)
            if qty > 0:
                orders.append(Order(product, ask, qty))
                position += qty

    for bid, bid_vol in sorted(depth.buy_orders.items(), reverse=True):
        if bid > fair + 1 and position > -POSITION_LIMIT:
            qty = min(bid_vol, position + POSITION_LIMIT)
            if qty > 0:
                orders.append(Order(product, bid, -qty))
                position -= qty

    # Quote one tick inside the best visible bid/ask (inside bot-2).
    if depth.buy_orders and depth.sell_orders:
        best_bid = max(depth.buy_orders)
        best_ask = min(depth.sell_orders)
        our_bid = best_bid + 1
        our_ask = best_ask - 1
        # Only quote if we wouldn't cross our own book and we'd still be on
        # the correct side of fair.
        if our_bid < our_ask and our_bid <= fair <= our_ask:
            bid_qty = max(0, POSITION_LIMIT - position - 5)
            ask_qty = max(0, POSITION_LIMIT + position - 5)
            if bid_qty > 0:
                orders.append(Order(product, int(our_bid), min(bid_qty, 20)))
            if ask_qty > 0:
                orders.append(Order(product, int(our_ask), -min(ask_qty, 20)))

    return orders


class Trader:
    def run(self, state: TradingState):
        result: Dict[str, List[Order]] = {}

        for product, depth in state.order_depths.items():
            position = state.position.get(product, 0)
            if product == "ASH_COATED_OSMIUM":
                fair = float(OSM_FAIR)
            elif product == "INTARIAN_PEPPER_ROOT":
                fair = pep_fair(state.timestamp)
            else:
                # Skip unknown products rather than crash.
                result[product] = []
                continue
            result[product] = market_make(product, fair, depth, position)

        conversions = 0
        trader_data = ""
        return result, conversions, trader_data
