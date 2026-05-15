"""
trader_v82_hardened: v82_best with three hardening layers.

1. Position-limit safety wrapper (clips orders, never silent rejection)
2. PEPPER auto-intercept detection (detects FV start from book structure)
3. PEPPER regime-change detector (detects slope break / trajectory shift)
"""
try:
    from datamodel import Order, OrderDepth, TradingState, Symbol, Trade
except ImportError:
    try:
        from prosperity3bt.datamodel import Order, OrderDepth, TradingState, Symbol, Trade
    except ImportError:
        from dataclasses import dataclass, field
        from typing import Dict, List
        @dataclass
        class Order:
            symbol: str; price: int; quantity: int
        @dataclass
        class OrderDepth:
            buy_orders: Dict[int, int] = field(default_factory=dict)
            sell_orders: Dict[int, int] = field(default_factory=dict)
        @dataclass
        class Trade:
            symbol: str; price: int; quantity: int
            buyer: str = ""; seller: str = ""; timestamp: int = 0
        @dataclass
        class TradingState:
            timestamp: int = 0
            order_depths: Dict[str, "OrderDepth"] = field(default_factory=dict)
            position: Dict[str, int] = field(default_factory=dict)
            own_trades: Dict[str, list] = field(default_factory=dict)
            market_trades: Dict[str, list] = field(default_factory=dict)
            observations: Dict = field(default_factory=dict)
            listings: Dict = field(default_factory=dict)
            traderData: str = ""

import json

class Logger:
    def __init__(self): self.logs = ""
    def print(self, *args, **kwargs): self.logs += " ".join(map(str, args)) + "\n"
    def flush(self, state, orders, conversions, trader_data):
        base_length = len(self.to_json([self.compress_state(state, ""), self.compress_orders(orders), conversions, "", ""]))
        max_item_length = (3750 - base_length) // 3
        print(self.to_json([self.compress_state(state, self.truncate(state.traderData, max_item_length)), self.compress_orders(orders), conversions, self.truncate(trader_data, max_item_length), self.truncate(self.logs, max_item_length)]))
        self.logs = ""
    def compress_state(self, state, trader_data): return [state.timestamp, trader_data, [[l.symbol, l.product, l.denomination] for l in state.listings.values()] if hasattr(state, 'listings') and state.listings else [], {s: [od.buy_orders, od.sell_orders] for s, od in state.order_depths.items()}, [[t.symbol, t.price, t.quantity, t.buyer, t.seller, t.timestamp] for arr in state.own_trades.values() for t in arr], [[t.symbol, t.price, t.quantity, t.buyer, t.seller, t.timestamp] for arr in state.market_trades.values() for t in arr], state.position, [{}, {}]]
    def compress_orders(self, orders): return [[o.symbol, o.price, o.quantity] for arr in orders.values() for o in arr]
    def to_json(self, value): return json.dumps(value, separators=(",", ":"))
    def truncate(self, value, max_length): return value[:max_length - 3] + "..." if len(value) > max_length else value

logger = Logger()

LIMITS = {"ASH_COATED_OSMIUM": 80, "INTARIAN_PEPPER_ROOT": 80}
OSM_FV = 10001
PEP_SLOPE = 0.1  # Known deterministic drift per tick

# ═══════════════════════════════════════════════════════════════════════
# HARDENING LAYER 1: Position-limit safety wrapper
# ═══════════════════════════════════════════════════════════════════════

def clip_orders(orders_by_product, positions):
    """Trim orders to guarantee engine acceptance. Preserves order priority.

    Engine rule per product:
      position + sum(buy_qty)  <= +limit
      position - sum(sell_qty) >= -limit   (sell_qty stored as positive here)

    Walks orders in submission order, trimming the last offending order.
    Returns (clipped_orders, trim_count) so callers can detect latent bugs.
    """
    clipped = {}
    total_trims = 0
    for product, order_list in orders_by_product.items():
        limit = LIMITS.get(product, 80)
        pos = positions.get(product, 0)
        buy_room = limit - pos     # max total buy qty
        sell_room = limit + pos    # max total sell qty (as positive)

        safe = []
        for o in order_list:
            if o.quantity > 0:  # buy
                allowed = min(o.quantity, buy_room)
                if allowed <= 0:
                    total_trims += 1
                    continue
                if allowed < o.quantity:
                    total_trims += 1
                buy_room -= allowed
                safe.append(Order(o.symbol, o.price, allowed))
            elif o.quantity < 0:  # sell
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


