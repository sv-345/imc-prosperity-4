"""Candidate trader variants for robust improvements over 127989.

All share the same shell (Logger, datamodel, PRODUCTS) — only the
_trade_stable (OSMIUM) and _trade_trending (PEPPER) methods differ.

Parameters are constructor args; each variant is a factory.
"""
from __future__ import annotations
import json
from dataclasses import dataclass, field
from typing import Dict, List


# Import from training_replay's datamodel (or shim)
try:
    from datamodel import Order, OrderDepth, TradingState, Trade
except ImportError:
    try:
        from prosperity3bt.datamodel import Order, OrderDepth, TradingState, Trade
    except ImportError:
        @dataclass
        class Order:
            symbol: str
            price: int
            quantity: int

        @dataclass
        class OrderDepth:
            buy_orders: Dict[int, int] = field(default_factory=dict)
            sell_orders: Dict[int, int] = field(default_factory=dict)

        @dataclass
        class Trade:
            symbol: str
            price: int
            quantity: int
            buyer: str = ""
            seller: str = ""
            timestamp: int = 0

        @dataclass
        class TradingState:
            timestamp: int = 0
            order_depths: Dict[str, OrderDepth] = field(default_factory=dict)
            position: Dict[str, int] = field(default_factory=dict)
            own_trades: Dict = field(default_factory=dict)
            market_trades: Dict[str, list] = field(default_factory=dict)
            observations: Dict = field(default_factory=dict)
            listings: Dict = field(default_factory=dict)
            traderData: str = ""


def _bb(d): return max(d.buy_orders) if d.buy_orders else None
def _ba(d): return min(d.sell_orders) if d.sell_orders else None


# ---------------- OSMIUM variants -----------------------------------------

def osmium_stable(fv=10000, edge=12, min_inside=15, limit=80,
                  use_eq_sweep=False):
    """Baseline stable (matches 127989). use_eq_sweep=True: sweep asks at price <= fv (not <)."""
    def fn(d, pos):
        opos = pos
        orders = []
        # Sweep mispriced asks
        for ap in sorted(d.sell_orders):
            cond = (ap <= fv) if use_eq_sweep else (ap < fv)
            if not cond:
                break
            fill = min(-d.sell_orders[ap], limit - pos)
            if fill > 0:
                orders.append(Order("ASH_COATED_OSMIUM", ap, fill))
                pos += fill
        # Sweep mispriced bids
        for bp in sorted(d.buy_orders, reverse=True):
            cond = (bp >= fv) if use_eq_sweep else (bp > fv)
            if not cond:
                break
            fill = min(d.buy_orders[bp], limit + pos)
            if fill > 0:
                orders.append(Order("ASH_COATED_OSMIUM", bp, -fill))
                pos -= fill

        buy_sweep = max(0, pos - opos)
        sell_sweep = max(0, opos - pos)
        buy_cap = max(0, limit - opos - buy_sweep)
        sell_cap = max(0, limit + opos - sell_sweep)
        bb = _bb(d); ba = _ba(d)

        if bb is not None and ba is not None:
            bid_pj = min(bb + 1, fv - 1)
            ask_pj = max(ba - 1, fv + 1)
            bid_ep = fv - edge
            ask_ep = fv + edge

            if bid_pj <= bid_ep:
                if buy_cap > 0:
                    orders.append(Order("ASH_COATED_OSMIUM", bid_ep, buy_cap))
            else:
                bpj = min(min_inside, buy_cap)
                be = buy_cap - bpj
                if be > 0:
                    orders.append(Order("ASH_COATED_OSMIUM", bid_ep, be))
                if bpj > 0:
                    orders.append(Order("ASH_COATED_OSMIUM", bid_pj, bpj))

            if ask_pj >= ask_ep:
                if sell_cap > 0:
                    orders.append(Order("ASH_COATED_OSMIUM", ask_ep, -sell_cap))
            else:
                spj = min(min_inside, sell_cap)
                se = sell_cap - spj
                if se > 0:
                    orders.append(Order("ASH_COATED_OSMIUM", ask_ep, -se))
                if spj > 0:
                    orders.append(Order("ASH_COATED_OSMIUM", ask_pj, -spj))
        else:
            if buy_cap > 0:
                orders.append(Order("ASH_COATED_OSMIUM", fv - edge, buy_cap))
            if sell_cap > 0:
                orders.append(Order("ASH_COATED_OSMIUM", fv + edge, -sell_cap))
        return orders
    return fn


