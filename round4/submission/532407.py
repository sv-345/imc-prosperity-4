"""nN33_voucher_imb_skip — nN32 + extend imb-skip to vouchers (5000-5400).

Voucher imb≥0.7 forward UP +0.29-0.32 t=+23 to +35 (4-6k events per strike).
Voucher imb≤0.3 forward DOWN -0.24 to -0.29 t=-24 to -33 (similar n).

When voucher imb high, skip ASK (avoid being run over). When low, skip BID.
Existing delta1 MM posts ASK at ba-1 every tick — when imb is heavy-bid, that
ask gets run over by aggressive buyers at adverse price. SKIP the ask in
this state. Symmetric: imb ≤ 0.4 → skip BID (forward DOWN).
"""
from __future__ import annotations

import json
import math
from typing import Dict, List

from datamodel import Order, OrderDepth, TradingState


POS_LIMIT: Dict[str, int] = {
    "HYDROGEL_PACK": 200,
    "VELVETFRUIT_EXTRACT": 200,
    "VEV_4000": 300,
    "VEV_4500": 300,
    "VEV_5000": 300,
    "VEV_5100": 300,
    "VEV_5200": 300,
    "VEV_5300": 300,
    "VEV_5400": 300,
    "VEV_5500": 300,
    "VEV_6000": 300,
    "VEV_6500": 300,
}
POS_BUDGET: Dict[str, int] = {p: int(1.0 * lim) for p, lim in POS_LIMIT.items()}  # v85x: 0.9→1.0

FV_ANCHOR: Dict[str, float] = {
    "HYDROGEL_PACK": 9991.0,
    "VELVETFRUIT_EXTRACT": 5250.0,
}

VEV_WING_IV: Dict[int, float] = {6000: 0.0, 6500: 0.0}  # v13: zero theo → never buy wings (v12 showed liquidation uses intrinsic ≈ 0)
R3_LIVE_TTE_YEARS: float = 4.0 / 365.0  # R4 port: was 5.0/365.0

# v85m: per-strike σ from EMPIRICAL bisection on bot quotes (per
# `analysis/r3/sigma_and_dS_empirical.md`). The previous fit
# `iv_replay_per_day.csv` was 0.008-0.011 too HIGH (rescaled to a
# different objective). Day-3 projections used here.
SIGMA_K_LIVE: Dict[int, float] = {
    5000: 0.2326,
    5100: 0.2236,
    5200: 0.2339,
    5300: 0.2377,
    5400: 0.2193,
    5500: 0.2409,
}

DELTA1_PRODUCTS = ("HYDROGEL_PACK", "VELVETFRUIT_EXTRACT")
VEV_PASSIVE_MM_STRIKES = (5000, 5100, 5200, 5300)  # v65: added 5300
VEV_TIGHT_MM_STRIKES = (5400, 5500)
# v9: ask-only (sell OTM vouchers inside bot's ask when underlying above mid).
# v2 server data: 5300/5400 had +92/+91 from pure sell-side flow. Pattern
# was bot takers lifted our asks → we profited when mid drifted down. With
# tight spread (~2), we can quote ONLY the ask at ba-1 without crossing.
VEV_ASK_ONLY_STRIKES = ()  # v10: disabled (v9 slightly negative)
VEV_BID_ONLY_STRIKES = ()  # v11: also disabled (net negative on server)
VEV_PINNED_STRIKES = (6000, 6500)
VEV_DEEP_ITM_STRIKES = (4000, 4500)

DELTA1_QUOTE_SIZE: Dict[str, int] = {
    "HYDROGEL_PACK": 30,
    "VELVETFRUIT_EXTRACT": 50,
}
VOUCHER_PASSIVE_SIZE = 50  # v85o: 15→50

# v86p: BSM deltas per strike (S=5260, T=5/365, σ_K from SIGMA_K_LIVE)
# Used for overshoot-detection mean-revert signal.
VOUCHER_DELTA: Dict[int, float] = {
    5000: 0.95, 5100: 0.85, 5200: 0.65, 5300: 0.42, 5400: 0.18, 5500: 0.07,
}
ONE_SIDED_POS_FRAC = 0.30


def norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2)))


def bs_call(S: float, K: float, T: float, sigma: float) -> float:
    if T <= 0 or sigma <= 0 or S <= 0:
        return max(S - K, 0.0)
    vol = sigma * math.sqrt(T)
    d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / vol
    d2 = d1 - vol
    return S * norm_cdf(d1) - K * norm_cdf(d2)


def voucher_theo(velvet_mid: float, K: int) -> float:
    """v84: BSM theo at current VELVET mid using per-strike σ_K."""
    sigma = SIGMA_K_LIVE.get(K, 0.244)
    return bs_call(velvet_mid, float(K), R3_LIVE_TTE_YEARS, sigma)


DRIFT_GUARD_STRIKES = (5200, 5300, 5400, 5500)

# nN1: regime-shift guard. Trips when |VELV_mid - anchor| > GUARD_DEV for
# GUARD_CONSEC consecutive ticks. R4 D1/D2/D3 max abs dev = 58.5 → threshold 60
# is dormant on training. Directional: low_active gates BUY, high_active gates SELL.
GUARD_DEV: float = 60.0
GUARD_CONSEC: int = 30


def drift_buy_scale(drop_from_open: float) -> float:
    """17->0.4, 48->0.0 (sweep). Throttles voucher BUY takes when VELV down-trends."""
    if drop_from_open <= 30:
        return 1.0
    if drop_from_open <= 60:
        return 0.4
    return 0.0


