from __future__ import annotations

import math
from typing import Any, Dict, List, Tuple

import jsonpickle
from datamodel import Order


POSITION_LIMIT = 10
MAX_ORDER_SIZE = 5

EW_ALPHA = 0.055
PAIR_WEIGHT = 1.25
RETURN_WEIGHT = 0.70
LEVEL_WEIGHT = 0.85
IMBALANCE_WEIGHT = 0.55

BASE_THRESHOLD = 0.90
FAIR_SHIFT_PER_Z = 3.0
MAX_FAIR_SHIFT = 10.0

LATE_TICK = 850_000
VERY_LATE_TICK = 970_000


PRODUCTS = [
    "GALAXY_SOUNDS_PLANETARY_RINGS",
    "GALAXY_SOUNDS_SOLAR_WINDS",
    "GALAXY_SOUNDS_DARK_MATTER",
    "GALAXY_SOUNDS_BLACK_HOLES",
    "GALAXY_SOUNDS_SOLAR_FLAMES",

    "SLEEP_POD_LAMB_WOOL",
    "SLEEP_POD_NYLON",
    "SLEEP_POD_POLYESTER",
    "SLEEP_POD_SUEDE",
    "SLEEP_POD_COTTON",

    "TRANSLATOR_SPACE_GRAY",
    "TRANSLATOR_ECLIPSE_CHARCOAL",
    "TRANSLATOR_ASTRO_BLACK",
    "TRANSLATOR_GRAPHITE_MIST",
    "TRANSLATOR_VOID_BLUE",

    "SNACKPACK_PISTACHIO",
    "SNACKPACK_STRAWBERRY",
    "SNACKPACK_VANILLA",
    "SNACKPACK_CHOCOLATE",
    "SNACKPACK_RASPBERRY",

    "PANEL_2X2",
    "PANEL_2X4",
    "PANEL_4X4",
    "PANEL_1X2",
    "PANEL_1X4",

    "MICROCHIP_RECTANGLE",
    "MICROCHIP_SQUARE",
    "MICROCHIP_OVAL",
    "MICROCHIP_CIRCLE",
    "MICROCHIP_TRIANGLE",

    "UV_VISOR_MAGENTA",
    "UV_VISOR_ORANGE",
    "UV_VISOR_YELLOW",
    "UV_VISOR_AMBER",
    "UV_VISOR_RED",

    "ROBOT_DISHES",
    "ROBOT_MOPPING",
    "ROBOT_LAUNDRY",
    "ROBOT_IRONING",
    "ROBOT_VACUUMING",

    "OXYGEN_SHAKE_MINT",
    "OXYGEN_SHAKE_GARLIC",
    "OXYGEN_SHAKE_MORNING_BREATH",
    "OXYGEN_SHAKE_CHOCOLATE",
    "OXYGEN_SHAKE_EVENING_BREATH",

    "PEBBLES_XL",
    "PEBBLES_S",
    "PEBBLES_XS",
    "PEBBLES_L",
    "PEBBLES_M",
]

PID = {p: str(i) for i, p in enumerate(PRODUCTS)}


