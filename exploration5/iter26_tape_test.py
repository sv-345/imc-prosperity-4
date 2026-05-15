"""iter26_tape_test — iter25_tb1 + OSM event-density trigger.

Purpose: falsifier for the "tape-pinning" hypothesis. See
exploration5/tape_pinning_test_spec.md for full spec and predictions.

Change vs tb1: only adds an EVENT-DENSITY take-side trigger on OSM that
lifts asks in (fv, fv+BAND] when a rolling window of aggressive-bid
events exceeds threshold (mirror for bids in [fv-BAND, fv)).

- Maker layer unchanged.
- PEP logic unchanged.
- Static fv=10001 gate for the primary take loop unchanged.
- iter22 defensive widening unchanged.

Parameters:
  W = 5           rolling window (ticks)
  DENSITY_THRESH = 3   |agg_bid_count - agg_ask_count| threshold over W
  BAND = 2        how far beyond fv the trigger lifts

Fire logging: each fire emits a CSV row to TAPE_TEST_FIRE_LOG env var
if set (append-mode). Format:
  day,timestamp,direction,fills,avg_price,ref_fv
"""

from datamodel import Order, OrderDepth, TradingState
import json
import os


LIMITS = {"ASH_COATED_OSMIUM": 80, "INTARIAN_PEPPER_ROOT": 80}
OSM_FV = 10001
PEP_SLOPE = 0.1

# iter22: defensive bot-take signal
NET_TAKE_THRESH_DEF = 3
ADVERSE_SHRINK = 0.2
ADVERSE_WIDEN = 3

# iter26 tape-test: event-density trigger.
# Original spec: BAND=2. Diagnostic showed 0 fires because OSM book goes one-sided
# during aggressive moments — best_ask is >fv+3 when density UP, best_bid <fv-3 when
# density DN. Widening BAND so the trigger can actually fire; otherwise the test is
# structurally degenerate (see tape_pinning_validated.md / tape_pinning_notes.md).
# Override via env var TAPE_TEST_BAND for sensitivity analysis.
W = 5
DENSITY_THRESH = 3
BAND = int(os.environ.get("TAPE_TEST_BAND", "5"))

_FIRE_LOG = os.environ.get("TAPE_TEST_FIRE_LOG")
_SIGNAL_LOG = os.environ.get("TAPE_TEST_SIGNAL_LOG")
_FIRE_DAY = os.environ.get("TAPE_TEST_DAY", "?")


def _log_fire(ts, direction, fills, avg_price, ref_fv):
    if not _FIRE_LOG:
        return
    try:
        with open(_FIRE_LOG, "a") as f:
            f.write(f"{_FIRE_DAY},{ts},{direction},{fills},{avg_price:.2f},{ref_fv}\n")
    except Exception:
        pass


def _log_signal(ts, signal, ab_sum, aa_sum, best_bid, best_ask):
    if not _SIGNAL_LOG:
        return
    try:
        with open(_SIGNAL_LOG, "a") as f:
            f.write(f"{_FIRE_DAY},{ts},{signal},{ab_sum},{aa_sum},{best_bid},{best_ask}\n")
    except Exception:
        pass


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


def _osm_agg_flags(d):
    """(agg_bid, agg_ask): any bid>=FV / any ask<=FV across all levels."""
    agg_bid = any(p >= OSM_FV for p in d.buy_orders.keys()) if d.buy_orders else False
    agg_ask = any(p <= OSM_FV for p in d.sell_orders.keys()) if d.sell_orders else False
    return agg_bid, agg_ask


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
            inner_bid = p; break
    for p in sorted(d.sell_orders):
        v = -d.sell_orders[p]
        if 8 <= v <= 12:
            inner_ask = p; break
    if inner_bid is not None and inner_ask is not None:
        fv_est = (inner_bid + inner_ask) / 2.0
        intercept = fv_est - PEP_SLOPE * tick
        return round(intercept * 2) / 2
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
    bb = max(d.buy_orders)
    ba = min(d.sell_orders)
    fv_est = (bb + ba) / 2.0
    intercept = fv_est - PEP_SLOPE * tick
    return round(intercept * 2) / 2