class State:
    __slots__ = ("tick", "last_mid", "closed", "velvet_ask_cooldown",
                 "ema_theo_diff", "ema_abs_dev", "velvet_mid_prev",
                 "velvet_open", "agg_buy", "agg_sell", "m67_stick",
                 "guard_run_low", "guard_run_high")

    def __init__(self) -> None:
        self.tick: int = 0
        self.last_mid: Dict[str, float] = {}
        self.closed: Dict[str, bool] = {}
        self.velvet_ask_cooldown: int = 0
        self.ema_theo_diff: Dict[str, float] = {}
        self.ema_abs_dev: Dict[str, float] = {}
        self.velvet_mid_prev: float = 0.0
        self.velvet_open: float = 0.0
        self.agg_buy: Dict[str, float] = {}
        self.agg_sell: Dict[str, float] = {}
        self.m67_stick: int = 0
        # nN1: regime-shift guard counters
        self.guard_run_low: int = 0   # mid sustained below anchor - GUARD_DEV
        self.guard_run_high: int = 0  # mid sustained above anchor + GUARD_DEV

    def to_json(self) -> str:
        return json.dumps({
            "tick": self.tick, "last_mid": self.last_mid,
            "closed": self.closed,
            "velvet_ask_cooldown": self.velvet_ask_cooldown,
            "ema_theo_diff": self.ema_theo_diff,
            "ema_abs_dev": self.ema_abs_dev,
            "velvet_mid_prev": self.velvet_mid_prev,
            "velvet_open": self.velvet_open,
            "agg_buy": self.agg_buy,
            "agg_sell": self.agg_sell,
            "m67_stick": self.m67_stick,
            "guard_run_low": self.guard_run_low,
            "guard_run_high": self.guard_run_high,
        })

    @classmethod
    def from_json(cls, s: str) -> "State":
        if not s:
            return cls()
        try:
            d = json.loads(s)
        except json.JSONDecodeError:
            return cls()
        out = cls()
        out.tick = int(d.get("tick", 0))
        out.last_mid = {k: float(v) for k, v in d.get("last_mid", {}).items()}
        out.closed = {k: bool(v) for k, v in d.get("closed", {}).items()}
        out.velvet_ask_cooldown = int(d.get("velvet_ask_cooldown", 0))
        out.ema_theo_diff = {k: float(v) for k, v in d.get("ema_theo_diff", {}).items()}
        out.ema_abs_dev = {k: float(v) for k, v in d.get("ema_abs_dev", {}).items()}
        out.velvet_mid_prev = float(d.get("velvet_mid_prev", 0.0))
        out.velvet_open = float(d.get("velvet_open", 0.0))
        out.agg_buy = {k: float(v) for k, v in d.get("agg_buy", {}).items()}
        out.agg_sell = {k: float(v) for k, v in d.get("agg_sell", {}).items()}
        out.m67_stick = int(d.get("m67_stick", 0))
        out.guard_run_low = int(d.get("guard_run_low", 0))
        out.guard_run_high = int(d.get("guard_run_high", 0))
        return out


def best_bid_ask(depth: OrderDepth) -> tuple[int | None, int | None, int | None, int | None]:
    bb = max(depth.buy_orders) if depth.buy_orders else None
    ba = min(depth.sell_orders) if depth.sell_orders else None
    bb_vol = depth.buy_orders.get(bb, 0) if bb is not None else None
    ba_vol = -depth.sell_orders.get(ba, 0) if ba is not None else None
    return bb, ba, bb_vol, ba_vol


def cap_orders(orders: List[Order], current_pos: int, limit: int) -> List[Order]:
    max_buy = max(limit - current_pos, 0)
    max_sell = max(limit + current_pos, 0)
    out: List[Order] = []
    used_buy = 0
    used_sell = 0
    for o in orders:
        if o.quantity > 0:
            allowed = min(o.quantity, max(max_buy - used_buy, 0))
            if allowed > 0:
                out.append(Order(o.symbol, o.price, allowed))
                used_buy += allowed
        elif o.quantity < 0:
            qty = -o.quantity
            allowed = min(qty, max(max_sell - used_sell, 0))
            if allowed > 0:
                out.append(Order(o.symbol, o.price, -allowed))
                used_sell += allowed
    return out


def get_mid(depth: OrderDepth) -> float | None:
    bb, ba, _, _ = best_bid_ask(depth)
    if bb is not None and ba is not None:
        return (bb + ba) / 2.0
    return float(bb) if bb is not None else (float(ba) if ba is not None else None)