HARD_PAIRS = [
    ("MICROCHIP_RECTANGLE", "MICROCHIP_SQUARE"),
    ("MICROCHIP_OVAL", "MICROCHIP_CIRCLE"),
    ("MICROCHIP_TRIANGLE", "MICROCHIP_CIRCLE"),

    ("SNACKPACK_RASPBERRY", "SNACKPACK_VANILLA"),
    ("SNACKPACK_PISTACHIO", "SNACKPACK_STRAWBERRY"),
    ("SNACKPACK_CHOCOLATE", "SNACKPACK_VANILLA"),

    ("GALAXY_SOUNDS_SOLAR_FLAMES", "GALAXY_SOUNDS_SOLAR_WINDS"),
    ("GALAXY_SOUNDS_BLACK_HOLES", "GALAXY_SOUNDS_DARK_MATTER"),

    ("SLEEP_POD_LAMB_WOOL", "SLEEP_POD_NYLON"),
    ("SLEEP_POD_COTTON", "SLEEP_POD_POLYESTER"),

    ("PEBBLES_XL", "PEBBLES_M"),
    ("PEBBLES_M", "PEBBLES_L"),
    ("PEBBLES_S", "PEBBLES_XS"),

    ("PANEL_1X2", "PANEL_1X4"),
    ("PANEL_2X2", "PANEL_2X4"),
    ("PANEL_2X4", "PANEL_4X4"),

    ("TRANSLATOR_SPACE_GRAY", "TRANSLATOR_GRAPHITE_MIST"),
    ("TRANSLATOR_ASTRO_BLACK", "TRANSLATOR_ECLIPSE_CHARCOAL"),

    ("OXYGEN_SHAKE_MINT", "OXYGEN_SHAKE_EVENING_BREATH"),
    ("OXYGEN_SHAKE_GARLIC", "OXYGEN_SHAKE_CHOCOLATE"),

    ("UV_VISOR_RED", "UV_VISOR_AMBER"),
    ("UV_VISOR_ORANGE", "UV_VISOR_YELLOW"),

    ("ROBOT_DISHES", "ROBOT_LAUNDRY"),
    ("ROBOT_MOPPING", "ROBOT_VACUUMING"),
]


FAMILY_PARAMS = {
    "MICROCHIP": (0.85, 4),
    "SNACKPACK": (0.90, 5),
    "PEBBLES": (0.85, 4),
    "GALAXY_SOUNDS": (0.95, 4),
    "SLEEP_POD": (0.95, 4),
    "PANEL": (0.95, 3),
    "OXYGEN_SHAKE": (0.95, 3),
    "UV_VISOR": (0.95, 3),
    "TRANSLATOR": (0.95, 3),
    "ROBOT": (1.00, 3),
}


BAD_PRODUCTS = set()


def _pid(product: str) -> str:
    return PID.get(product, product)


def _family(product: str) -> str:
    if product.startswith("MICROCHIP_"):
        return "MICROCHIP"
    if product.startswith("SNACKPACK_"):
        return "SNACKPACK"
    if product.startswith("GALAXY_SOUNDS_"):
        return "GALAXY_SOUNDS"
    if product.startswith("SLEEP_POD_"):
        return "SLEEP_POD"
    if product.startswith("TRANSLATOR_"):
        return "TRANSLATOR"
    if product.startswith("ROBOT_"):
        return "ROBOT"
    if product.startswith("PANEL_"):
        return "PANEL"
    if product.startswith("OXYGEN_SHAKE_"):
        return "OXYGEN_SHAKE"
    if product.startswith("UV_VISOR_"):
        return "UV_VISOR"
    if product.startswith("PEBBLES_"):
        return "PEBBLES"
    return product.split("_")[0]


def _clip(x: float, lo: float, hi: float) -> float:
    if x < lo:
        return lo
    if x > hi:
        return hi
    return x


def _mean(xs: List[float]) -> float:
    if not xs:
        return 0.0
    return sum(xs) / len(xs)


def _best_bid_ask(depth) -> Tuple[int, int, int, int]:
    if depth.buy_orders:
        bb = max(depth.buy_orders.keys())
        bb_vol = depth.buy_orders[bb]
    else:
        bb, bb_vol = 0, 0

    if depth.sell_orders:
        ba = min(depth.sell_orders.keys())
        ba_vol = abs(depth.sell_orders[ba])
    else:
        ba, ba_vol = 0, 0

    return bb, bb_vol, ba, ba_vol


def _fair_from_l2(depth, bb: int, ba: int) -> float:
    bids = sorted(depth.buy_orders.keys(), reverse=True)
    asks = sorted(depth.sell_orders.keys())

    if len(bids) >= 2 and len(asks) >= 2:
        return (bids[1] + asks[1]) / 2.0

    if bb > 0 and ba > 0:
        return (bb + ba) / 2.0

    return float(bb or ba)