# ═══════════════════════════════════════════════════════════════════════
# HARDENING LAYER 2: PEPPER auto-intercept detection
# ═══════════════════════════════════════════════════════════════════════

def detect_pepper_intercept(d, timestamp):
    """Detect PEPPER FV intercept from order book structure.

    PEPPER FV = intercept + slope * tick_index.
    Inner bots quote at round(FV ± FV/2000 ± 0.5).
    At FV~12000: inner offset ≈ ±7, so inner mid ≈ FV.

    Returns estimated intercept, or None if can't determine.
    """
    if not d.buy_orders or not d.sell_orders:
        return None

    tick = timestamp // 100

    # Layer 1: inner midpoint (most precise)
    inner_bid = inner_ask = None
    for p in sorted(d.buy_orders, reverse=True):
        v = d.buy_orders[p]
        if 8 <= v <= 12:
            inner_bid = p; break
    for p in sorted(d.sell_orders):
        v = -d.sell_orders[p]
        if 8 <= v <= 12:
            inner_ask = p; break

    if inner_bid is not None and inner_ask is not None:
        fv_est = (inner_bid + inner_ask) / 2.0
        intercept = fv_est - PEP_SLOPE * tick
        return round(intercept * 2) / 2  # snap to 0.5 grid

    # Layer 2: wall midpoint (coarser)
    wall_bid = wall_ask = None
    for p in sorted(d.buy_orders, reverse=True):
        v = d.buy_orders[p]
        if 15 <= v <= 25:
            wall_bid = p; break
    for p in sorted(d.sell_orders):
        v = -d.sell_orders[p]
        if 15 <= v <= 25:
            wall_ask = p; break

    if wall_bid is not None and wall_ask is not None:
        fv_est = (wall_bid + wall_ask) / 2.0
        intercept = fv_est - PEP_SLOPE * tick
        return round(intercept * 2) / 2

    # Layer 3: raw midpoint
    bb = max(d.buy_orders)
    ba = min(d.sell_orders)
    fv_est = (bb + ba) / 2.0
    intercept = fv_est - PEP_SLOPE * tick
    return round(intercept * 2) / 2


# ═══════════════════════════════════════════════════════════════════════
# HARDENING LAYER 3: PEPPER regime-change detector
# ═══════════════════════════════════════════════════════════════════════

class RegimeDetector:
    """Detects PEPPER trajectory breaks (slope sign flip, jump, etc.)."""

    WARMUP = 50       # Don't arm until this many ticks
    GAP = 15          # Deviation threshold (ticks) — normal noise is ≈ ±7 from inner spread
    CONFIRM = 5       # Consecutive deviations required before firing

    def __init__(self):
        self.consecutive_deviations = 0
        self.fired = False

    def check(self, expected_fv, observed_mid, tick):
        """Returns True if regime change detected."""
        if self.fired:
            return True
        if tick < self.WARMUP:
            return False
        if observed_mid is None:
            self.consecutive_deviations = 0
            return False

        deviation = abs(observed_mid - expected_fv)
        if deviation >= self.GAP:
            self.consecutive_deviations += 1
        else:
            self.consecutive_deviations = 0

        if self.consecutive_deviations >= self.CONFIRM:
            self.fired = True
            return True
        return False


# ═══════════════════════════════════════════════════════════════════════
# TRADER
# ═══════════════════════════════════════════════════════════════════════

