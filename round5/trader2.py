from __future__ import annotations

import math
from typing import Any, Dict, List, Tuple

import jsonpickle
from datamodel import Order


POSITION_LIMIT = 10
MAX_ORDER_SIZE = 5

HIST_WINDOW = 80
PAIR_WINDOW = 90
TREND_WINDOW = 25

TAKE_EDGE = 3.0
MAX_FAIR_SHIFT = 8.0

PAIR_Z = 1.15
GROUP_Z = 1.20
LEVEL_Z = 1.25

PAIR_SHIFT = 3.5
GROUP_SHIFT = 2.2
LEVEL_SHIFT = 1.6
IMBALANCE_SHIFT = 1.5

LATE_START = 0.82
VERY_LATE = 0.94


HARD_PAIRS = [
    ("MICROCHIP_RECTANGLE", "MICROCHIP_SQUARE"),
    ("MICROCHIP_OVAL", "MICROCHIP_CIRCLE"),
    ("SNACKPACK_RASPBERRY", "SNACKPACK_VANILLA"),
    ("SNACKPACK_PISTACHIO", "SNACKPACK_STRAWBERRY"),
    ("GALAXY_SOUNDS_SOLAR_FLAMES", "GALAXY_SOUNDS_SOLAR_WINDS"),
    ("SLEEP_POD_LAMB_WOOL", "SLEEP_POD_NYLON"),
]


FAMILY_PARAMS = {
    "MICROCHIP": (1.05, 3.0),
    "SNACKPACK": (1.10, 3.2),
    "GALAXY_SOUNDS": (1.20, 2.5),
    "SLEEP_POD": (1.15, 2.8),
    "PANEL": (1.25, 2.0),
    "OXYGEN_SHAKE": (1.20, 2.2),
    "UV_VISOR": (1.20, 2.2),
    "TRANSLATOR": (1.15, 2.5),
    "ROBOT": (1.25, 2.0),
}


BAD_PRODUCTS = set()


def _family(product: str) -> str:
    for prefix in FAMILY_PARAMS:
        if product.startswith(prefix + "_"):
            return prefix
    return product.split("_")[0]


