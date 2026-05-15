"""
trader_v100_scratch — fresh design from data stats + winner techniques.

Design anchors (from 127989 session profiling):
  OSMIUM: mean=9999.91 but wall-mid=10001.25 → anchor at 10001
          (FV=10000 loses 24 PnL/seed). Returns phi=-0.49 but phi-bias
          on raw mid adds noise (regresses -58). Skew at K≤0.03 is neutral.
          → Use DRO-optimal: static FV=10001, adaptive edge∈[12,20], mi=15.
  PEPPER: drift=+0.101/tick, trending. Accumulate to 80 then MM sell.
          Qty=8 insider signal (rare but sharp per 127989 logs).

Winner techniques applied:
  1. Wall-mid FV anchor (winner's latent-FV extraction → constant here).
  2. Bot-aware quote ladder: penny-jump inside + wall edge post.
  3. Inventory-integrated capacity (winner's skew → MC shows neutral here,
     retained as soft version with K=0; hook present for future sessions).
  4. Sweep-all-mispriced-levels: free-money crosses.
"""
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
    def _lst(self, l):
        try: return [l['symbol'], l['product'], l['denomination']] if isinstance(l, dict) else [l.symbol, l.product, l.denomination]
        except Exception: return []
    def compress_state(self, state, trader_data): return [state.timestamp, trader_data, [self._lst(l) for l in state.listings.values()] if hasattr(state, 'listings') and state.listings else [], {s: [od.buy_orders, od.sell_orders] for s, od in state.order_depths.items()}, [[t.symbol, t.price, t.quantity, t.buyer, t.seller, t.timestamp] for arr in state.own_trades.values() for t in arr], [[t.symbol, t.price, t.quantity, t.buyer, t.seller, t.timestamp] for arr in state.market_trades.values() for t in arr], state.position, [{}, {}]]
    def compress_orders(self, orders): return [[o.symbol, o.price, o.quantity] for arr in orders.values() for o in arr]
    def to_json(self, value): return json.dumps(value, separators=(",", ":"))
    def truncate(self, value, max_length): return value[:max_length - 3] + "..." if len(value) > max_length else value

logger = Logger()

LIMIT = 80
OSM_FV = 10001          # wall-mid anchor (empirical 10001.25)
OSM_EDGE_MIN = 12       # DRO-optimal floor
OSM_EDGE_MAX = 20       # adaptive cap
OSM_MIN_INSIDE = 15     # penny-jump quote size
OSM_SKEW_K = 0.0        # disabled — MC-neutral on 127989 session

PEP_INITIAL_FV = 12000.0
PEP_DRIFT = 0.10
PEP_INSIDER_QTY = 8     # winner signal (per 127989)