class Trader:
    def __init__(self):
        self._pep_intercept = None   # Auto-detected, not hardcoded
        self._pep_fv = None          # Derived from intercept + slope*tick
        self._pep_fallback = 12000.0 # Layer 4 fallback (only if all else fails)
        self._regime = RegimeDetector()
        self._tick = 0

    @staticmethod
    def _bb(d):
        return max(d.buy_orders) if d.buy_orders else None

    @staticmethod
    def _ba(d):
        return min(d.sell_orders) if d.sell_orders else None

    def _inner_mid(self, d):
        ib = ia = None
        for p in sorted(d.buy_orders, reverse=True):
            if 10 <= d.buy_orders[p] <= 15:
                ib = p; break
        for p in sorted(d.sell_orders):
            if 10 <= -d.sell_orders[p] <= 15:
                ia = p; break
        if ib and ia and 15 <= ia - ib <= 17:
            return (ib + ia) / 2.0
        if ib: return ib + 8.0
        if ia: return ia - 8.0
        return None

    def run(self, state):
        if state.traderData:
            try:
                d = json.loads(state.traderData)
                self._pep_intercept = d.get("pi")
                self._pep_fallback = d.get("pf", 12000.0)
                self._tick = d.get("t", 0)
                self._regime.consecutive_deviations = d.get("rc", 0)
                self._regime.fired = d.get("rf", False)
            except:
                pass

        self._tick += 1
        tick_index = state.timestamp // 100

        # ── PEPPER FV: auto-intercept detection ──
        pep = "INTARIAN_PEPPER_ROOT"
        if pep in state.order_depths and self._pep_intercept is None:
            detected = detect_pepper_intercept(state.order_depths[pep], state.timestamp)
            if detected is not None:
                self._pep_intercept = detected

        # Compute PEPPER FV from intercept
        if self._pep_intercept is not None:
            self._pep_fv = self._pep_intercept + PEP_SLOPE * (tick_index + 1)
        else:
            self._pep_fallback += PEP_SLOPE
            self._pep_fv = self._pep_fallback

        # ── Regime detection ──
        if pep in state.order_depths:
            pep_d = state.order_depths[pep]
            observed = None
            bb_p = self._bb(pep_d)
            ba_p = self._ba(pep_d)
            if bb_p is not None and ba_p is not None:
                observed = (bb_p + ba_p) / 2.0
            regime_break = self._regime.check(self._pep_fv, observed, self._tick)
            if regime_break:
                # Re-detect intercept from current book
                new_intercept = detect_pepper_intercept(pep_d, state.timestamp)
                if new_intercept is not None:
                    self._pep_intercept = new_intercept
                    self._pep_fv = self._pep_intercept + PEP_SLOPE * (tick_index + 1)
                    self._regime = RegimeDetector()  # Reset detector

        result = {}

        osm = "ASH_COATED_OSMIUM"
        if osm in state.order_depths:
            result[osm] = self._trade_osmium(
                osm, state.order_depths[osm], state.position.get(osm, 0)
            )

        if pep in state.order_depths:
            result[pep] = self._trade_pepper(
                pep, state.order_depths[pep], state.position.get(pep, 0)
            )

        # ── HARDENING LAYER 1: safety clip ──
        result, trims = clip_orders(result, state.position)

        td = json.dumps({
            "pi": self._pep_intercept,
            "pf": self._pep_fallback,
            "t": self._tick,
            "rc": self._regime.consecutive_deviations,
            "rf": self._regime.fired,
        })
        logger.flush(state, result, 0, td)
        return result, 0, td

    # ── OSMIUM: identical to v82_best ──

    def _trade_osmium(self, product, d, pos):
        fv = OSM_FV
        orders = []
        opos = pos

        bb = self._bb(d)
        ba = self._ba(d)

        dynamic_fv = self._inner_mid(d)
        if dynamic_fv is None:
            dynamic_fv = fv

        for ap in sorted(d.sell_orders):
            if ap >= fv:
                break
            vol = -d.sell_orders[ap]
            real_edge = dynamic_fv - ap
            if vol <= 9 or real_edge >= 2:
                fill = min(vol, LIMITS[product] - pos)
                if fill > 0:
                    orders.append(Order(product, ap, fill))
                    pos += fill

        for bp in sorted(d.buy_orders, reverse=True):
            if bp <= fv:
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

        edge = 20
        if bb is not None and ba is not None:
            bid_pj = min(bb + 1, fv - 1)
            ask_pj = max(ba - 1, fv + 1)
            bid_edge = fv - edge
            ask_edge = fv + edge

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
                orders.append(Order(product, fv - edge, buy_cap))
            if sell_cap > 0:
                orders.append(Order(product, fv + edge, -sell_cap))

        return orders

    # ── PEPPER: uses auto-detected intercept ──

    def _trade_pepper(self, product, d, pos):
        fv_int = int(round(self._pep_fv))
        orders = []
        bb = self._bb(d)
        ba = self._ba(d)
        limit = LIMITS[product]

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
                orders.append(Order(product, min(bb + 1, fv_int - 1), buy_cap))
            sell_qty = min(8, limit + pos)
            if sell_qty > 0:
                ask_price = max(ba - 1, fv_int + 1) if ba else fv_int + 7
                orders.append(Order(product, ask_price, -sell_qty))

        return orders