def _imbalance(depth, levels: int = 3) -> float:
    bids = sorted(depth.buy_orders.items(), reverse=True)[:levels]
    asks = sorted(depth.sell_orders.items())[:levels]

    bid_vol = sum(max(0, vol) for _, vol in bids)
    ask_vol = sum(abs(vol) for _, vol in asks)

    if bid_vol + ask_vol <= 0:
        return 0.0

    return (bid_vol - ask_vol) / (bid_vol + ask_vol)


def _ew_z(stats: Dict[str, List[float]], key: str, value: float) -> float:
    item = stats.get(key)

    if not isinstance(item, list) or len(item) != 3:
        stats[key] = [value, 1.0, 1.0]
        return 0.0

    mean = float(item[0])
    var = max(float(item[1]), 1e-6)
    n = int(item[2])

    if n >= 5:
        z = (value - mean) / math.sqrt(var)
        z = _clip(z, -5.0, 5.0)
    else:
        z = 0.0

    diff = value - mean
    mean = mean + EW_ALPHA * diff
    var = (1.0 - EW_ALPHA) * (var + EW_ALPHA * diff * diff)

    stats[key] = [mean, max(var, 1e-6), float(min(n + 1, 1_000_000))]

    return z


def _update_pair_z(
    mids: Dict[str, float],
    stats: Dict[str, List[float]],
) -> Dict[str, float]:
    out: Dict[str, float] = {}

    for a, b in HARD_PAIRS:
        if a not in mids or b not in mids:
            continue

        spread = mids[a] - mids[b]
        key = "p" + _pid(a) + "_" + _pid(b)
        z = _ew_z(stats, key, spread)

        if z != 0.0:
            out[a] = out.get(a, 0.0) + z
            out[b] = out.get(b, 0.0) - z

    return out


def _update_group_z(
    mids: Dict[str, float],
    prev_mid: Dict[str, float],
    stats: Dict[str, List[float]],
) -> Tuple[Dict[str, float], Dict[str, float]]:
    groups: Dict[str, List[str]] = {}

    for product in mids:
        groups.setdefault(_family(product), []).append(product)

    return_z: Dict[str, float] = {}
    level_z: Dict[str, float] = {}

    for _, products in groups.items():
        if len(products) < 2:
            continue

        active = []
        returns = []

        for p in products:
            key = _pid(p)
            if key in prev_mid:
                active.append(p)
                returns.append(mids[p] - prev_mid[key])

        if len(active) >= 2:
            avg_ret = _mean(returns)

            for p in active:
                key = _pid(p)
                resid = mids[p] - prev_mid[key] - avg_ret
                z = _ew_z(stats, "r" + key, resid)
                return_z[p] = z

        group_mid = _mean([mids[p] for p in products])

        for p in products:
            key = _pid(p)
            spread = mids[p] - group_mid
            z = _ew_z(stats, "l" + key, spread)
            level_z[p] = z

    for p, mid in mids.items():
        prev_mid[_pid(p)] = mid

    return return_z, level_z


def _qty_from_signal(strength: float, fam_max_qty: int) -> int:
    if strength >= 3.0:
        return min(MAX_ORDER_SIZE, fam_max_qty)
    if strength >= 2.1:
        return min(4, fam_max_qty)
    if strength >= 1.5:
        return min(3, fam_max_qty)
    if strength >= 1.1:
        return min(2, fam_max_qty)
    return 1