def delta1_orders(product: str, depth: OrderDepth, current_pos: int, budget: int, anchor: float, tight_surface: bool = False, skip_velvet_ask: bool = False) -> List[Order]:
    """v18: HYDROGEL-only anchor-relative take (v17 blew up HYDROGEL from
    $609 to $4757 but hurt VELVETFRUIT). VELVETFRUIT uses plain passive MM.
    """
    bb, ba, _, _ = best_bid_ask(depth)
    orders: List[Order] = []
    if bb is None or ba is None:
        return orders
    if ba - bb < 2:
        return orders
    size = DELTA1_QUOTE_SIZE.get(product, 10)

    # Anchor-relative take. Best config: HY BUY 32 / SELL 28. VL BUY 18 / SELL 23.
    take_buy_edges = {"HYDROGEL_PACK": 46, "VELVETFRUIT_EXTRACT": 18}  # v135: HY buy 32→34
    take_sell_edges = {"HYDROGEL_PACK": 28, "VELVETFRUIT_EXTRACT": 23}
    take_buy_edge = take_buy_edges.get(product, 0)
    take_sell_edge = take_sell_edges.get(product, 0)
    if take_buy_edge > 0:
        if ba <= anchor - take_buy_edge and current_pos < budget:
            vol = -depth.sell_orders[ba]
            qty = min(vol, budget - current_pos, 400)
            if qty > 0:
                orders.append(Order(product, ba, qty))
    if take_sell_edge > 0:
        if bb >= anchor + take_sell_edge and current_pos > -budget:
            vol = depth.buy_orders[bb]
            qty = min(vol, budget + current_pos, 400)
            if qty > 0:
                orders.append(Order(product, bb, -qty))

    # v47: book-sweeping take at extreme edges. When bot quote is absurdly
    # off-anchor, cross deeper into the book to capture levels below the top.
    # v53 reverted: depth-2 was optimal on server. SA2's L1→L2 gap analysis
    # didn't translate (server matching may fill at order price not book price).
    # v86r: asymmetric sweep — HY BUY 50, HY SELL 30
    sweep_buy_edges = {"HYDROGEL_PACK": 80, "VELVETFRUIT_EXTRACT": 30}
    sweep_sell_edges = {"HYDROGEL_PACK": 30, "VELVETFRUIT_EXTRACT": 25}  # v86t
    sb_edge = sweep_buy_edges.get(product, 0)
    ss_edge = sweep_sell_edges.get(product, 0)
    # nN98: gate sweep edges on L1 depletion
    # nN100: also compute L1-L2 gaps for MM gating below
    l1_ask_vol_sw = -depth.sell_orders[ba]
    l1_bid_vol_sw = depth.buy_orders[bb]
    sells_sorted_sw = sorted(depth.sell_orders.keys())
    buys_sorted_sw = sorted(depth.buy_orders.keys(), reverse=True)
    ask_gap_sw = (sells_sorted_sw[1] - sells_sorted_sw[0]) if len(sells_sorted_sw) >= 2 else 0
    bid_gap_sw = (buys_sorted_sw[0] - buys_sorted_sw[1]) if len(buys_sorted_sw) >= 2 else 0
    if sb_edge > 0:
        if ba <= anchor - sb_edge and current_pos < budget and l1_bid_vol_sw > 5:
            qty = min(budget - current_pos, 600)
            if qty > 0:
                orders.append(Order(product, ba + 2, qty))
    if ss_edge > 0:
        if bb >= anchor + ss_edge and current_pos > -budget and l1_ask_vol_sw > 5:
            qty = min(budget + current_pos, 600)
            if qty > 0:
                orders.append(Order(product, bb - 2, -qty))

    already_buy = sum(o.quantity for o in orders if o.quantity > 0)
    already_sell = sum(-o.quantity for o in orders if o.quantity < 0)
    # v60 rejected: bb+2/ba-2 on HYDROGEL lost $60. A2's "same fill rate"
    # claim was wrong — bb+2 misses bot-to-bot trades priced at bb+1 that
    # would have stepped into bb+1 quotes. Reverted to bb+1/ba-1.
    # composition: HY MM offset override
    # n75: HY+VELV MM at bb/ba (be like Mark 14 — proven +$7,248 BT vs bb+1)
    _hy_bid_off = 0
    _hy_ask_off = 0
    _bid_px = bb + _hy_bid_off
    _ask_px = ba - _hy_ask_off
    # nN100: gate HY/VELV MM directional side on L1-L2 GAP signal.
    # ask_gap_sw/bid_gap_sw computed above (sweep block). Reuse.
    # If ask_gap >= 5 (HY) / 3 (VELV), mid likely rising → skip ASK side (avoid selling into rising mid)
    # If bid_gap >= 5 (HY) / 3 (VELV), mid likely falling → skip BID side (avoid buying into falling mid)
    _gap_thr = 5 if product == "HYDROGEL_PACK" else 3
    _skip_bid = bid_gap_sw >= _gap_thr
    _skip_ask = ask_gap_sw >= _gap_thr
    if current_pos + already_buy < budget and _bid_px < _ask_px and _bid_px >= 1 and not _skip_bid:
        orders.append(Order(product, _bid_px, min(size, budget - current_pos - already_buy)))
    if current_pos - already_sell > -budget and not skip_velvet_ask and _bid_px < _ask_px and _ask_px >= 1 and not _skip_ask:
        orders.append(Order(product, _ask_px, -min(size, budget + current_pos - already_sell)))
    return orders


def vev_passive_mm_orders(
    product: str, depth: OrderDepth, current_pos: int, budget: int
) -> List[Order]:
    """v68: multi-level voucher passive MM.
    Layer 1: bb+1 / ba-1 (1 tick inside) when spread >= 3.
    Layer 2: bb+2 / ba-2 (2 ticks inside) when spread >= 5.
    Captures bot-bot trades at multiple price points per tick via step-in
    matching. Sized smaller per layer (8) to limit adverse exposure.
    """
    bb, ba, _, _ = best_bid_ask(depth)
    orders: List[Order] = []
    if bb is None or ba is None:
        return orders
    spread = ba - bb
    if spread < 3:
        return orders
    layer1_size = 15
    layer2_size = 8
    pos_frac = current_pos / max(budget, 1)
    allow_bid = pos_frac < ONE_SIDED_POS_FRAC
    allow_ask = pos_frac > -ONE_SIDED_POS_FRAC
    if pos_frac > 0:
        allow_ask = True
    if pos_frac < 0:
        allow_bid = True
    if allow_bid and current_pos < budget:
        # Layer 1
        bid_size = min(layer1_size, budget - current_pos)
        if bid_size > 0:
            orders.append(Order(product, bb + 1, bid_size))
        # Layer 2 (if spread permits)
        if spread >= 5:
            already = sum(o.quantity for o in orders if o.quantity > 0)
            l2 = min(layer2_size, budget - current_pos - already)
            if l2 > 0:
                orders.append(Order(product, bb + 2, l2))
    if allow_ask and current_pos > -budget:
        ask_size = min(layer1_size, budget + current_pos)
        if ask_size > 0:
            orders.append(Order(product, ba - 1, -ask_size))
        if spread >= 5:
            already = sum(-o.quantity for o in orders if o.quantity < 0)
            l2 = min(layer2_size, budget + current_pos - already)
            if l2 > 0:
                orders.append(Order(product, ba - 2, -l2))
    return orders


def wing_voucher_orders(
    product: str, strike: int, underlying_mid: float, depth: OrderDepth, current_pos: int, budget: int
) -> List[Order]:
    bb, ba, _, _ = best_bid_ask(depth)
    orders: List[Order] = []
    if ba is None:
        return orders
    iv = VEV_WING_IV.get(strike, 0.35)
    theo = bs_call(underlying_mid, strike, R3_LIVE_TTE_YEARS, iv)
    if ba <= theo and current_pos < budget:
        vol = -depth.sell_orders[ba]
        qty = min(vol, budget - current_pos, 50)
        if qty > 0:
            orders.append(Order(product, ba, qty))
    # n51/n62: bid-at-0 on VEV_6000/6500 wings. Inv1 confirmed Mark 22 sells
    # ~100/day per strike at price 0; long-at-0 marked at last-tick mid 0.5 →
    # +$0.50/unit. Exempted from inv-throttle numerator below.
    if current_pos < budget:
        already_buy = sum(o.quantity for o in orders if o.quantity > 0)
        size = min(50, budget - current_pos - already_buy)
        if size > 0:
            orders.append(Order(product, 0, size))
    return orders


