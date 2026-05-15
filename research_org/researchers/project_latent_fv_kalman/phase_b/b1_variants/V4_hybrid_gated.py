"""V4 — Hybrid confidence-gated Kalman.

Use Kalman posterior FV for OSM take/quote decisions ONLY when the
filter has converged (P below a threshold). Otherwise fall back to
iter23's static ``OSM_FV = 10001`` constant.

Convergence threshold: ``P <= P_inf * (1 + V4_TOL)`` where P_inf is
the analytical steady-state. With V4_TOL = 0.5, the filter is
considered converged when P ≤ 1.5 * P_inf ≈ 0.64. Per phase_a
validation, OSM P converges to within 5% of P_inf within ~20 ticks
from cold-start, and within 1% within ~50 ticks. So this gate
activates by tick ~20 and remains active thereafter.

PEP uses V1-style full Kalman FV in the converged regime; else falls
back to the iter23 ``detect_pepper_intercept`` heuristic. PEP's
convergence threshold is ``PEP_P_INF * (1 + V4_TOL)``.

Research-only variant. NOT a server submission.
"""

from datamodel import Order, OrderDepth, TradingState
import json

from _kalman_core import (  # type: ignore
    LatentFVKalman,
    OSM_P_INF,
    PEP_P_INF,
    PEP_SLOPE as _PEP_SLOPE,
)

LIMITS = {"ASH_COATED_OSMIUM": 80, "INTARIAN_PEPPER_ROOT": 80}
PEP_SLOPE = _PEP_SLOPE

NET_TAKE_THRESH_DEF = 3
ADVERSE_SHRINK = 0.2
ADVERSE_WIDEN = 3

OSM_FV_CONST = 10001
V4_TOL = 0.5
V4_OSM_CONVERGED = OSM_P_INF * (1.0 + V4_TOL)
V4_PEP_CONVERGED = PEP_P_INF * (1.0 + V4_TOL)


def net_take_signal(market_trades_list, bp1, ap1):
    net = 0
    for t in market_trades_list:
        buyer = getattr(t, "buyer", "") or ""
        seller = getattr(t, "seller", "") or ""
        if "SUBMISSION" in buyer or "SUBMISSION" in seller:
            continue
        price = float(getattr(t, "price", 0))
        qty = int(getattr(t, "quantity", 0))
        if price >= ap1:
            net += qty
        elif price <= bp1:
            net -= qty
    return net


def clip_orders(orders_by_product, positions):
    clipped = {}
    total_trims = 0
    for product, order_list in orders_by_product.items():
        limit = LIMITS.get(product, 80)
        pos = positions.get(product, 0)
        buy_room = limit - pos
        sell_room = limit + pos
        safe = []
        for o in order_list:
            if o.quantity > 0:
                allowed = min(o.quantity, buy_room)
                if allowed <= 0:
                    total_trims += 1
                    continue
                if allowed < o.quantity:
                    total_trims += 1
                buy_room -= allowed
                safe.append(Order(o.symbol, o.price, allowed))
            elif o.quantity < 0:
                wanted = -o.quantity
                allowed = min(wanted, sell_room)
                if allowed <= 0:
                    total_trims += 1
                    continue
                if allowed < wanted:
                    total_trims += 1
                sell_room -= allowed
                safe.append(Order(o.symbol, o.price, -allowed))
        clipped[product] = safe
    return clipped, total_trims


