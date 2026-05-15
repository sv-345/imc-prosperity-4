"""Parametric clone of 127989 Trader for strategy sweeps.

Identical behavior to submissions/127989/127989.py when defaults used.
Construct with `make_trader(osm=..., pep=...)` where the dicts override any
of the tunable parameters.

Tunable params (with 127989 defaults shown):
  osm = dict(
      quote_edge=12,         # spread from FV for resting quote
      min_inside_qty=15,     # size to put at penny-jump when inside edge
      fv=10000,              # stable FV
      limit=80,
  )
  pep = dict(
      accumulate_threshold=70,  # pos < this → accumulate; else hold+MM
      buy_above_fv=8,           # max ask price above FV to accumulate at
      default_sell_qty=8,       # sell qty with no insider signal
      insider_sell_qty=15,      # sell qty when insider just sold (aggressive)
      cooldown_up=20,           # ticks of no-sell after insider BOUGHT
      cooldown_down=-10,        # ticks of aggressive-sell after insider SOLD
      insider_qty=8,            # market-trade qty that identifies insider
      limit=80,
  )
"""
from __future__ import annotations
import json
from dataclasses import dataclass
from typing import Any

try:
    from datamodel import Order
except ImportError:
    @dataclass
    class Order:
        symbol: str
        price: int
        quantity: int


OSM_DEFAULTS = dict(
    quote_edge=12,
    min_inside_qty=15,
    fv=10000,
    limit=80,
    # Optional asymmetric overrides (None → fall back to quote_edge / min_inside_qty)
    buy_edge=None,
    sell_edge=None,
    buy_min_inside=None,
    sell_min_inside=None,
    # Position-skewing: tighten the reducing side by this many ticks per unit position.
    skew_per_pos=0.0,
    skew_cap=6,
    # Adaptive edge: when the opposing side of the book is empty, widen the edge.
    # Intuition: our deep quote is the only liquidity, so we can charge more.
    onesided_edge_bonus=0,  # extra ticks added to edge when opposing side empty
    # Sweep mispriced: default strictly past FV. Include orders at FV too?
    sweep_at_fv=False,  # True → include asks==fv and bids==fv in sweep
    # Use wall-estimated FV (worst_bid + worst_ask)/2 when 10 ≤ wall_spread ≤ 30
    use_wall_fv=False,
    # When wall_fv not available, use EMA of recent wall_fvs for stability
    # (0 = disabled; otherwise alpha for EMA in [0, 1])
    wall_fv_ema_alpha=0.0,
    # Mid-based FV fallback: when wall unavailable, use (bb+ba)/2 instead of static
    mid_fallback_fv=False,
    # Multi-level sell: place additional sell orders at deeper prices.
    # E.g., extra_sell_levels=[(qty, extra_edge), ...] adds sells at fv+sell_edge+extra_edge
    extra_sell_levels=None,  # list of (qty, extra_edge) tuples, or None
    extra_buy_levels=None,
    # Wall-detection range
    wall_spread_lo=10,
    wall_spread_hi=30,
)

PEP_DEFAULTS = dict(
    accumulate_threshold=70,
    buy_above_fv=8,
    default_sell_qty=8,
    insider_sell_qty=15,
    cooldown_up=20,
    cooldown_down=-10,
    insider_qty=8,
    limit=80,
    sweep_bids_above_fv=False,  # sell into bids > fv (symmetric to ask sweep)
    sweep_above_fv_buffer=0,    # only sweep bids at price > fv + buffer
    sell_offset=1,  # post sell at max(ba - sell_offset, fv + 1)
    bid_offset=1,   # post bid at min(bb + bid_offset, fv - 1) during hold
    accumulate_bid_offset=1,    # bid at bb + this during accumulate
)