class Trader:
    def run(self, state) -> Tuple[Dict[str, List[Any]], int, str]:
        try:
            memory = jsonpickle.decode(state.traderData) if state.traderData else {}
            if not isinstance(memory, dict):
                memory = {}
        except Exception:
            memory = {}

        prev_mid: Dict[str, float] = memory.get("m", {})
        stats: Dict[str, List[float]] = memory.get("s", {})

        result: Dict[str, List[Any]] = {}
        mids: Dict[str, float] = {}

        for product, depth in state.order_depths.items():
            if product in BAD_PRODUCTS:
                continue

            bb, _, ba, _ = _best_bid_ask(depth)
            if bb <= 0 and ba <= 0:
                continue

            fair = _fair_from_l2(depth, bb, ba)
            mids[product] = (bb + ba) / 2.0 if bb > 0 and ba > 0 else fair

        pair_z = _update_pair_z(mids, stats)
        return_z, level_z = _update_group_z(mids, prev_mid, stats)

        timestamp = int(getattr(state, "timestamp", 0))
        day_tick = timestamp % 1_000_000

        for product, depth in state.order_depths.items():
            if product in BAD_PRODUCTS:
                continue

            position = state.position.get(product, 0)

            bb, bb_vol, ba, ba_vol = _best_bid_ask(depth)
            if bb <= 0 and ba <= 0:
                continue

            if product not in mids:
                continue

            fam = _family(product)
            threshold, fam_max_qty = FAMILY_PARAMS.get(fam, (BASE_THRESHOLD, 3))

            if day_tick >= LATE_TICK:
                threshold += 0.25

            pz = pair_z.get(product, 0.0)
            rz = return_z.get(product, 0.0)
            lz = level_z.get(product, 0.0)
            imb = _imbalance(depth)

            # Positive total_z means rich/overvalued -> sell.
            # Negative total_z means cheap/undervalued -> buy.
            total_z = (
                PAIR_WEIGHT * pz
                + RETURN_WEIGHT * rz
                + LEVEL_WEIGHT * lz
                - IMBALANCE_WEIGHT * imb
            )

            total_z = _clip(total_z, -5.0, 5.0)
            strength = abs(total_z)

            qty_base = _qty_from_signal(strength, fam_max_qty)

            orders: List[Any] = []

            # Very late: reduce inventory instead of opening fresh slow mean-reversion risk.
            if day_tick >= VERY_LATE_TICK:
                if position > 0 and bb > 0 and bb_vol > 0:
                    qty = min(position, bb_vol, MAX_ORDER_SIZE)
                    if qty > 0:
                        orders.append(Order(product, bb, -qty))
                elif position < 0 and ba > 0 and ba_vol > 0:
                    qty = min(-position, ba_vol, MAX_ORDER_SIZE)
                    if qty > 0:
                        orders.append(Order(product, ba, qty))

                if orders:
                    result[product] = orders
                continue

            # Marketable buy: product is cheap.
            if total_z <= -threshold and ba > 0 and ba_vol > 0:
                buy_capacity = POSITION_LIMIT - position
                qty = min(qty_base, buy_capacity, ba_vol)

                if qty > 0:
                    orders.append(Order(product, ba, int(qty)))

            # Marketable sell: product is rich.
            elif total_z >= threshold and bb > 0 and bb_vol > 0:
                sell_capacity = POSITION_LIMIT + position
                qty = min(qty_base, sell_capacity, bb_vol)

                if qty > 0:
                    orders.append(Order(product, bb, -int(qty)))

            # Extra inventory correction if signal flips against current position.
            if not orders:
                if position > 5 and total_z > 0.25 and bb > 0 and bb_vol > 0:
                    qty = min(position, bb_vol, 2)
                    if qty > 0:
                        orders.append(Order(product, bb, -int(qty)))

                elif position < -5 and total_z < -0.25 and ba > 0 and ba_vol > 0:
                    qty = min(-position, ba_vol, 2)
                    if qty > 0:
                        orders.append(Order(product, ba, int(qty)))

            if orders:
                result[product] = orders

        try:
            trader_data = jsonpickle.encode({
                "m": prev_mid,
                "s": stats,
            })
        except Exception:
            trader_data = ""

        return result, 0, trader_data