def detect_pepper_intercept(d, timestamp):
    if not d.buy_orders or not d.sell_orders:
        return None
    tick = timestamp // 100
    inner_bid = inner_ask = None
    for p in sorted(d.buy_orders, reverse=True):
        v = d.buy_orders[p]
        if 8 <= v <= 12:
            inner_bid = p
            break
    for p in sorted(d.sell_orders):
        v = -d.sell_orders[p]
        if 8 <= v <= 12:
            inner_ask = p
            break
    if inner_bid is not None and inner_ask is not None:
        fv_est = (inner_bid + inner_ask) / 2.0
        intercept = fv_est - PEP_SLOPE * tick
        return round(intercept * 2) / 2
    wall_bid = wall_ask = None
    for p in sorted(d.buy_orders, reverse=True):
        v = d.buy_orders[p]
        if 15 <= v <= 25:
            wall_bid = p
            break
    for p in sorted(d.sell_orders):
        v = -d.sell_orders[p]
        if 15 <= v <= 25:
            wall_ask = p
            break
    if wall_bid is not None and wall_ask is not None:
        fv_est = (wall_bid + wall_ask) / 2.0
        intercept = fv_est - PEP_SLOPE * tick
        return round(intercept * 2) / 2
    bb = max(d.buy_orders)
    ba = min(d.sell_orders)
    fv_est = (bb + ba) / 2.0
    intercept = fv_est - PEP_SLOPE * tick
    return round(intercept * 2) / 2


def _inner_mid_osm(d):
    ib = ia = None
    for p in sorted(d.buy_orders, reverse=True):
        if 10 <= d.buy_orders[p] <= 15:
            ib = p
            break
    for p in sorted(d.sell_orders):
        if 10 <= -d.sell_orders[p] <= 15:
            ia = p
            break
    if ib and ia and 15 <= ia - ib <= 17:
        return (ib + ia) / 2.0
    if ib:
        return ib + 8.0
    if ia:
        return ia - 8.0
    return None


def _inner_mid_pep(d):
    bids = sorted(d.buy_orders, reverse=True)
    asks = sorted(d.sell_orders)
    ib = ia = None
    for p in bids:
        if 8 <= d.buy_orders[p] <= 12:
            ib = p
            break
    for p in asks:
        if 8 <= -d.sell_orders[p] <= 12:
            ia = p
            break
    if ib is not None and ia is not None:
        return (ib + ia) / 2.0
    if bids and asks:
        return (bids[0] + asks[0]) / 2.0
    return None