class RegimeDetector:
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
        # rolling window of (agg_bid, agg_ask) OSM flags, oldest first, len<=W
        self._den_hist = []

    def bid(self):
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
                sd = json.loads(state.traderData)
                self._pep_intercept = sd.get("pi")
                self._pep_fallback = sd.get("pf", 12000.0)
                self._tick = sd.get("t", 0)
                self._regime.consecutive_deviations = sd.get("rc", 0)
                self._regime.fired = sd.get("rf", False)
                self._den_hist = sd.get("dh", [])
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

        take_sig = {}
        for sym in ("ASH_COATED_OSMIUM", "INTARIAN_PEPPER_ROOT"):
            trades = state.market_trades.get(sym, []) if state.market_trades else []
            if sym in state.order_depths:
                d_ = state.order_depths[sym]
                if d_.buy_orders and d_.sell_orders:
                    take_sig[sym] = net_take_signal(trades, max(d_.buy_orders), min(d_.sell_orders))
                else:
                    take_sig[sym] = 0
            else:
                take_sig[sym] = 0

        osm = "ASH_COATED_OSMIUM"
        density_signal = 0
        if osm in state.order_depths:
            ab, aa = _osm_agg_flags(state.order_depths[osm])
            self._den_hist.append([1 if ab else 0, 1 if aa else 0])
            if len(self._den_hist) > W:
                self._den_hist = self._den_hist[-W:]
            sum_b = sum(x[0] for x in self._den_hist)
            sum_a = sum(x[1] for x in self._den_hist)
            density_signal = sum_b - sum_a
            if abs(density_signal) >= DENSITY_THRESH:
                od = state.order_depths[osm]
                bb_ = max(od.buy_orders) if od.buy_orders else -1
                ba_ = min(od.sell_orders) if od.sell_orders else -1
                _log_signal(state.timestamp, density_signal, sum_b, sum_a, bb_, ba_)

        result = {}

        if osm in state.order_depths:
            result[osm] = self._trade_osmium(
                osm, state.order_depths[osm], state.position.get(osm, 0),
                take_sig.get(osm, 0), density_signal, state.timestamp,
            )

        if pep in state.order_depths:
            result[pep] = self._trade_pepper(
                pep, state.order_depths[pep], state.position.get(pep, 0),
                take_sig.get(pep, 0),
            )

        result, _ = clip_orders(result, state.position)

        td = json.dumps({
            "pi": self._pep_intercept,
            "pf": self._pep_fallback,
            "t": self._tick,
            "rc": self._regime.consecutive_deviations,
            "rf": self._regime.fired,
            "dh": self._den_hist,
        })
        return result, 0, td

    def _trade_osmium(self, product, d, pos, take_sig=0, density_signal=0, ts=0):
        fv = OSM_FV
        orders = []
        opos = pos
        defend_ask = take_sig >= NET_TAKE_THRESH_DEF
        defend_bid = take_sig <= -NET_TAKE_THRESH_DEF

        bb = self._bb(d)
        ba = self._ba(d)

        dynamic_fv = self._inner_mid(d)
        if dynamic_fv is None:
            dynamic_fv = fv

        # Primary fv-gated take loops (unchanged from tb1)
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

        # iter26 tape-test: density-triggered cross into (fv, fv+BAND]
        if density_signal >= DENSITY_THRESH:
            total_fill = 0
            sum_px = 0.0
            for ap in sorted(d.sell_orders):
                if ap <= fv:
                    continue
                if ap > fv + BAND:
                    break
                vol = -d.sell_orders[ap]
                fill = min(vol, 10, LIMITS[product] - pos)
                if fill > 0:
                    orders.append(Order(product, ap, fill))
                    pos += fill
                    total_fill += fill
                    sum_px += ap * fill
            if total_fill > 0:
                _log_fire(ts, "UP", total_fill, sum_px / total_fill, fv)

        elif density_signal <= -DENSITY_THRESH:
            total_fill = 0
            sum_px = 0.0
            for bp in sorted(d.buy_orders, reverse=True):
                if bp >= fv:
                    continue
                if bp < fv - BAND:
                    break
                vol = d.buy_orders[bp]
                fill = min(vol, 10, LIMITS[product] + pos)
                if fill > 0:
                    orders.append(Order(product, bp, -fill))
                    pos -= fill
                    total_fill += fill
                    sum_px += bp * fill
            if total_fill > 0:
                _log_fire(ts, "DN", total_fill, sum_px / total_fill, fv)

        buy_swept = max(0, pos - opos)
        sell_swept = max(0, opos - pos)
        buy_cap = max(0, LIMITS[product] - opos - buy_swept)
        sell_cap = max(0, LIMITS[product] + opos - sell_swept)

        edge = 20
        if bb is not None and ba is not None:
            bid_pj = min(bb + 1, int(dynamic_fv) - 1)
            ask_pj = max(ba - 1, int(dynamic_fv) + 1)
            if defend_ask:
                ask_pj = ask_pj + ADVERSE_WIDEN
                sell_cap = int(round(sell_cap * ADVERSE_SHRINK))
            if defend_bid:
                bid_pj = bid_pj - ADVERSE_WIDEN
                buy_cap = int(round(buy_cap * ADVERSE_SHRINK))
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

    def _trade_pepper(self, product, d, pos, take_sig=0):
        fv_int = int(round(self._pep_fv))
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