# ---------------- PEPPER variants ------------------------------------------

def _estimate_pepper_fv(d, wall_offset=None):
    if not d.buy_orders or not d.sell_orders:
        return None
    worst_bid = min(d.buy_orders.keys())
    worst_ask = max(d.sell_orders.keys())
    if wall_offset is None:
        wall_spread = worst_ask - worst_bid
        if wall_spread < 10 or wall_spread > 30:
            return None
        return (worst_bid + worst_ask) // 2
    fv_bid = worst_bid + wall_offset
    fv_ask = worst_ask - wall_offset
    if abs(fv_bid - fv_ask) <= 1:
        return (fv_bid + fv_ask) // 2
    return None


def _estimate_osmium_fv(d):
    """OSMIUM: infer fv from walls at fv±10. Returns None if unclear."""
    if not d.buy_orders or not d.sell_orders:
        return None
    worst_bid = min(d.buy_orders.keys())
    worst_ask = max(d.sell_orders.keys())
    # Walls are at floor(fv)-10 and ceil(fv)+10; midpoint ≈ fv
    mid = (worst_bid + worst_ask) / 2
    # Sanity check: width should be ~20-22
    if 18 <= (worst_ask - worst_bid) <= 24:
        return mid
    return None


def osmium_dynamic(fallback_fv=10000, edge=12, min_inside=15, limit=80):
    """OSMIUM with FV estimated from walls each tick (fallback to fixed 10000)."""
    def fn(d, pos):
        est = _estimate_osmium_fv(d)
        fv = round(est) if est is not None else fallback_fv
        return osmium_stable(fv=fv, edge=edge, min_inside=min_inside, limit=limit)(d, pos)
    return fn


def osmium_multilevel(fv=10000, edge=12, min_inside=15, limit=80, pj_layers=(0, 1)):
    """OSMIUM with multi-level penny-jumps at (bb+1+k) and (ba-1-k) for k in pj_layers.
    Each layer gets min_inside // len(pj_layers) units.
    """
    def fn(d, pos):
        opos = pos
        orders = []
        for ap in sorted(d.sell_orders):
            if ap >= fv: break
            fill = min(-d.sell_orders[ap], limit - pos)
            if fill > 0:
                orders.append(Order("ASH_COATED_OSMIUM", ap, fill))
                pos += fill
        for bp in sorted(d.buy_orders, reverse=True):
            if bp <= fv: break
            fill = min(d.buy_orders[bp], limit + pos)
            if fill > 0:
                orders.append(Order("ASH_COATED_OSMIUM", bp, -fill))
                pos -= fill
        buy_sweep = max(0, pos - opos)
        sell_sweep = max(0, opos - pos)
        buy_cap = max(0, limit - opos - buy_sweep)
        sell_cap = max(0, limit + opos - sell_sweep)
        bb = _bb(d); ba = _ba(d)

        if bb is None or ba is None:
            if buy_cap > 0:
                orders.append(Order("ASH_COATED_OSMIUM", fv - edge, buy_cap))
            if sell_cap > 0:
                orders.append(Order("ASH_COATED_OSMIUM", fv + edge, -sell_cap))
            return orders

        bid_ep = fv - edge
        ask_ep = fv + edge
        layer_size = min_inside // max(1, len(pj_layers))

        # Multi-level PJ on bid side
        for k in pj_layers:
            price = min(bb + 1 + k, fv - 1 - k)
            if price <= bid_ep: break  # can't nest inside edge
            qty = min(layer_size, buy_cap)
            if qty > 0:
                orders.append(Order("ASH_COATED_OSMIUM", price, qty))
                buy_cap -= qty
        if buy_cap > 0:
            orders.append(Order("ASH_COATED_OSMIUM", bid_ep, buy_cap))

        # Multi-level PJ on ask side
        for k in pj_layers:
            price = max(ba - 1 - k, fv + 1 + k)
            if price >= ask_ep: break
            qty = min(layer_size, sell_cap)
            if qty > 0:
                orders.append(Order("ASH_COATED_OSMIUM", price, -qty))
                sell_cap -= qty
        if sell_cap > 0:
            orders.append(Order("ASH_COATED_OSMIUM", ask_ep, -sell_cap))
        return orders
    return fn