class Trader:
    def __init__(self):
        self._kf_osm = None
        self._kf_pep = None
        self._pep_intercept = None
        self._pep_fv = None
        self._pep_fallback = 12000.0
        self._tick = 0

    def bid(self):
        return 15

    @staticmethod
    def _bb(d):
        return max(d.buy_orders) if d.buy_orders else None

    @staticmethod
    def _ba(d):
        return min(d.sell_orders) if d.sell_orders else None

    def _restore(self, trader_data):
        if not trader_data:
            return
        try:
            d = json.loads(trader_data)
        except Exception:
            return
        osm = d.get("kf_osm")
        if osm:
            self._kf_osm = LatentFVKalman(
                Q=0.145, R_base=1.68, P0=max(osm["P"], 1e-6),
                x0=osm["x"], tick0=osm["t"],
            )
            self._kf_osm.n_updates = osm.get("n", 0)
        pep = d.get("kf_pep")
        if pep:
            self._kf_pep = LatentFVKalman(
                Q=0.040, R_base=1.61, P0=max(pep["P"], 1e-6),
                x0=pep["x"], mu=pep["mu"], slope=PEP_SLOPE, tick0=pep["t"],
            )
            self._kf_pep.n_updates = pep.get("n", 0)
        self._pep_intercept = d.get("pi")
        self._pep_fallback = d.get("pf", 12000.0)
        self._tick = d.get("t", 0)

    def _dump(self):
        out = {
            "pi": self._pep_intercept, "pf": self._pep_fallback, "t": self._tick,
        }
        if self._kf_osm is not None:
            out["kf_osm"] = {
                "x": self._kf_osm.x, "P": self._kf_osm.P,
                "t": self._kf_osm.tick, "n": self._kf_osm.n_updates,
            }
        if self._kf_pep is not None:
            out["kf_pep"] = {
                "x": self._kf_pep.x, "P": self._kf_pep.P,
                "t": self._kf_pep.tick, "mu": self._kf_pep.mu,
                "n": self._kf_pep.n_updates,
            }
        return json.dumps(out)

    def run(self, state: TradingState):
        self._restore(state.traderData or "")
        self._tick += 1
        tick_index = state.timestamp // 100

        osm = "ASH_COATED_OSMIUM"
        pep = "INTARIAN_PEPPER_ROOT"

        osm_fv = osm_P = None
        if osm in state.order_depths:
            d_ = state.order_depths[osm]
            y = _inner_mid_osm(d_)
            one_sided = (not d_.buy_orders) or (not d_.sell_orders)
            if y is not None and self._kf_osm is None:
                self._kf_osm = LatentFVKalman.cold_osm()
                self._kf_osm.x = y  # seed from first observation
                self._kf_osm.tick = tick_index - 1
            if self._kf_osm is not None:
                self._kf_osm.update(y, one_sided=one_sided)
                osm_fv = self._kf_osm.fv()
                osm_P = self._kf_osm.P

        # PEP keeps heuristic seed, but we also run the Kalman silently
        # so we can switch to it once P converges.
        if pep in state.order_depths and self._pep_intercept is None:
            detected = detect_pepper_intercept(state.order_depths[pep], state.timestamp)
            if detected is not None:
                self._pep_intercept = detected
        if self._pep_intercept is not None:
            pep_heuristic_fv = self._pep_intercept + PEP_SLOPE * (tick_index + 1)
        else:
            self._pep_fallback += PEP_SLOPE
            pep_heuristic_fv = self._pep_fallback

        pep_fv_final = pep_heuristic_fv
        pep_P = None
        if pep in state.order_depths:
            d_ = state.order_depths[pep]
            y = _inner_mid_pep(d_)
            one_sided = (not d_.buy_orders) or (not d_.sell_orders)
            if y is not None and self._kf_pep is None:
                mu = y - PEP_SLOPE * tick_index
                self._kf_pep = LatentFVKalman.cold_pep(mu=mu, tick0=tick_index - 1)
            if self._kf_pep is not None:
                self._kf_pep.update(y, one_sided=one_sided)
                pep_P = self._kf_pep.P
                # V4 gate: only use Kalman FV if converged
                if pep_P <= V4_PEP_CONVERGED:
                    pep_fv_final = self._kf_pep.fv()
        self._pep_fv = pep_fv_final

        # OSM fv for trading: gated
        osm_fv_final = OSM_FV_CONST
        if osm_fv is not None and osm_P is not None and osm_P <= V4_OSM_CONVERGED:
            osm_fv_final = osm_fv

        take_sig = {}
        for sym in (osm, pep):
            trades = state.market_trades.get(sym, []) if state.market_trades else []
            if sym in state.order_depths:
                d_ = state.order_depths[sym]
                if d_.buy_orders and d_.sell_orders:
                    take_sig[sym] = net_take_signal(
                        trades, max(d_.buy_orders), min(d_.sell_orders)
                    )
                else:
                    take_sig[sym] = 0
            else:
                take_sig[sym] = 0

        result = {}
        if osm in state.order_depths:
            result[osm] = self._trade_osmium(
                osm, state.order_depths[osm], state.position.get(osm, 0),
                take_sig.get(osm, 0), osm_fv_final,
            )
        if pep in state.order_depths:
            result[pep] = self._trade_pepper(
                pep, state.order_depths[pep], state.position.get(pep, 0),
                take_sig.get(pep, 0), pep_fv_final,
            )

        result, _ = clip_orders(result, state.position)
        return result, 0, self._dump()

    def _trade_osmium(self, product, d, pos, take_sig, fv_float):
        orders = []
        opos = pos
        defend_ask = take_sig >= NET_TAKE_THRESH_DEF
        defend_bid = take_sig <= -NET_TAKE_THRESH_DEF
        bb = self._bb(d)
        ba = self._ba(d)
        dynamic_fv = _inner_mid_osm(d) or fv_float

        for ap in sorted(d.sell_orders):
            if ap >= fv_float:
                break
            vol = -d.sell_orders[ap]
            real_edge = dynamic_fv - ap
            if vol <= 9 or real_edge >= 2:
                fill = min(vol, LIMITS[product] - pos)
                if fill > 0:
                    orders.append(Order(product, ap, fill))
                    pos += fill

        for bp in sorted(d.buy_orders, reverse=True):
            if bp <= fv_float:
                break
            vol = d.buy_orders[bp]
            real_edge = bp - dynamic_fv
            if vol <= 9 or real_edge >= 2:
                fill = min(vol, LIMITS[product] + pos)
                if fill > 0:
                    orders.append(Order(product, bp, -fill))
                    pos -= fill

        buy_swept = max(0, pos - opos)
        sell_swept = max(0, opos - pos)
        buy_cap = max(0, LIMITS[product] - opos - buy_swept)
        sell_cap = max(0, LIMITS[product] + opos - sell_swept)

        fv_int = int(round(fv_float))
        edge = 20
        if bb is not None and ba is not None:
            bid_pj = min(bb + 1, fv_int - 1)
            ask_pj = max(ba - 1, fv_int + 1)
            if defend_ask:
                ask_pj = ask_pj + ADVERSE_WIDEN
                sell_cap = int(round(sell_cap * ADVERSE_SHRINK))
            if defend_bid:
                bid_pj = bid_pj - ADVERSE_WIDEN
                buy_cap = int(round(buy_cap * ADVERSE_SHRINK))
            bid_edge = fv_int - edge
            ask_edge = fv_int + edge
            mi = 15
            if bid_pj <= bid_edge:
                if buy_cap > 0:
                    orders.append(Order(product, bid_edge, buy_cap))
            else:
                bpj = min(mi, buy_cap)
                be = buy_cap - bpj
                if be > 0:
                    orders.append(Order(product, bid_edge, be))
                if bpj > 0:
                    orders.append(Order(product, bid_pj, bpj))
            if ask_pj >= ask_edge:
                if sell_cap > 0:
                    orders.append(Order(product, ask_edge, -sell_cap))
            else:
                spj = min(mi, sell_cap)
                se = sell_cap - spj
                if se > 0:
                    orders.append(Order(product, ask_edge, -se))
                if spj > 0:
                    orders.append(Order(product, ask_pj, -spj))
        else:
            if buy_cap > 0:
                orders.append(Order(product, fv_int - edge, buy_cap))
            if sell_cap > 0:
                orders.append(Order(product, fv_int + edge, -sell_cap))
        return orders

    def _trade_pepper(self, product, d, pos, take_sig, pep_fv_float):
        fv_int = int(round(pep_fv_float))
        orders = []
        bb = self._bb(d)
        ba = self._ba(d)
        limit = LIMITS[product]
        defend_ask = take_sig >= NET_TAKE_THRESH_DEF
        defend_bid = take_sig <= -NET_TAKE_THRESH_DEF

        for ap in sorted(d.sell_orders):
            if ap >= fv_int:
                break
            fill = min(-d.sell_orders[ap], limit - pos)
            if fill > 0:
                orders.append(Order(product, ap, fill))
                pos += fill

        if pos < 70:
            buy_limit = fv_int + 6
            for ap in sorted(d.sell_orders):
                if ap > buy_limit or ap < fv_int:
                    continue
                fill = min(-d.sell_orders[ap], limit - pos)
                if fill > 0:
                    orders.append(Order(product, ap, fill))
                    pos += fill
                if pos >= limit:
                    break
            remaining = limit - pos
            if remaining > 0 and bb is not None:
                orders.append(Order(product, bb + 1, remaining))
        else:
            buy_cap = limit - pos
            if buy_cap > 0 and bb is not None:
                bid_price = min(bb + 1, fv_int - 1)
                if defend_bid:
                    bid_price -= ADVERSE_WIDEN
                    buy_cap = int(round(buy_cap * ADVERSE_SHRINK))
                if buy_cap > 0:
                    orders.append(Order(product, bid_price, buy_cap))
            if take_sig >= NET_TAKE_THRESH_DEF:
                base_sell = 0
            elif take_sig <= -NET_TAKE_THRESH_DEF:
                base_sell = 15
            else:
                base_sell = 8
            sell_qty = min(base_sell, limit + pos)
            if sell_qty > 0:
                ask_price = max(ba - 1, fv_int + 1) if ba else fv_int + 7
                orders.append(Order(product, ask_price, -sell_qty))
        return orders