def _mean(xs: List[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _std(xs: List[float]) -> float:
    n = len(xs)
    if n < 8:
        return 0.0
    m = _mean(xs)
    return math.sqrt(sum((x - m) * (x - m) for x in xs) / (n - 1))


def _clip(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _best_bid_ask(depth) -> Tuple[int, int, int, int]:
    bids = depth.buy_orders
    asks = depth.sell_orders

    if bids:
        bb = max(bids)
        bv = bids[bb]
    else:
        bb, bv = 0, 0

    if asks:
        ba = min(asks)
        av = abs(asks[ba])
    else:
        ba, av = 0, 0

    return bb, bv, ba, av


def _fair_from_l2(depth, bb: int, ba: int) -> float:
    bids = sorted(depth.buy_orders.keys(), reverse=True)
    asks = sorted(depth.sell_orders.keys())

    if len(bids) >= 2 and len(asks) >= 2:
        return (bids[1] + asks[1]) / 2.0

    if bb and ba:
        return (bb + ba) / 2.0

    return float(bb or ba)


def _imbalance(depth, levels: int = 3) -> float:
    bids = sorted(depth.buy_orders.items(), reverse=True)[:levels]
    asks = sorted(depth.sell_orders.items())[:levels]

    bv = sum(max(0, v) for _, v in bids)
    av = sum(abs(v) for _, v in asks)

    if bv + av <= 0:
        return 0.0

    return (bv - av) / (bv + av)


def _progress(timestamp: int) -> float:
    t = timestamp % 1_000_000
    return _clip(t / 1_000_000.0, 0.0, 1.0)


def _update_pair_z(
    mids: Dict[str, float],
    pair_hist: Dict[str, List[float]],
) -> Tuple[Dict[str, float], Dict[str, List[float]]]:
    out: Dict[str, float] = {}

    for a, b in HARD_PAIRS:
        if a not in mids or b not in mids:
            continue

        key = a + "|" + b
        spread = mids[a] - mids[b]
        hist = pair_hist.get(key, [])
        s = _std(hist)

        if s > 1e-9:
            z = (spread - _mean(hist)) / s
            out[a] = out.get(a, 0.0) + z
            out[b] = out.get(b, 0.0) - z

        hist.append(spread)
        if len(hist) > PAIR_WINDOW:
            del hist[0: len(hist) - PAIR_WINDOW]
        pair_hist[key] = hist

    return out, pair_hist


def _update_group_z(
    mids: Dict[str, float],
    prev_mid: Dict[str, float],
    resid_hist: Dict[str, List[float]],
    level_hist: Dict[str, List[float]],
) -> Tuple[Dict[str, float], Dict[str, float], Dict[str, float], Dict[str, List[float]], Dict[str, List[float]]]:

    groups: Dict[str, List[str]] = {}
    for p in mids:
        groups.setdefault(_family(p), []).append(p)

    return_z: Dict[str, float] = {}
    level_z: Dict[str, float] = {}

    for fam, products in groups.items():
        if len(products) < 2:
            continue

        active = [p for p in products if p in prev_mid]
        if len(active) >= 2:
            rets = [mids[p] - prev_mid[p] for p in active]
            avg_ret = _mean(rets)

            for p in active:
                resid = mids[p] - prev_mid[p] - avg_ret
                hist = resid_hist.get(p, [])
                s = _std(hist)

                if s > 1e-9:
                    return_z[p] = resid / s

                hist.append(resid)
                if len(hist) > HIST_WINDOW:
                    del hist[0: len(hist) - HIST_WINDOW]
                resid_hist[p] = hist

        group_mid = _mean([mids[p] for p in products])

        for p in products:
            spread = mids[p] - group_mid
            hist = level_hist.get(p, [])
            s = _std(hist)

            if s > 1e-9:
                level_z[p] = (spread - _mean(hist)) / s

            hist.append(spread)
            if len(hist) > HIST_WINDOW:
                del hist[0: len(hist) - HIST_WINDOW]
            level_hist[p] = hist

    for p, m in mids.items():
        prev_mid[p] = m

    return return_z, level_z, prev_mid, resid_hist, level_hist


class Trader:
    def run(self, state) -> Tuple[Dict[str, List[Any]], int, str]:
        try:
            mem = jsonpickle.decode(state.traderData) if state.traderData else {}
            if not isinstance(mem, dict):
                mem = {}
        except Exception:
            mem = {}

        hist = mem.get("h", {})
        opens = mem.get("o", {})
        prev_mid = mem.get("pm", {})
        resid_hist = mem.get("rh", {})
        level_hist = mem.get("lh", {})
        pair_hist = mem.get("ph", {})

        result: Dict[str, List[Any]] = {}
        mids: Dict[str, float] = {}

        for product, depth in state.order_depths.items():
            bb, _, ba, _ = _best_bid_ask(depth)
            if bb <= 0 and ba <= 0:
                continue

            fair = _fair_from_l2(depth, bb, ba)
            mids[product] = (bb + ba) / 2.0 if bb and ba else fair

        pair_z, pair_hist = _update_pair_z(mids, pair_hist)
        return_z, level_z, prev_mid, resid_hist, level_hist = _update_group_z(
            mids, prev_mid, resid_hist, level_hist
        )

        prog = _progress(getattr(state, "timestamp", 0))

        for product, depth in state.order_depths.items():
            if product in BAD_PRODUCTS:
                continue

            position = state.position.get(product, 0)
            bb, bv, ba, av = _best_bid_ask(depth)

            if bb <= 0 and ba <= 0:
                continue

            fam = _family(product)
            fam_z, fam_shift = FAMILY_PARAMS.get(fam, (GROUP_Z, GROUP_SHIFT))

            fair = _fair_from_l2(depth, bb, ba)
            mid = mids.get(product, fair)

            if product not in opens:
                opens[product] = mid

            h = hist.get(product, [])
            h.append(mid)
            if len(h) > TREND_WINDOW + 1:
                del h[0: len(h) - (TREND_WINDOW + 1)]
            hist[product] = h

            trend = h[-1] - h[0] if len(h) > 1 else 0.0

            pz = pair_z.get(product, 0.0)
            rz = return_z.get(product, 0.0)
            lz = level_z.get(product, 0.0)
            imb = _imbalance(depth)

            signal = 0.0

            if abs(pz) >= PAIR_Z:
                signal -= PAIR_SHIFT * pz

            if abs(rz) >= fam_z:
                signal -= fam_shift * rz

            if abs(lz) >= LEVEL_Z:
                signal -= LEVEL_SHIFT * lz

            signal += IMBALANCE_SHIFT * imb

            signal = _clip(signal, -MAX_FAIR_SHIFT, MAX_FAIR_SHIFT)

            late_mult = 1.0
            if prog > LATE_START:
                late_mult = 0.65
            if prog > VERY_LATE:
                late_mult = 0.35

            fair += signal * late_mult

            spread = (ba - bb) if bb and ba else 0
            k = max(2, int((spread - 1) // 2)) if spread > 0 else 3

            confidence = abs(pz) + 0.7 * abs(rz) + 0.5 * abs(lz) + 0.5 * abs(imb)

            if confidence > 2.5:
                k = max(1, k - 1)

            base_size = 1
            if confidence > 1.5:
                base_size = 2
            if confidence > 2.2:
                base_size = 3
            if confidence > 3.0:
                base_size = 5

            if prog > LATE_START and confidence < 2.0:
                base_size = max(1, base_size // 2)

            if prog > VERY_LATE and confidence < 2.7:
                base_size = 1

            buy_cap = min(base_size, POSITION_LIMIT - position)
            sell_cap = min(base_size, POSITION_LIMIT + position)

            if trend > 10:
                buy_cap = max(0, buy_cap // 2)
            elif trend < -10:
                sell_cap = max(0, sell_cap // 2)

            orders: List[Any] = []

            # Aggressive taker only when fair exceeds spread by enough.
            if ba > 0 and fair - ba > TAKE_EDGE and buy_cap > 0:
                qty = min(buy_cap, av)
                if qty > 0:
                    orders.append(Order(product, ba, qty))
                    buy_cap -= qty
                    position += qty

            if bb > 0 and bb - fair > TAKE_EDGE and sell_cap > 0:
                qty = min(sell_cap, bv)
                if qty > 0:
                    orders.append(Order(product, bb, -qty))
                    sell_cap -= qty
                    position -= qty

            buy_price = int(fair - k)
            sell_price = int(fair + k + 0.999999)

            if bb > 0:
                buy_price = min(buy_price, bb)
            if ba > 0:
                sell_price = max(sell_price, ba)

            if ba > 0 and buy_price >= ba:
                buy_price = ba - 1
            if bb > 0 and sell_price <= bb:
                sell_price = bb + 1

            # Directional gating: rich product => don't buy, cheap product => don't sell.
            total_z = pz + 0.7 * rz + 0.5 * lz

            if total_z > fam_z:
                buy_cap = 0
                sell_cap = max(sell_cap, min(base_size, POSITION_LIMIT + position))

            elif total_z < -fam_z:
                sell_cap = 0
                buy_cap = max(buy_cap, min(base_size, POSITION_LIMIT - position))

            if buy_price > 0 and buy_cap > 0:
                orders.append(Order(product, buy_price, buy_cap))

            if sell_price > 0 and sell_cap > 0:
                orders.append(Order(product, sell_price, -sell_cap))

            if orders:
                result[product] = orders

        try:
            trader_data = jsonpickle.encode({
                "h": hist,
                "o": opens,
                "pm": prev_mid,
                "rh": resid_hist,
                "lh": level_hist,
                "ph": pair_hist,
            })
        except Exception:
            trader_data = ""

        return result, 0, trader_data