def make_trader(osm: dict | None = None, pep: dict | None = None):
    """Return a Trader instance parametrized by osm/pep dicts."""
    o = {**OSM_DEFAULTS, **(osm or {})}
    p = {**PEP_DEFAULTS, **(pep or {})}

    class Trader:
        def __init__(self):
            self._last_fv: dict = {}

        @staticmethod
        def _bb(d):
            return max(d.buy_orders) if d.buy_orders else None

        @staticmethod
        def _ba(d):
            return min(d.sell_orders) if d.sell_orders else None

        @staticmethod
        def _estimate_fv_wall(d, lo=10, hi=30):
            if not d.buy_orders or not d.sell_orders:
                return None
            worst_bid = min(d.buy_orders.keys())
            worst_ask = max(d.sell_orders.keys())
            wall_spread = worst_ask - worst_bid
            if wall_spread < lo or wall_spread > hi:
                return None
            return (worst_bid + worst_ask) // 2

        def _trade_osm(self, product, d, pos):
            fv = o["fv"]
            if o["use_wall_fv"]:
                wf = self._estimate_fv_wall(d, o["wall_spread_lo"], o["wall_spread_hi"])
                ema = o["wall_fv_ema_alpha"]
                prev = self._last_fv.get("osm_wall_ema")
                if wf is not None:
                    if ema > 0 and prev is not None:
                        wf = ema * wf + (1 - ema) * prev
                    self._last_fv["osm_wall_ema"] = wf
                    fv = wf
                elif o["mid_fallback_fv"]:
                    bb_ = self._bb(d); ba_ = self._ba(d)
                    if bb_ is not None and ba_ is not None:
                        fv = (bb_ + ba_) / 2
                elif prev is not None:
                    fv = prev
            lim = o["limit"]
            base_edge = o["quote_edge"]
            buy_edge = o["buy_edge"] if o["buy_edge"] is not None else base_edge
            sell_edge = o["sell_edge"] if o["sell_edge"] is not None else base_edge
            base_min = o["min_inside_qty"]
            buy_min = o["buy_min_inside"] if o["buy_min_inside"] is not None else base_min
            sell_min = o["sell_min_inside"] if o["sell_min_inside"] is not None else base_min

            # Position skewing: when long, tighten sell (reduce inventory) / loosen buy.
            # When short, the reverse. Capped at skew_cap ticks.
            skew = o["skew_per_pos"]
            if skew:
                cap = o["skew_cap"]
                adj = max(-cap, min(cap, int(round(skew * pos))))
                sell_edge = max(1, sell_edge - adj)  # long → tighter sell
                buy_edge = max(1, buy_edge + adj)    # long → looser buy

            opos = pos
            orders = []

            # Sweep mispriced
            saf = o["sweep_at_fv"]
            for ap in sorted(d.sell_orders):
                if ap > fv or (ap == fv and not saf):
                    break
                fill = min(-d.sell_orders[ap], lim - pos)
                if fill > 0:
                    orders.append(Order(product, ap, fill))
                    pos += fill
            for bp in sorted(d.buy_orders, reverse=True):
                if bp < fv or (bp == fv and not saf):
                    break
                fill = min(d.buy_orders[bp], lim + pos)
                if fill > 0:
                    orders.append(Order(product, bp, -fill))
                    pos -= fill

            buy_sweep = max(0, pos - opos)
            sell_sweep = max(0, opos - pos)
            buy_cap = max(0, lim - opos - buy_sweep)
            sell_cap = max(0, lim + opos - sell_sweep)

            bb = self._bb(d)
            ba = self._ba(d)

            bonus = o["onesided_edge_bonus"]
            if bb is not None and ba is not None:
                bid_pj = min(bb + 1, fv - 1)
                ask_pj = max(ba - 1, fv + 1)
                bid_ep = fv - buy_edge
                ask_ep = fv + sell_edge

                if bid_pj <= bid_ep:
                    if buy_cap > 0:
                        orders.append(Order(product, bid_ep, buy_cap))
                else:
                    bpj = min(buy_min, buy_cap)
                    be = buy_cap - bpj
                    if be > 0:
                        orders.append(Order(product, bid_ep, be))
                    if bpj > 0:
                        orders.append(Order(product, bid_pj, bpj))

                if ask_pj >= ask_ep:
                    if sell_cap > 0:
                        orders.append(Order(product, ask_ep, -sell_cap))
                else:
                    spj = min(sell_min, sell_cap)
                    se = sell_cap - spj
                    if se > 0:
                        orders.append(Order(product, ask_ep, -se))
                    if spj > 0:
                        orders.append(Order(product, ask_pj, -spj))
            else:
                # One-sided book: apply onesided_edge_bonus. If asks=[] (no bot asks),
                # our sell is the only one → widen sell. If bids=[], widen buy.
                be = buy_edge + (bonus if bb is None else 0)
                se = sell_edge + (bonus if ba is None else 0)
                if buy_cap > 0:
                    orders.append(Order(product, fv - be, buy_cap))
                if sell_cap > 0:
                    orders.append(Order(product, fv + se, -sell_cap))

            # Optional: extra levels (above/below main quotes)
            esl = o["extra_sell_levels"]
            if esl and sell_cap > 0:
                for qty, extra in esl:
                    if qty <= 0:
                        continue
                    orders.append(Order(product, int(fv + sell_edge + extra), -qty))
            ebl = o["extra_buy_levels"]
            if ebl and buy_cap > 0:
                for qty, extra in ebl:
                    if qty <= 0:
                        continue
                    orders.append(Order(product, int(fv - buy_edge - extra), qty))

            return orders

        def _trade_pep(self, product, d, pos, market_trades):
            lim = p["limit"]
            bb = self._bb(d)
            ba = self._ba(d)

            insider_cooldown = self._last_fv.get('pep_insider_cd', 0)

            if bb is not None and ba is not None:
                mid = (bb + ba) / 2
                for t in market_trades:
                    if t.quantity == p["insider_qty"]:
                        if t.price > mid:
                            insider_cooldown = p["cooldown_up"]
                        else:
                            insider_cooldown = p["cooldown_down"]

            if insider_cooldown > 0:
                insider_cooldown -= 1
            elif insider_cooldown < 0:
                insider_cooldown += 1
            self._last_fv['pep_insider_cd'] = insider_cooldown

            fv = (
                self._estimate_fv_wall(d)
                if (bb is not None and ba is not None)
                else None
            )
            if fv is not None:
                self._last_fv[product] = fv
            elif product in self._last_fv:
                fv = self._last_fv[product]
            if fv is None:
                return []

            orders = []
            # Sweep asks below FV
            for ap in sorted(d.sell_orders):
                if ap >= fv:
                    break
                fill = min(-d.sell_orders[ap], lim - pos)
                if fill > 0:
                    orders.append(Order(product, ap, fill))
                    pos += fill

            # Optional symmetric sweep: bids above fv + buffer
            if p.get("sweep_bids_above_fv"):
                buf = p.get("sweep_above_fv_buffer", 0)
                for bp in sorted(d.buy_orders, reverse=True):
                    if bp <= fv + buf:
                        break
                    fill = min(d.buy_orders[bp], lim + pos)
                    if fill > 0:
                        orders.append(Order(product, bp, -fill))
                        pos -= fill

            if pos < p["accumulate_threshold"]:
                buy_limit = fv + p["buy_above_fv"]
                for ap in sorted(d.sell_orders):
                    if ap > buy_limit or ap < fv:
                        continue
                    fill = min(-d.sell_orders[ap], lim - pos)
                    if fill > 0:
                        orders.append(Order(product, ap, fill))
                        pos += fill
                    if pos >= lim:
                        break
                remaining = lim - pos
                if remaining > 0 and bb is not None:
                    orders.append(Order(product, bb + p["accumulate_bid_offset"], remaining))
            else:
                buy_cap = lim - pos
                if buy_cap > 0 and bb is not None:
                    bid_price = min(bb + p["bid_offset"], fv - 1)
                    orders.append(Order(product, bid_price, buy_cap))

                if insider_cooldown > 0:
                    sell_qty = 0
                elif insider_cooldown < 0:
                    sell_qty = min(p["insider_sell_qty"], lim + pos)
                else:
                    sell_qty = min(p["default_sell_qty"], lim + pos)

                if sell_qty > 0 and ba is not None:
                    ask_price = max(ba - p["sell_offset"], fv + 1)
                    orders.append(Order(product, ask_price, -sell_qty))
            return orders

        def run(self, state):
            if state.traderData:
                try:
                    data = json.loads(state.traderData)
                    self._last_fv = data.get("last_fv", {})
                except (json.JSONDecodeError, TypeError):
                    pass

            result = {}
            for product in ("ASH_COATED_OSMIUM", "INTARIAN_PEPPER_ROOT"):
                if product not in state.order_depths:
                    continue
                d = state.order_depths[product]
                pos = state.position.get(product, 0)
                if product == "ASH_COATED_OSMIUM":
                    result[product] = self._trade_osm(product, d, pos)
                else:
                    mt = state.market_trades.get(product, [])
                    result[product] = self._trade_pep(product, d, pos, mt)

            conversions = 0
            trader_data = json.dumps({"last_fv": self._last_fv})
            return result, conversions, trader_data

    return Trader()


if __name__ == "__main__":
    # Sanity: run defaults against 127989's server book and check PnL close
    from server_book_replay import run_server_session
    t = make_trader()
    r = run_server_session(t, "ASH_COATED_OSMIUM", seed=0)
    print(f"OSM seed 0: PnL={r.pnl:.0f}  (127989 seed 0 with same params expected)")
    t = make_trader()
    r = run_server_session(t, "INTARIAN_PEPPER_ROOT", seed=0)
    print(f"PEP seed 0: PnL={r.pnl:.0f}")
