"""Iter 13 — iter12 + R1 CF3: tighten OSM take condition.

R1 post-mortem (docs/round1_postmortem/counterfactuals.md#CF3) identified 140
OSM crosses with `markout+50 ≤ +5` — weak takes that drained spread. These
came through the `vol ≤ 9` branch (small-size bot asks without strong edge).
R1 CF3 proposed tightening to require edge ≥ 2 OR (vol ≤ 4 AND edge ≥ 1),
estimated +$1-2k hindsight recovery on 10k ticks.

Change from iter12: drop the `vol ≤ 9` pure-volume trigger — require edge ≥ 2
for any cross. Slightly more conservative than R1's full CF3 proposal
(simpler single condition). Scales to ~+$100-200 on R2's 1000-tick slice.

Not expected to close full $3.5k gap to 13k — this is a small evidence-backed
improvement on top of iter12. Gap needs a separate bigger lever.

Original iter12 docstring:
---
Direct port of R1 v82_hardened (submission 273632).

The iter10 OSM strategy is missing three structures that v82 had in R1:

1. Aggressive cross-the-book take on ANY ask below fv when `vol ≤ 9 OR
   real_edge ≥ 2` (mirror for bids). R1 fired this 251 times for ~$18.5 k
   net-of-crosses markout on 50-tick forward.
2. Wide-snipe layer at fv±20 — catches big breakout crosses that pierce
   the inner MM.
3. Dual passive quoting at `min(bb+1, fv-1)` inside AND `fv±20` outside
   simultaneously. My iter10 only has a single inner-inside layer.

v82 also uses auto-intercept detection for PEP (derives fv intercept
from the book without hardcoding day_start), a regime-change detector
that resets the intercept on slope breaks, and a recycle-when-long
branch (sells 8 at ba-1 when pos ≥ 70). All three are absent from iter10.

This port preserves the R1 logic verbatim — only the import line and
the Logger are stripped (community reports logger.flush slows lambdas,
and it's not needed on server). LIMITS, OSM_FV=10001, PEP_SLOPE=0.1 all
match R2 calibration (docs/round2_model.md).

Expected: PEP similar to iter10 (~$7.4 k), OSM materially higher from
the three missing structures. Target $9–10 k total as a baseline; further
tuning beyond v82 is iter13+ work.
"""

from datamodel import Order, OrderDepth, TradingState
import json


LIMITS = {"ASH_COATED_OSMIUM": 80, "INTARIAN_PEPPER_ROOT": 80}
OSM_FV = 10001
PEP_SLOPE = 0.1


def clip_orders(orders_by_product, positions):
    """Trim orders to guarantee engine acceptance. Preserves order priority."""
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
    """Detect PEPPER FV intercept from order book structure."""
    if not d.buy_orders or not d.sell_orders:
        return None

    tick = timestamp // 100

    # Layer 1: inner midpoint
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
        return round(intercept * 2) / 2

    # Layer 2: wall midpoint
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


class RegimeDetector:
    """Detects PEPPER trajectory breaks (slope sign flip, jump, etc.)."""
    WARMUP = 50
    GAP = 15
    CONFIRM = 5

    def __init__(self):
        self.consecutive_deviations = 0
        self.fired = False

    def check(self, expected_fv, observed_mid, tick):
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


class Trader:
    def __init__(self):
        self._pep_intercept = None
        self._pep_fv = None
        self._pep_fallback = 12000.0
        self._regime = RegimeDetector()
        self._tick = 0

    def bid(self):
        # MAF bid — irrelevant for testing; only applies to final round.
        return 15

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
            except Exception:
                pass

        self._tick += 1
        tick_index = state.timestamp // 100

        pep = "INTARIAN_PEPPER_ROOT"
        if pep in state.order_depths and self._pep_intercept is None:
            detected = detect_pepper_intercept(state.order_depths[pep], state.timestamp)
            if detected is not None:
                self._pep_intercept = detected

        if self._pep_intercept is not None:
            self._pep_fv = self._pep_intercept + PEP_SLOPE * (tick_index + 1)
        else:
            self._pep_fallback += PEP_SLOPE
            self._pep_fv = self._pep_fallback

        if pep in state.order_depths:
            pep_d = state.order_depths[pep]
            observed = None
            bb_p = self._bb(pep_d)
            ba_p = self._ba(pep_d)
            if bb_p is not None and ba_p is not None:
                observed = (bb_p + ba_p) / 2.0
            regime_break = self._regime.check(self._pep_fv, observed, self._tick)
            if regime_break:
                new_intercept = detect_pepper_intercept(pep_d, state.timestamp)
                if new_intercept is not None:
                    self._pep_intercept = new_intercept
                    self._pep_fv = self._pep_intercept + PEP_SLOPE * (tick_index + 1)
                    self._regime = RegimeDetector()

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

        result, _ = clip_orders(result, state.position)

        td = json.dumps({
            "pi": self._pep_intercept,
            "pf": self._pep_fallback,
            "t": self._tick,
            "rc": self._regime.consecutive_deviations,
            "rf": self._regime.fired,
        })
        return result, 0, td

    def _trade_osmium(self, product, d, pos):
        fv = OSM_FV
        orders = []
        opos = pos

        bb = self._bb(d)
        ba = self._ba(d)

        dynamic_fv = self._inner_mid(d)
        if dynamic_fv is None:
            dynamic_fv = fv

        # iter13: R1 CF3 — drop `vol ≤ 9` trigger; require edge ≥ 2 for all takes.
        for ap in sorted(d.sell_orders):
            if ap >= fv:
                break
            vol = -d.sell_orders[ap]
            real_edge = dynamic_fv - ap
            if real_edge >= 2:
                fill = min(vol, LIMITS[product] - pos)
                if fill > 0:
                    orders.append(Order(product, ap, fill))
                    pos += fill

        for bp in sorted(d.buy_orders, reverse=True):
            if bp <= fv:
                break
            vol = d.buy_orders[bp]
            real_edge = bp - dynamic_fv
            if real_edge >= 2:
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

    def _trade_pepper(self, product, d, pos):
        fv_int = int(round(self._pep_fv))
        orders = []
        bb = self._bb(d)
        ba = self._ba(d)
        limit = LIMITS[product]

        # Take any ask below fv_int (rare mispricing)
        for ap in sorted(d.sell_orders):
            if ap >= fv_int:
                break
            fill = min(-d.sell_orders[ap], limit - pos)
            if fill > 0:
                orders.append(Order(product, ap, fill))
                pos += fill

        if pos < 70:
            # Fast accumulate: buy through all asks up to fv_int + 6
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
            # Recycle: buy any remaining capacity inside bb, sell 8 at ba-1
            buy_cap = limit - pos
            if buy_cap > 0 and bb is not None:
                orders.append(Order(product, min(bb + 1, fv_int - 1), buy_cap))
            sell_qty = min(8, limit + pos)
            if sell_qty > 0:
                ask_price = max(ba - 1, fv_int + 1) if ba else fv_int + 7
                orders.append(Order(product, ask_price, -sell_qty))

        return orders