def deep_itm_orders(
    product: str, strike: int, underlying_mid: float, depth: OrderDepth, current_pos: int, budget: int
) -> List[Order]:
    bb, ba, _, _ = best_bid_ask(depth)
    orders: List[Order] = []
    if bb is None or ba is None:
        return orders
    intrinsic = max(underlying_mid - strike, 0.0)
    tv_cap = 2.0
    if ba <= intrinsic + 1 and current_pos < budget:
        vol = -depth.sell_orders[ba]
        qty = min(vol, budget - current_pos, 600)
        if qty > 0:
            orders.append(Order(product, ba, qty))
    if bb >= intrinsic + tv_cap - 1 and current_pos > -budget:
        vol = depth.buy_orders[bb]
        qty = min(vol, budget + current_pos, 600)
        if qty > 0:
            orders.append(Order(product, bb, -qty))
    return orders


def deep_itm_orders_with_mm(
    product: str, strike: int, underlying_mid: float, depth: OrderDepth, current_pos: int, budget: int
) -> List[Order]:
    """v43: take + passive MM layered on deep-ITM strikes (4000, 4500) with
    spread typically ≥6."""
    bb, ba, _, _ = best_bid_ask(depth)
    orders: List[Order] = []
    if bb is None or ba is None:
        return orders
    intrinsic = max(underlying_mid - strike, 0.0)
    tv_cap = 2.0
    if ba <= intrinsic + 1 and current_pos < budget:
        vol = -depth.sell_orders[ba]
        qty = min(vol, budget - current_pos, 600)
        if qty > 0:
            orders.append(Order(product, ba, qty))
    if bb >= intrinsic + tv_cap - 1 and current_pos > -budget:
        vol = depth.buy_orders[bb]
        qty = min(vol, budget + current_pos, 600)
        if qty > 0:
            orders.append(Order(product, bb, -qty))
    if ba - bb >= 6:
        size = 15
        already_buy = sum(o.quantity for o in orders if o.quantity > 0)
        already_sell = sum(-o.quantity for o in orders if o.quantity < 0)
        # n75: deep_itm passive MM at bb/ba (Mark 14 trades VEV_4000 heavily)
        if current_pos + already_buy < budget:
            orders.append(Order(product, bb, min(size, budget - current_pos - already_buy)))
        if current_pos - already_sell > -budget:
            orders.append(Order(product, ba, -min(size, budget + current_pos - already_sell)))
    return orders


def tight_strike_mm_orders(product, depth, current_pos, budget):
    """v46: passive MM on tight-spread strikes (5300, 5400, 5500) by joining
    the bot's queue at bb or ba rather than crossing. Small size to limit
    adverse exposure. Only quotes when spread ≥ 2."""
    bb, ba, _, _ = best_bid_ask(depth)
    orders: List[Order] = []
    if bb is None or ba is None:
        return orders
    if ba - bb < 2:
        return orders
    size = 5
    # Join bot's quotes (not inside) — FIFO puts us second but captures any overflow.
    if current_pos < budget:
        orders.append(Order(product, bb, min(size, budget - current_pos)))
    if current_pos > -budget:
        orders.append(Order(product, ba, -min(size, budget + current_pos)))
    return orders


