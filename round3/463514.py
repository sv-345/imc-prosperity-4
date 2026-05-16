"""trader_r3_v86 — wing passive bid (VELVET anchor change reverted).

Diff vs current trader.py:
- Wing voucher (VEV_6000, VEV_6500): add passive bid at price 0.
  Current trader uses VEV_WING_IV={...:0.0}, so theo=0, never buys.
  Anchor_regime_report §3 says wings close at $0.50 (bid=0/ask=1 floor);
  wing_voucher_architecture.md memory says "long at bid=0 carries
  positive expectation almost regardless of underlying realization."
  Buy at price 0 = $0 XIRECs cost. If filled, marked at $0.50+.
  Asymmetric: cannot lose money on entry.

NOTE: VELVET anchor 5250→5258 was tried and reverted. Backtester showed
−$248k regression because the change cascades into voucher-mirror
triggers (lines 408/418): mirror buys fire too early in d0/d1 Q1 where
V trades around 5235-5238, costing ~$126k voucher PnL. The bs_decision
§4.4 eval-window-risk flag was correct.
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
R3_LIVE_TTE_YEARS: float = 5.0 / 365.0

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


class State:
    __slots__ = ("tick", "last_mid", "closed", "velvet_ask_cooldown",
                 "ema_theo_diff", "ema_abs_dev", "velvet_mid_prev")

    def __init__(self) -> None:
        self.tick: int = 0
        self.last_mid: Dict[str, float] = {}
        self.closed: Dict[str, bool] = {}
        # v61: ticks remaining to SKIP VELVET ask after BUY-agg print (A3 finding)
        self.velvet_ask_cooldown: int = 0
        # v85: per-strike EMA of theo_diff (Frankfurt smile scalping)
        self.ema_theo_diff: Dict[str, float] = {}
        self.ema_abs_dev: Dict[str, float] = {}
        # v85k: prev-tick VELVET mid for dS direction predictor
        self.velvet_mid_prev: float = 0.0

    def to_json(self) -> str:
        return json.dumps({
            "tick": self.tick, "last_mid": self.last_mid,
            "closed": self.closed,
            "velvet_ask_cooldown": self.velvet_ask_cooldown,
            "ema_theo_diff": self.ema_theo_diff,
            "ema_abs_dev": self.ema_abs_dev,
            "velvet_mid_prev": self.velvet_mid_prev,
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
    if sb_edge > 0:
        if ba <= anchor - sb_edge and current_pos < budget:
            qty = min(budget - current_pos, 600)
            if qty > 0:
                orders.append(Order(product, ba + 2, qty))
    if ss_edge > 0:
        if bb >= anchor + ss_edge and current_pos > -budget:
            qty = min(budget + current_pos, 600)
            if qty > 0:
                orders.append(Order(product, bb - 2, -qty))

    already_buy = sum(o.quantity for o in orders if o.quantity > 0)
    already_sell = sum(-o.quantity for o in orders if o.quantity < 0)
    # v60 rejected: bb+2/ba-2 on HYDROGEL lost $60. A2's "same fill rate"
    # claim was wrong — bb+2 misses bot-to-bot trades priced at bb+1 that
    # would have stepped into bb+1 quotes. Reverted to bb+1/ba-1.
    # composition: HY MM offset override
    _hy_bid_off = 1  # v125: HY MM revert (also in v113)
    _hy_ask_off = 1 if product == "HYDROGEL_PACK" else 1
    _bid_px = bb + _hy_bid_off
    _ask_px = ba - _hy_ask_off
    if current_pos + already_buy < budget and _bid_px < _ask_px and _bid_px >= 1:
        orders.append(Order(product, _bid_px, min(size, budget - current_pos - already_buy)))
    if current_pos - already_sell > -budget and not skip_velvet_ask and _bid_px < _ask_px and _ask_px >= 1:
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
    # v86: passive bid at price 0. Buy at 0 = $0 cost; if filled, marked at
    # $0.50+ hidden FV. Asymmetric — cannot lose money on entry.
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
        if current_pos + already_buy < budget:
            orders.append(Order(product, bb + 1, min(size, budget - current_pos - already_buy)))
        if current_pos - already_sell > -budget:
            orders.append(Order(product, ba - 1, -min(size, budget + current_pos - already_sell)))
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

        # close_ticks disabled — v58h-style 1k-tuned close fires too early on 10k eval
        # (was: HYDROGEL_PACK=690, VELVETFRUIT_EXTRACT=600 — fires at 6.9%/6% on 10k)
        pass

        underlying_mid = s.last_mid.get("VELVETFRUIT_EXTRACT", FV_ANCHOR["VELVETFRUIT_EXTRACT"])
        result: Dict[str, List[Order]] = {}

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
            if bb_v >= anchor_v + 22:
                velvet_take_sell = True
            elif ba_v <= anchor_v - 22:
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
            if bb_v2 >= anchor_v2 + 18 and bb_v2 < anchor_v2 + 22:
                velvet_tier2_sell = True
            elif ba_v2 <= anchor_v2 - 18 and ba_v2 > anchor_v2 - 22:
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
        VOUCHER_EDGES = VOUCHER_EDGES_TIGHT if tight_surface else VOUCHER_EDGES_WIDE

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


        # v145: voucher inventory throttle on TAKE entries (from v141_invtt)
        INVTT_F = 0.72  # v142 finding: 0.69 better than 0.75 on this base
        voucher_pos_total = 0
        voucher_limit_total = 0
        for prod_name in POS_LIMIT:
            if prod_name.startswith("VEV_"):
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
                    skip_ask = (product == "VELVETFRUIT_EXTRACT" and skip_velvet_ask)
                    orders = delta1_orders(product, depth, current_pos, budget, FV_ANCHOR[product], tight_surface, skip_ask)
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
                        if bb_v_ >= VOUCHER_ANCHOR_SELL[strike] + v_edge:
                            voucher_take_sell = True
                        elif ba_v_ <= VOUCHER_ANCHOR_BUY[strike] - v_edge:
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

        trader_data = s.to_json()
        return result, 0, trader_data