def osmium_wall_aware(fallback_fv=10000, edge=12, min_inside=15, limit=80,
                       inside_wall=1):
    """Like dynamic but quote_ep is priced RELATIVE TO WALL (inside_wall ticks
    inside the wall bot) rather than relative to fv. More robust to FV drift.

    If walls absent, fall back to fixed-FV logic with fallback_fv.
    """
    def fn(d, pos):
        opos = pos
        orders = []
        if not d.buy_orders or not d.sell_orders:
            return []
        worst_bid = min(d.buy_orders.keys())
        worst_ask = max(d.sell_orders.keys())
        # Is there a valid wall? Width should be ~20-22
        have_wall = 18 <= (worst_ask - worst_bid) <= 24
        if have_wall:
            fv = (worst_bid + worst_ask) / 2
            bid_ep = worst_bid + inside_wall
            ask_ep = worst_ask - inside_wall
        else:
            fv = fallback_fv
            bid_ep = fv - edge
            ask_ep = fv + edge
        # Sweep
        for ap in sorted(d.sell_orders):
            if ap >= fv: break
            fill = min(-d.sell_orders[ap], limit - pos)
            if fill > 0:
                orders.append(Order("ASH_COATED_OSMIUM", ap, fill))
                pos += fill
        for bp in sorted(d.buy_orders, reverse=True):
            if bp <= fv: break
            fill = min(d.buy_orders[bp], limit + pos)
            if fill > 0:
                orders.append(Order("ASH_COATED_OSMIUM", bp, -fill))
                pos -= fill
        buy_sweep = max(0, pos - opos)
        sell_sweep = max(0, opos - pos)
        buy_cap = max(0, limit - opos - buy_sweep)
        sell_cap = max(0, limit + opos - sell_sweep)
        bb = _bb(d); ba = _ba(d)
        if bb is None or ba is None:
            return orders
        # PJ inside bb/ba, capped at bid_ep/ask_ep
        bid_pj = min(bb + 1, int(fv - 1))
        ask_pj = max(ba - 1, int(fv + 1))
        if bid_pj <= bid_ep:
            if buy_cap > 0:
                orders.append(Order("ASH_COATED_OSMIUM", int(bid_ep), buy_cap))
        else:
            bpj = min(min_inside, buy_cap)
            be = buy_cap - bpj
            if be > 0:
                orders.append(Order("ASH_COATED_OSMIUM", int(bid_ep), be))
            if bpj > 0:
                orders.append(Order("ASH_COATED_OSMIUM", bid_pj, bpj))
        if ask_pj >= ask_ep:
            if sell_cap > 0:
                orders.append(Order("ASH_COATED_OSMIUM", int(ask_ep), -sell_cap))
        else:
            spj = min(min_inside, sell_cap)
            se = sell_cap - spj
            if se > 0:
                orders.append(Order("ASH_COATED_OSMIUM", int(ask_ep), -se))
            if spj > 0:
                orders.append(Order("ASH_COATED_OSMIUM", ask_pj, -spj))
        return orders
    return fn