class Trader:
    def run(self, state: TradingState):
        s = State.from_json(state.traderData or "")
        s.tick += 1
        # v86p: snapshot prev mids BEFORE updating last_mid
        prev_mids = dict(s.last_mid)

        for product, depth in state.order_depths.items():
            mid = get_mid(depth)
            if mid is not None:
                s.last_mid[product] = mid

        # nP1: aggressor-flow EWMA per voucher strike. Use prev-tick mid as
        # reference: trade price > prev_mid → buy-aggr; < → sell-aggr; equal skip.
        FLOW_DECAY = 0.99
        for K in (5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500):
            sym = f"VEV_{K}"
            prev_m = prev_mids.get(sym)
            s.agg_buy[sym] = s.agg_buy.get(sym, 0.0) * FLOW_DECAY
            s.agg_sell[sym] = s.agg_sell.get(sym, 0.0) * FLOW_DECAY
            if prev_m is None:
                continue
            for tr in state.market_trades.get(sym, []):
                if tr.price > prev_m:
                    s.agg_buy[sym] += tr.quantity
                elif tr.price < prev_m:
                    s.agg_sell[sym] += tr.quantity

        pass

        underlying_mid = s.last_mid.get("VELVETFRUIT_EXTRACT", FV_ANCHOR["VELVETFRUIT_EXTRACT"])
        result: Dict[str, List[Order]] = {}

        # nN1: regime-shift guard tracking. Only updates state — does NOT gate.
        # Threshold 60 is beyond historical max abs deviation (D3 hit 58.5),
        # so on R4 D1/D2/D3 these counters never reach GUARD_CONSEC and the
        # behavior is byte-identical to nK_75. nN1b consumes the active flags.
        velv_anchor = FV_ANCHOR["VELVETFRUIT_EXTRACT"]
        velv_dev = underlying_mid - velv_anchor
        if velv_dev <= -GUARD_DEV:
            s.guard_run_low += 1
        else:
            s.guard_run_low = 0
        if velv_dev >= GUARD_DEV:
            s.guard_run_high += 1
        else:
            s.guard_run_high = 0
        guard_low_active = s.guard_run_low >= GUARD_CONSEC
        guard_high_active = s.guard_run_high >= GUARD_CONSEC

        # n50: VELV drop-from-open guard × inventory factor (combine n47e + n49).
        if s.velvet_open == 0.0 and "VELVETFRUIT_EXTRACT" in s.last_mid:
            s.velvet_open = s.last_mid["VELVETFRUIT_EXTRACT"]
        drop_from_open = (s.velvet_open - underlying_mid) if s.velvet_open > 0 else 0.0
        guard_long_inv = sum(max(state.position.get(f"VEV_{k}", 0), 0) for k in DRIFT_GUARD_STRIKES)
        if guard_long_inv >= 300:
            inv_factor = 0.3
        elif guard_long_inv >= 30:
            inv_factor = 0.7 - 0.39999999999999997 * (guard_long_inv - 30) / 270
        else:
            inv_factor = 1.0
        guard_buy_scale = drift_buy_scale(drop_from_open) * inv_factor

        # v69: per-voucher anchor signal. Each voucher has its own BSM-based
        # anchor: BSM(5250, K, 5/365, σ_K). Take when bot bid/ask deviates
        # from voucher anchor by edge_K. Independent of VELVET signal.
        velvet_depth = state.order_depths.get("VELVETFRUIT_EXTRACT")
        velvet_take_sell = False
        velvet_take_buy = False
        velvet_imb_take_sell = False
        velvet_imb_take_buy = False
        if velvet_depth and velvet_depth.buy_orders and velvet_depth.sell_orders:
            bb_v = max(velvet_depth.buy_orders.keys())
            ba_v = min(velvet_depth.sell_orders.keys())
            anchor_v = FV_ANCHOR["VELVETFRUIT_EXTRACT"]
            bid_vol = sum(velvet_depth.buy_orders.values())
            ask_vol = -sum(velvet_depth.sell_orders.values())
            denom = bid_vol + ask_vol
            velvet_imb = (bid_vol - ask_vol) / denom if denom > 0 else 0.0
            # nN87: gate mirror trigger on L1 depletion
            # If ask thin (<=5), don't take_sell (mid likely to keep rising)
            # If bid thin (<=5), don't take_buy (mid likely to keep falling)
            l1_ask_vol = -velvet_depth.sell_orders[ba_v]
            l1_bid_vol = velvet_depth.buy_orders[bb_v]
            if bb_v >= anchor_v + 21 and not guard_high_active and l1_ask_vol > 5:
                velvet_take_sell = True
            elif ba_v <= anchor_v - 33 and not guard_low_active and l1_bid_vol > 5:
                velvet_take_buy = True
            if velvet_imb >= 0.05:
                velvet_imb_take_sell = True
            elif velvet_imb <= -0.05:
                velvet_imb_take_buy = True

        # v86v: tier-2 mirror at threshold 18 (only deep ITM strikes 4000/4500)
        velvet_tier2_sell = False
        velvet_tier2_buy = False
        if velvet_depth and velvet_depth.buy_orders and velvet_depth.sell_orders:
            bb_v2 = max(velvet_depth.buy_orders.keys())
            ba_v2 = min(velvet_depth.sell_orders.keys())
            anchor_v2 = FV_ANCHOR["VELVETFRUIT_EXTRACT"]
            if bb_v2 >= anchor_v2 + 18 and bb_v2 < anchor_v2 + 21 and not guard_high_active:
                velvet_tier2_sell = True
            elif ba_v2 <= anchor_v2 - 18 and ba_v2 > anchor_v2 - 33 and not guard_low_active:
                velvet_tier2_buy = True
        VOUCHER_MIRROR_STRIKES = (4000, 4500, 5000, 5100, 5200, 5300, 5400)  # excl 5500
        # v73: tight-surface gate with smaller edges (cleaner signal can fire on smaller deviations).
        VOUCHER_ANCHORS = {5000: 262.0, 5100: 172.0, 5200: 95.5, 5300: 47.5, 5400: 17.0, 5500: 7.0}  # v86d
        # v142: asymmetric per-strike anchors. SELL trigger uses sell_anchor; BUY trigger uses buy_anchor.
        VOUCHER_ANCHOR_SELL = dict(VOUCHER_ANCHORS)
        VOUCHER_ANCHOR_SELL[5400] = 18.0
        VOUCHER_ANCHOR_SELL[5100] = 176.0
        VOUCHER_ANCHOR_SELL[5000] = 264.0
        VOUCHER_ANCHOR_BUY = dict(VOUCHER_ANCHORS)
        VOUCHER_ANCHOR_BUY[5000] = 246.0
        VOUCHER_ANCHOR_BUY[5100] = 157.0
        VOUCHER_EDGES_TIGHT = {5000: 0, 5100: 0, 5200: 0, 5300: 4, 5400: 1, 5500: 1}  # v86z
        VOUCHER_EDGES_WIDE = {5000: 99, 5100: 99, 5200: 3, 5300: 4, 5400: 4, 5500: 99}  # v123: enable 5400
        d5200 = state.order_depths.get("VEV_5200")
        d5300 = state.order_depths.get("VEV_5300")
        tight_surface = False
        if (d5200 and d5200.buy_orders and d5200.sell_orders
                and d5300 and d5300.buy_orders and d5300.sell_orders):
            s5200 = min(d5200.sell_orders.keys()) - max(d5200.buy_orders.keys())
            s5300 = min(d5300.sell_orders.keys()) - max(d5300.buy_orders.keys())
            tight_surface = (s5200 <= 2) and (s5300 <= 2)
        VOUCHER_EDGES = VOUCHER_EDGES_WIDE  # n65 always-WIDE

        # v85r: BUY-aggressor detection on VELVET. When market_trades has
        # a buy-aggressor print (price > prev mid), set 5-tick cooldown
        # during which the passive VELVET ask is dropped to avoid adverse
        # selection on the +0.47-tick drift (per bot_to_bot_report.md).
        prev_velvet_mid = s.velvet_mid_prev
        velvet_mid_now = s.last_mid.get("VELVETFRUIT_EXTRACT")
        velvet_market_trades = state.market_trades.get("VELVETFRUIT_EXTRACT", [])
        if prev_velvet_mid > 0 and any(t.price > prev_velvet_mid for t in velvet_market_trades):
            s.velvet_ask_cooldown = 2
        if velvet_mid_now is not None:
            s.velvet_mid_prev = velvet_mid_now
        skip_velvet_ask = s.velvet_ask_cooldown > 0
        if s.velvet_ask_cooldown > 0:
            s.velvet_ask_cooldown -= 1

        # nN32: HYDROGEL imb conditional skip flags
        skip_hydro_ask = False
        skip_hydro_bid = False
        depth_hydro = state.order_depths.get("HYDROGEL_PACK")
        if depth_hydro and depth_hydro.buy_orders and depth_hydro.sell_orders:
            hbb = max(depth_hydro.buy_orders); hba = min(depth_hydro.sell_orders)
            hbbv = depth_hydro.buy_orders[hbb]; hbav = -depth_hydro.sell_orders[hba]
            hd = hbbv + hbav
            if hd > 0:
                himb = hbbv / hd
                if himb >= 0.55: skip_hydro_ask = True
                elif himb <= 0.45: skip_hydro_bid = True


        # v145: voucher inventory throttle on TAKE entries (from v141_invtt)
        # n51/n62: keep wings (6000/6500) in DENOMINATOR (per n37: -$109K when
        # excluded) but EXCLUDE from NUMERATOR so dead-wing carry doesn't trip
        # the throttle.
        INVTT_F = 0.72  # v142 finding: 0.69 better than 0.75 on this base
        voucher_pos_total = 0
        voucher_limit_total = 0
        for prod_name in POS_LIMIT:
            if prod_name.startswith("VEV_"):
                strike_n = int(prod_name.split("_")[1])
                if strike_n not in VEV_PINNED_STRIKES:
                    voucher_pos_total += abs(state.position.get(prod_name, 0))
                voucher_limit_total += POS_LIMIT[prod_name]
        inv_frac = voucher_pos_total / voucher_limit_total if voucher_limit_total > 0 else 0.0
        take_scale = max(0.0, 1.0 - inv_frac) if inv_frac > INVTT_F else 1.0

        for product, depth in state.order_depths.items():
            current_pos = state.position.get(product, 0)
            limit = POS_LIMIT.get(product, 0)
            budget = POS_BUDGET.get(product, 0)
            if limit == 0:
                continue

            orders: List[Order] = []
            if product in DELTA1_PRODUCTS:
                if s.closed.get(product, False):
                    if current_pos != 0:
                        bb, ba, _, _ = best_bid_ask(depth)
                        if bb is not None and ba is not None:
                            if current_pos > 0:
                                orders = [Order(product, bb, -current_pos)]
                            else:
                                orders = [Order(product, ba, -current_pos)]
                else:
                    skip_ask = (product == "VELVETFRUIT_EXTRACT" and skip_velvet_ask) or (product == "HYDROGEL_PACK" and skip_hydro_ask)
                    orders = delta1_orders(product, depth, current_pos, budget, FV_ANCHOR[product], tight_surface, skip_ask)
                    # nN32: post-process to skip BID for HYDRO when imb low
                    if product == "HYDROGEL_PACK" and skip_hydro_bid:
                        orders = [o for o in orders if o.quantity < 0]
            elif product.startswith("VEV_"):
                try:
                    strike = int(product[4:])
                except ValueError:
                    continue

                voucher_take_sell = False
                voucher_take_buy = False
                if strike in VOUCHER_MIRROR_STRIKES:
                    voucher_take_sell = velvet_take_sell
                    voucher_take_buy = velvet_take_buy
                # v142: asymmetric per-side anchor
                if strike in VOUCHER_ANCHORS:
                    bb_v_, ba_v_, _, _ = best_bid_ask(depth)
                    if bb_v_ is not None and ba_v_ is not None:
                        v_edge = VOUCHER_EDGES.get(strike, 5)
                        if bb_v_ >= VOUCHER_ANCHOR_SELL[strike] + v_edge and not guard_high_active:
                            voucher_take_sell = True
                        elif ba_v_ <= VOUCHER_ANCHOR_BUY[strike] - v_edge and not guard_low_active:
                            voucher_take_buy = True
                if not (voucher_take_sell or voucher_take_buy) and (velvet_imb_take_sell or velvet_imb_take_buy):
                    bb_, ba_, _, _ = best_bid_ask(depth)
                    if bb_ is not None and ba_ is not None:
                        if velvet_imb_take_sell and current_pos > -budget:
                            vol = depth.buy_orders[bb_]
                            qty = min(vol, budget + current_pos, 30)
                            qty = int(qty * take_scale)
                            if qty > 0:
                                orders = [Order(product, bb_, -qty)]
                        elif velvet_imb_take_buy and current_pos < budget:
                            vol = -depth.sell_orders[ba_]
                            qty = min(vol, budget - current_pos, 30)
                            qty = int(qty * take_scale)
                            if strike in DRIFT_GUARD_STRIKES:
                                qty = int(qty * guard_buy_scale)
                            if qty > 0:
                                orders = [Order(product, ba_, qty)]
                if voucher_take_sell or voucher_take_buy:
                    bb_, ba_, _, _ = best_bid_ask(depth)
                    if bb_ is not None and ba_ is not None:
                        if voucher_take_sell and current_pos > -budget:
                            vol = depth.buy_orders[bb_]
                            qty = min(vol, budget + current_pos, 600)  # v85aa
                            qty = int(qty * take_scale)
                            if qty > 0:
                                orders = [Order(product, bb_, -qty)]
                        elif voucher_take_buy and current_pos < budget:
                            vol = -depth.sell_orders[ba_]
                            qty = min(vol, budget - current_pos, 600)  # v85aa
                            qty = int(qty * take_scale)
                            if strike in DRIFT_GUARD_STRIKES:
                                qty = int(qty * guard_buy_scale)
                            if qty > 0:
                                orders = [Order(product, ba_, qty)]
                elif strike in VEV_PASSIVE_MM_STRIKES:
                    if s.tick > 1 and "VELVETFRUIT_EXTRACT" in s.last_mid:
                        orders = vev_passive_mm_orders(product, depth, current_pos, budget)
                elif strike in VEV_TIGHT_MM_STRIKES:
                    if s.tick > 1:
                        orders = tight_strike_mm_orders(product, depth, current_pos, budget)
                elif strike in VEV_ASK_ONLY_STRIKES:
                    bb, ba, _, _ = best_bid_ask(depth)
                    if bb is not None and ba is not None and ba - bb >= 2 and current_pos > -budget:
                        orders = [Order(product, ba - 1, -min(3, budget + current_pos))]
                elif strike in VEV_BID_ONLY_STRIKES:
                    bb, ba, _, _ = best_bid_ask(depth)
                    if bb is not None and ba is not None and ba - bb >= 2 and current_pos < budget:
                        orders = [Order(product, bb + 1, min(3, budget - current_pos))]
                elif strike in VEV_PINNED_STRIKES:
                    orders = wing_voucher_orders(product, strike, underlying_mid, depth, current_pos, budget)
                elif strike in VEV_DEEP_ITM_STRIKES:
                    orders = deep_itm_orders_with_mm(product, strike, underlying_mid, depth, current_pos, budget)

            orders = cap_orders(orders, current_pos, limit)
            if orders:
                result[product] = orders

        # n9: Mark 22 sell anticipation. Post bid at bb+1 (queue priority over
        # the bot's bid quote) on positive-EV strikes (5200/5300/5400). Triggered
        # only when Mark 22 sold this strike this tick. Hold via v148 exit logic.
        for sym in ("VEV_5400",):  # nN120: drop 5500 (M22 99% right → wrong direction to fade)
            trades_sym = state.market_trades.get(sym, [])
            mark22_sold = any(t.seller == "Mark 22" for t in trades_sym)
            if not mark22_sold:
                continue
            depth = state.order_depths.get(sym)
            if not depth or not depth.buy_orders or not depth.sell_orders:
                continue
            bb = max(depth.buy_orders)
            ba = min(depth.sell_orders)
            # don't cross — post strictly inside
            if bb + 1 >= ba:
                continue
            current_pos = state.position.get(sym, 0)
            limit = POS_LIMIT.get(sym, 0)
            existing = result.get(sym, [])
            existing_buy = sum(o.quantity for o in existing if o.quantity > 0)
            existing_sell = sum(-o.quantity for o in existing if o.quantity < 0)
            extra_pair: List[Order] = []
            buy_room = max(limit - current_pos - existing_buy, 0)
            qty_b = int(min(200, buy_room) * guard_buy_scale)
            if qty_b > 0:
                extra_pair.append(Order(sym, bb + 1, qty_b))
            # n16: when long inventory exists, also add ASK at ba-1 for exit
            if current_pos > 0:
                sell_room = max(limit + current_pos - existing_sell, 0)
                qty_s = min(current_pos, sell_room, 200)
                if qty_s > 0:
                    extra_pair.append(Order(sym, ba - 1, -qty_s))
            if extra_pair:
                result[sym] = list(existing) + extra_pair

        # n14: VELV Mark 14 buy → ask ba-2 (deeper inside than v148's ba-1).
        v_trades = state.market_trades.get("VELVETFRUIT_EXTRACT", [])
        if any(t.buyer == "Mark 14" for t in v_trades):
            depth_v = state.order_depths.get("VELVETFRUIT_EXTRACT")
            if depth_v and depth_v.buy_orders and depth_v.sell_orders:
                bb_v = max(depth_v.buy_orders)
                ba_v = min(depth_v.sell_orders)
                if ba_v - 1 > bb_v:
                    cp_v = state.position.get("VELVETFRUIT_EXTRACT", 0)
                    lim_v = POS_LIMIT.get("VELVETFRUIT_EXTRACT", 0)
                    existing_v = result.get("VELVETFRUIT_EXTRACT", [])
                    existing_sell_v = sum(-o.quantity for o in existing_v if o.quantity < 0)
                    room = max(lim_v + cp_v - existing_sell_v, 0)
                    qty = min(15, room)
                    if qty > 0:
                        result["VELVETFRUIT_EXTRACT"] = list(existing_v) + [Order("VELVETFRUIT_EXTRACT", ba_v - 1, -qty)]

        # n22: Mark 67 prophet on VELV. 95.4% H=1 hit rate. Follow direction with
        # passive priority quote — bid bb+1 on their buy, ask ba-1 on their sell.
        m67_buy = any(t.buyer == "Mark 67" for t in v_trades)
        m67_sell = any(t.seller == "Mark 67" for t in v_trades)
        if m67_buy or m67_sell:
            depth_v = state.order_depths.get("VELVETFRUIT_EXTRACT")
            if depth_v and depth_v.buy_orders and depth_v.sell_orders:
                bb_v = max(depth_v.buy_orders)
                ba_v = min(depth_v.sell_orders)
                cp_v = state.position.get("VELVETFRUIT_EXTRACT", 0)
                lim_v = POS_LIMIT.get("VELVETFRUIT_EXTRACT", 0)
                existing_v = result.get("VELVETFRUIT_EXTRACT", [])
                existing_buy_v = sum(o.quantity for o in existing_v if o.quantity > 0)
                existing_sell_v = sum(-o.quantity for o in existing_v if o.quantity < 0)
                add: List[Order] = []
                if m67_buy and bb_v + 1 < ba_v:
                    room = max(lim_v - cp_v - existing_buy_v, 0)
                    qty = min(15, room)
                    if qty > 0:
                        add.append(Order("VELVETFRUIT_EXTRACT", bb_v + 1, qty))
                if m67_sell and ba_v - 1 > bb_v:
                    room = max(lim_v + cp_v - existing_sell_v, 0)
                    qty = min(15, room)
                    if qty > 0:
                        add.append(Order("VELVETFRUIT_EXTRACT", ba_v - 1, -qty))
                if add:
                    result["VELVETFRUIT_EXTRACT"] = list(existing_v) + add

        # n41: add Mark 14 SELL → bid bb+1 (mirror of n14b's BUY → ask).
        # Mark 14 sells VELV at ask (he's a maker selling to aggressive buyers like
        # Mark 55 / Mark 67). After his sell, recovery flow comes from sellers, our bid
        # at bb+1 catches the next bid-side flow.
        if any(t.seller == "Mark 14" for t in v_trades):
            depth_v = state.order_depths.get("VELVETFRUIT_EXTRACT")
            if depth_v and depth_v.buy_orders and depth_v.sell_orders:
                bb_v = max(depth_v.buy_orders)
                ba_v = min(depth_v.sell_orders)
                if bb_v + 1 < ba_v:
                    cp_v = state.position.get("VELVETFRUIT_EXTRACT", 0)
                    lim_v = POS_LIMIT.get("VELVETFRUIT_EXTRACT", 0)
                    existing_v = result.get("VELVETFRUIT_EXTRACT", [])
                    existing_buy_v = sum(o.quantity for o in existing_v if o.quantity > 0)
                    room = max(lim_v - cp_v - existing_buy_v, 0)
                    qty = min(15, room)
                    if qty > 0:
                        result["VELVETFRUIT_EXTRACT"] = list(existing_v) + [Order("VELVETFRUIT_EXTRACT", bb_v + 1, qty)]


        # nM67voucher: extend Mark 67 prophet to vouchers (positive-delta strikes).
        if m67_buy or m67_sell:
            for K_v in (5000, 5100, 5200, 5300, 5400):
                sym_v = f"VEV_{K_v}"
                d_k = state.order_depths.get(sym_v)
                if not d_k or not d_k.buy_orders or not d_k.sell_orders:
                    continue
                bb_k = max(d_k.buy_orders); ba_k = min(d_k.sell_orders)
                if bb_k + 1 >= ba_k: continue
                cp_k = state.position.get(sym_v, 0)
                lim_k = POS_LIMIT.get(sym_v, 0)
                ex = result.get(sym_v, [])
                ex_buy = sum(o.quantity for o in ex if o.quantity > 0)
                ex_sell = sum(-o.quantity for o in ex if o.quantity < 0)
                extra = []
                if m67_buy:
                    room = max(lim_k - cp_k - ex_buy, 0)
                    q = min(15, room)
                    if q > 0: extra.append(Order(sym_v, bb_k + 1, q))
                if m67_sell:
                    room = max(lim_k + cp_k - ex_sell, 0)
                    q = min(15, room)
                    if q > 0: extra.append(Order(sym_v, ba_k - 1, -q))
                if extra:
                    result[sym_v] = list(ex) + extra


        # nV_sticky: keep voucher cross-bias active for 10 ticks after Mark 67.
        # Currently the m67_buy/sell only fires on the tick of the trade — extend with state.
        if any(t.buyer == "Mark 67" for t in v_trades):
            s.m67_stick = 75
        if s.m67_stick > 0:
            s.m67_stick -= 1
            for K_vs in (5000, 5100, 5200, 5300, 5400):
                sym_vs = f"VEV_{K_vs}"
                d_vs = state.order_depths.get(sym_vs)
                if not d_vs or not d_vs.buy_orders or not d_vs.sell_orders:
                    continue
                bb_vs = max(d_vs.buy_orders); ba_vs = min(d_vs.sell_orders)
                if bb_vs + 1 >= ba_vs: continue
                cp_vs = state.position.get(sym_vs, 0)
                lim_vs = POS_LIMIT.get(sym_vs, 0)
                ex_vs = result.get(sym_vs, [])
                ex_b_vs = sum(o.quantity for o in ex_vs if o.quantity > 0)
                room_vs = max(lim_vs - cp_vs - ex_b_vs, 0)
                q_vs = min(50, room_vs)
                if q_vs > 0:
                    result[sym_vs] = list(ex_vs) + [Order(sym_vs, bb_vs + 1, q_vs)]

        # nN15: late-day BUY wind-down. In last 1000 ticks (s.tick > 9000),
        # scale all voucher BUY orders by 0.3.
        if s.tick > 9500:
            LATE_BUY_SCALE = 0.0
            for sym_l in list(result.keys()):
                if not sym_l.startswith("VEV_"):
                    continue
                scaled_l: List[Order] = []
                for o_l in result[sym_l]:
                    if o_l.quantity > 0:
                        q_l = int(o_l.quantity * LATE_BUY_SCALE)
                        if q_l > 0:
                            scaled_l.append(Order(sym_l, o_l.price, q_l))
                    else:
                        scaled_l.append(o_l)
                result[sym_l] = scaled_l

        # nN33: imb-conditional skip on vouchers (5000-5400). Compute per-strike imb,
        # filter out the wrong-side orders.
        for K_n33 in (5000, 5100, 5200, 5300, 5400):
            sym_n33 = f"VEV_{K_n33}"
            d_n33 = state.order_depths.get(sym_n33)
            if not d_n33 or not d_n33.buy_orders or not d_n33.sell_orders: continue
            bb_n33 = max(d_n33.buy_orders); ba_n33 = min(d_n33.sell_orders)
            bbv_n33 = d_n33.buy_orders[bb_n33]; bav_n33 = -d_n33.sell_orders[ba_n33]
            denom_n33 = bbv_n33 + bav_n33
            if denom_n33 <= 0: continue
            imb_n33 = bbv_n33 / denom_n33
            if imb_n33 >= 0.75:
                # forward UP — drop ASKS
                if sym_n33 in result:
                    result[sym_n33] = [o for o in result[sym_n33] if o.quantity > 0]
            elif imb_n33 <= 0.25:
                # forward DOWN — drop BIDS
                if sym_n33 in result:
                    result[sym_n33] = [o for o in result[sym_n33] if o.quantity < 0]

        # nP1: scale BUY size on strikes where sell-flow dominates.
        # Threshold: total flow ≥ 3, sell-pct ≥ 0.75 → buy_scale 0.5.
        # Symmetric: buy-pct ≥ 0.75 → sell_scale 0.5.
        for sym in list(result.keys()):
            if not sym.startswith("VEV_"):
                continue
            ab = s.agg_buy.get(sym, 0.0)
            asl = s.agg_sell.get(sym, 0.0)
            tot = ab + asl
            if tot < 3.0:
                continue
            sell_pct = asl / tot
            buy_scale = 0.3 if sell_pct >= 0.5 else 1.0
            sell_scale = 0.3 if (1.0 - sell_pct) >= 0.5 else 1.0
            if buy_scale == 1.0 and sell_scale == 1.0:
                continue
            scaled: List[Order] = []
            for o in result[sym]:
                if o.quantity > 0 and buy_scale < 1.0:
                    q = int(o.quantity * buy_scale)
                    if q > 0:
                        scaled.append(Order(sym, o.price, q))
                elif o.quantity < 0 and sell_scale < 1.0:
                    q = int(-o.quantity * sell_scale)
                    if q > 0:
                        scaled.append(Order(sym, o.price, -q))
                else:
                    scaled.append(o)
            result[sym] = scaled

        trader_data = s.to_json()
        return result, 0, trader_data