class Trader:
    def __init__(self):
        self._pep_fv = PEP_INITIAL_FV
        self._insider_cd = 0

    @staticmethod
    def _bb(d):
        return max(d.buy_orders) if d.buy_orders else None

    @staticmethod
    def _ba(d):
        return min(d.sell_orders) if d.sell_orders else None

    def _trade_osmium(self, product, d, pos):
        orders: List[Order] = []
        opos = pos
        fv = OSM_FV

        bb = self._bb(d)
        ba = self._ba(d)

        if bb is not None and ba is not None:
            spread = ba - bb
            edge = max(OSM_EDGE_MIN, min(OSM_EDGE_MAX, (spread * 3) // 4))
        else:
            edge = OSM_EDGE_MIN + 2

        # Sweep mispriced asks (< FV)
        for ap in sorted(d.sell_orders):
            if ap >= fv:
                break
            fill = min(-d.sell_orders[ap], LIMIT - pos)
            if fill > 0:
                orders.append(Order(product, ap, fill))
                pos += fill

        # Sweep mispriced bids (> FV)
        for bp in sorted(d.buy_orders, reverse=True):
            if bp <= fv:
                break
            fill = min(d.buy_orders[bp], LIMIT + pos)
            if fill > 0:
                orders.append(Order(product, bp, -fill))
                pos -= fill

        buy_swept = max(0, pos - opos)
        sell_swept = max(0, opos - pos)
        buy_cap = max(0, LIMIT - opos - buy_swept)
        sell_cap = max(0, LIMIT + opos - sell_swept)

        skew = int(round(-pos * OSM_SKEW_K))  # 0 at K=0

        if bb is not None and ba is not None:
            bid_edge = fv - edge + skew
            ask_edge = fv + edge + skew
            bid_pj = min(bb + 1, fv - 1 + skew)
            ask_pj = max(ba - 1, fv + 1 + skew)

            if bid_pj <= bid_edge:
                if buy_cap > 0:
                    orders.append(Order(product, bid_edge, buy_cap))
            else:
                bpj = min(OSM_MIN_INSIDE, buy_cap)
                be = buy_cap - bpj
                if be > 0:
                    orders.append(Order(product, bid_edge, be))
                if bpj > 0:
                    orders.append(Order(product, bid_pj, bpj))

            if ask_pj >= ask_edge:
                if sell_cap > 0:
                    orders.append(Order(product, ask_edge, -sell_cap))
            else:
                spj = min(OSM_MIN_INSIDE, sell_cap)
                se = sell_cap - spj
                if se > 0:
                    orders.append(Order(product, ask_edge, -se))
                if spj > 0:
                    orders.append(Order(product, ask_pj, -spj))
        else:
            if buy_cap > 0:
                orders.append(Order(product, fv - edge + skew, buy_cap))
            if sell_cap > 0:
                orders.append(Order(product, fv + edge + skew, -sell_cap))

        return orders

    def _pep_fv_from_book(self, d):
        """Wall-mid FV: outermost bid/ask midpoint (stable anchor)."""
        if not d.buy_orders or not d.sell_orders:
            return None
        wb = min(d.buy_orders)
        wa = max(d.sell_orders)
        spread = wa - wb
        if spread < 10 or spread > 30:
            return None
        return (wb + wa) / 2.0

    def _trade_pepper(self, product, d, pos, market_trades):
        orders: List[Order] = []
        bb = self._bb(d)
        ba = self._ba(d)

        if bb is not None and ba is not None:
            mid = (bb + ba) / 2
            for t in market_trades:
                if t.quantity == PEP_INSIDER_QTY:
                    if t.price > mid:
                        self._insider_cd = 20
                    else:
                        self._insider_cd = -10

        if self._insider_cd > 0:
            self._insider_cd -= 1
        elif self._insider_cd < 0:
            self._insider_cd += 1

        wm = self._pep_fv_from_book(d)
        if wm is not None:
            self._pep_fv = wm
        else:
            self._pep_fv += PEP_DRIFT

        fv_int = int(round(self._pep_fv))

        for ap in sorted(d.sell_orders):
            if ap >= fv_int:
                break
            fill = min(-d.sell_orders[ap], LIMIT - pos)
            if fill > 0:
                orders.append(Order(product, ap, fill))
                pos += fill

        if pos < 70:
            buy_limit = fv_int + 8
            for ap in sorted(d.sell_orders):
                if ap > buy_limit or ap < fv_int:
                    continue
                fill = min(-d.sell_orders[ap], LIMIT - pos)
                if fill > 0:
                    orders.append(Order(product, ap, fill))
                    pos += fill
                if pos >= LIMIT:
                    break
            rem = LIMIT - pos
            if rem > 0 and bb is not None:
                orders.append(Order(product, bb + 1, rem))
        else:
            buy_cap = LIMIT - pos
            if buy_cap > 0 and bb is not None:
                bid_price = min(bb + 1, fv_int - 1)
                orders.append(Order(product, bid_price, buy_cap))

            if self._insider_cd > 0:
                sell_qty = 0
            elif self._insider_cd < 0:
                sell_qty = min(15, LIMIT + pos)
            else:
                sell_qty = min(8, LIMIT + pos)

            if sell_qty > 0:
                if ba is not None:
                    ask_price = max(ba - 1, fv_int + 1)
                else:
                    ask_price = fv_int + 7
                orders.append(Order(product, ask_price, -sell_qty))

        return orders

    def run(self, state):
        if state.traderData:
            try:
                data = json.loads(state.traderData)
                self._pep_fv = data.get("pfv", PEP_INITIAL_FV)
                self._insider_cd = data.get("icd", 0)
            except Exception:
                pass

        result = {}
        osm = "ASH_COATED_OSMIUM"
        if osm in state.order_depths:
            d = state.order_depths[osm]
            pos = state.position.get(osm, 0)
            result[osm] = self._trade_osmium(osm, d, pos)

        pep = "INTARIAN_PEPPER_ROOT"
        if pep in state.order_depths:
            d = state.order_depths[pep]
            pos = state.position.get(pep, 0)
            mt = state.market_trades.get(pep, [])
            result[pep] = self._trade_pepper(pep, d, pos, mt)

        trader_data = json.dumps({
            "pfv": self._pep_fv,
            "icd": self._insider_cd,
        })
        logger.flush(state, result, 0, trader_data)
        return result, 0, trader_data