def osmium_asym(fv=10000, bid_edge=12, ask_edge=12, min_inside=15, limit=80):
    """OSMIUM with different edges on bid vs ask side."""
    def fn(d, pos):
        opos = pos
        orders = []
        for ap in sorted(d.sell_orders):
            if ap >= fv: break
            fill = min(-d.sell_orders[ap], limit - pos)
            if fill > 0:
                orders.append(Order("ASH_COATED_OSMIUM", ap, fill))
                pos += fill
        for bp in sorted(d.buy_orders, reverse=True):
            if bp <= fv: break
            fill = min(d.buy_orders[bp], limit + pos)
            if fill > 0:
                orders.append(Order("ASH_COATED_OSMIUM", bp, -fill))
                pos -= fill
        buy_sweep = max(0, pos - opos)
        sell_sweep = max(0, opos - pos)
        buy_cap = max(0, limit - opos - buy_sweep)
        sell_cap = max(0, limit + opos - sell_sweep)
        bb = _bb(d); ba = _ba(d)
        if bb is None or ba is None:
            if buy_cap > 0:
                orders.append(Order("ASH_COATED_OSMIUM", fv - bid_edge, buy_cap))
            if sell_cap > 0:
                orders.append(Order("ASH_COATED_OSMIUM", fv + ask_edge, -sell_cap))
            return orders
        bid_pj = min(bb + 1, fv - 1)
        ask_pj = max(ba - 1, fv + 1)
        bid_ep = fv - bid_edge
        ask_ep = fv + ask_edge
        # Bid
        if bid_pj <= bid_ep:
            if buy_cap > 0:
                orders.append(Order("ASH_COATED_OSMIUM", bid_ep, buy_cap))
        else:
            bpj = min(min_inside, buy_cap)
            be = buy_cap - bpj
            if be > 0:
                orders.append(Order("ASH_COATED_OSMIUM", bid_ep, be))
            if bpj > 0:
                orders.append(Order("ASH_COATED_OSMIUM", bid_pj, bpj))
        # Ask
        if ask_pj >= ask_ep:
            if sell_cap > 0:
                orders.append(Order("ASH_COATED_OSMIUM", ask_ep, -sell_cap))
        else:
            spj = min(min_inside, sell_cap)
            se = sell_cap - spj
            if se > 0:
                orders.append(Order("ASH_COATED_OSMIUM", ask_ep, -se))
            if spj > 0:
                orders.append(Order("ASH_COATED_OSMIUM", ask_pj, -spj))
        return orders
    return fn


def pepper_trending(limit=80,
                    insider_qty=8,
                    insider_buy_cooldown=20,
                    insider_sell_cooldown=-10,
                    default_sell_qty=8,
                    bullish_sell_qty=0,
                    bearish_sell_qty=15,
                    accum_thresh=70,
                    buy_limit_offset=8,
                    aggro_take_on_insider_buy=False,
                    aggro_buy_size=40):
    """Parameterized PEPPER trending strategy.

    Key knobs for robustness tests:
      insider_sell_cooldown: set to 0 to disable bearish response (data shows
                             insider sells aren't predictive past ~20 ticks)
      bearish_sell_qty:      set to 8 (default) to treat insider sell as neutral
      insider_buy_cooldown:  longer = hold longer after insider buy
    """
    # Persistent state kept in closure
    state = {"insider_cd": 0, "last_fv": None}

    def fn(d, pos, market_trades, state_ref=state):
        bb = _bb(d); ba = _ba(d)

        cd = state_ref["insider_cd"]
        insider_buy_fired = False
        if bb is not None and ba is not None:
            mid = (bb + ba) / 2
            for t in market_trades:
                if t.quantity == insider_qty:
                    if t.price > mid:
                        cd = insider_buy_cooldown
                        insider_buy_fired = True
                    else:
                        cd = insider_sell_cooldown
        # Decay
        if cd > 0: cd -= 1
        elif cd < 0: cd += 1
        state_ref["insider_cd"] = cd

        fv = _estimate_pepper_fv(d)
        if fv is not None:
            state_ref["last_fv"] = fv
        elif state_ref["last_fv"] is not None:
            fv = state_ref["last_fv"]
        if fv is None:
            return []

        orders = []
        # Free sweep below FV
        for ap in sorted(d.sell_orders):
            if ap >= fv: break
            fill = min(-d.sell_orders[ap], limit - pos)
            if fill > 0:
                orders.append(Order("INTARIAN_PEPPER_ROOT", ap, fill))
                pos += fill

        # Aggressive take on insider-buy signal (lift offers up to aggro_buy_size)
        if aggro_take_on_insider_buy and insider_buy_fired and pos < limit:
            want = min(aggro_buy_size, limit - pos)
            for ap in sorted(d.sell_orders):
                if want <= 0: break
                fill = min(-d.sell_orders[ap], want)
                if fill > 0:
                    orders.append(Order("INTARIAN_PEPPER_ROOT", ap, fill))
                    pos += fill
                    want -= fill

        if pos < accum_thresh:
            # ACCUMULATE
            buy_limit = fv + buy_limit_offset
            for ap in sorted(d.sell_orders):
                if ap > buy_limit or ap < fv: continue
                fill = min(-d.sell_orders[ap], limit - pos)
                if fill > 0:
                    orders.append(Order("INTARIAN_PEPPER_ROOT", ap, fill))
                    pos += fill
                if pos >= limit: break
            rem = limit - pos
            if rem > 0 and bb is not None:
                orders.append(Order("INTARIAN_PEPPER_ROOT", bb + 1, rem))
        else:
            # HOLD + MM with insider-aware sell sizing
            buy_cap = limit - pos
            if buy_cap > 0 and bb is not None:
                bid_price = min(bb + 1, fv - 1)
                orders.append(Order("INTARIAN_PEPPER_ROOT", bid_price, buy_cap))

            if cd > 0:
                sq = bullish_sell_qty  # don't sell, insider bought
            elif cd < 0:
                sq = bearish_sell_qty
            else:
                sq = default_sell_qty
            sq = min(sq, limit + pos)
            if sq > 0 and ba is not None:
                ask_price = max(ba - 1, fv + 1)
                orders.append(Order("INTARIAN_PEPPER_ROOT", ask_price, -sq))
        return orders
    return fn


# ---------------- Full Trader wrapper --------------------------------------

class ParametricTrader:
    def __init__(self, osmium_fn, pepper_fn):
        self.osmium_fn = osmium_fn
        self.pepper_fn = pepper_fn
        self._last_fv = {}

    def run(self, state):
        if state.traderData:
            try:
                data = json.loads(state.traderData)
                self._last_fv = data.get("last_fv", {})
            except Exception:
                pass

        result = {}
        for product, d in state.order_depths.items():
            pos = state.position.get(product, 0)
            if product == "ASH_COATED_OSMIUM":
                result[product] = self.osmium_fn(d, pos)
            elif product == "INTARIAN_PEPPER_ROOT":
                mt = state.market_trades.get(product, [])
                result[product] = self.pepper_fn(d, pos, mt)
            else:
                result[product] = []
        return result, 0, json.dumps({"last_fv": self._last_fv})


# ---------------- Variant registry -----------------------------------------

def variants():
    """Return {name: (osmium_fn_factory, pepper_fn_factory)}.
    Each value is a tuple of zero-arg callables that produce the leg fn."""
    osm = {
        "osm_base":     lambda: osmium_stable(edge=12, min_inside=15),
        "osm_dynfv_e14": lambda: osmium_dynamic(edge=14),
        "osm_wall_i1":  lambda: osmium_wall_aware(inside_wall=1),
        "osm_wall_i1_mi30": lambda: osmium_wall_aware(inside_wall=1, min_inside=30),
        "osm_wall_i1_mi8": lambda: osmium_wall_aware(inside_wall=1, min_inside=8),
        "osm_wall_i1_mi25": lambda: osmium_wall_aware(inside_wall=1, min_inside=25),
        "osm_wall_i1_mi50": lambda: osmium_wall_aware(inside_wall=1, min_inside=50),
    }
    pep = {
        "pep_base":     lambda: pepper_trending(),  # 127989 defaults
        "pep_nobear":   lambda: pepper_trending(insider_sell_cooldown=0, bearish_sell_qty=8),
        "pep_longcd":   lambda: pepper_trending(insider_buy_cooldown=50),
        "pep_aggro":    lambda: pepper_trending(aggro_take_on_insider_buy=True, aggro_buy_size=40),
        "pep_aggro_big": lambda: pepper_trending(aggro_take_on_insider_buy=True, aggro_buy_size=80),
        "pep_aggro_longcd": lambda: pepper_trending(aggro_take_on_insider_buy=True,
                                                     aggro_buy_size=40,
                                                     insider_buy_cooldown=50),
    }
    return osm, pep
