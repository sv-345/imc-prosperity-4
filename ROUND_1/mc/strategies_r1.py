"""Port of the best-submission R1 strategies (v14 / submission 127989)
adapted to MC v1's TickContext/OrderIntent interface.

Strategies:
  * osmium_stable_edge10(ctx) — known fv=10000, sweep mispriced + penny-jump at edge 10
  * pepper_trending(ctx)       — drift-aware accumulate-then-hold with penny-jump

The MC must provide:
  - ctx.fv                 current (true) fv
  - ctx.book               current book state (bid/ask levels with bot+strat volume)
  - ctx.position           current strategy position
  - ctx.position_limit     e.g., 80
"""

from __future__ import annotations
from typing import List, Tuple

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from mc_r1_v1 import OrderIntent, TickContext


def _best_bid(ctx: TickContext):
    lv = ctx.book.best_bid()
    return lv.price if lv else None


def _best_ask(ctx: TickContext):
    lv = ctx.book.best_ask()
    return lv.price if lv else None


def _sweep_asks_below(ctx: TickContext, fv: float, lim: int) -> Tuple[List[Tuple[int, int]], int]:
    """Buy any ask at price < fv. Return (bid_orders, new_position)."""
    orders = []
    pos = ctx.position
    for lv in ctx.book.ask_levels_sorted():
        if lv.price >= fv:
            break
        # Only the BOT-owned volume is takeable by us; strat_vol is our own
        fill = min(lv.bot_vol, lim - pos)
        if fill > 0:
            orders.append((lv.price, fill))
            pos += fill
    return orders, pos


def _sweep_bids_above(ctx: TickContext, fv: float, lim: int) -> Tuple[List[Tuple[int, int]], int]:
    """Sell any bid at price > fv."""
    orders = []
    pos = ctx.position
    for lv in ctx.book.bid_levels_sorted():
        if lv.price <= fv:
            break
        fill = min(lv.bot_vol, lim + pos)
        if fill > 0:
            orders.append((lv.price, fill))
            pos -= fill
    return orders, pos


def make_osmium_stable(fv_anchor: float = 10000.0, edge: int = 10, min_inside_qty: int = 15, limit: int = 80):
    """Return a strategy fn that uses a FIXED fv anchor (the known OSMIUM FV).
    Matches the _trade_stable logic in submission 127989.
    """
    def strategy(ctx: TickContext) -> OrderIntent:
        fv = fv_anchor
        lim = limit
        intent = OrderIntent()
        pos = ctx.position
        opos = pos

        # Sweep mispriced
        sweep_buys, pos = _sweep_asks_below(ctx, fv, lim)
        intent.bids.extend(sweep_buys)
        sweep_sells, pos = _sweep_bids_above(ctx, fv, lim)
        # For MC's phase-1 matching, sells are placed as ask orders at aggressive prices
        intent.asks.extend(sweep_sells)

        buy_sweep = max(0, pos - opos)
        sell_sweep = max(0, opos - pos)
        buy_cap = max(0, lim - opos - buy_sweep)
        sell_cap = max(0, lim + opos - sell_sweep)

        bb = _best_bid(ctx)
        ba = _best_ask(ctx)

        if bb is not None and ba is not None:
            bid_pj = min(bb + 1, int(fv) - 1)
            ask_pj = max(ba - 1, int(fv) + 1)
            bid_ep = int(fv) - edge
            ask_ep = int(fv) + edge

            # Bid side: penny-jump + edge
            if bid_pj <= bid_ep:
                if buy_cap > 0:
                    intent.bids.append((bid_ep, buy_cap))
            else:
                bpj = min(min_inside_qty, buy_cap)
                be = buy_cap - bpj
                if be > 0:
                    intent.bids.append((bid_ep, be))
                if bpj > 0:
                    intent.bids.append((bid_pj, bpj))

            # Ask side: penny-jump + edge
            if ask_pj >= ask_ep:
                if sell_cap > 0:
                    intent.asks.append((ask_ep, sell_cap))
            else:
                spj = min(min_inside_qty, sell_cap)
                se = sell_cap - spj
                if se > 0:
                    intent.asks.append((ask_ep, se))
                if spj > 0:
                    intent.asks.append((ask_pj, spj))
        else:
            if buy_cap > 0:
                intent.bids.append((int(fv) - edge, buy_cap))
            if sell_cap > 0:
                intent.asks.append((int(fv) + edge, sell_cap))
        return intent
    return strategy


def make_pepper_trending(limit: int = 80, wall_offset: int = 10):
    """Port of _trade_trending for PEPPER: accumulate-then-hold with
    insider-detection off (we don't simulate qty=8 insider bot).
    """
    def strategy(ctx: TickContext) -> OrderIntent:
        lim = limit
        bb = _best_bid(ctx)
        ba = _best_ask(ctx)
        intent = OrderIntent()

        # FV estimate from walls (not from ctx.fv — strategies didn't know fv)
        if bb is None or ba is None:
            return intent
        worst_bid = min(lv.price for lv in ctx.book.bid_levels_sorted())
        worst_ask = max(lv.price for lv in ctx.book.ask_levels_sorted())
        fv_from_bid = worst_bid + wall_offset
        fv_from_ask = worst_ask - wall_offset
        if abs(fv_from_bid - fv_from_ask) > 1:
            return intent
        fv = (fv_from_bid + fv_from_ask) // 2
        pos = ctx.position

        # Sweep asks below FV (free profit)
        for lv in ctx.book.ask_levels_sorted():
            if lv.price >= fv:
                break
            fill = min(lv.bot_vol, lim - pos)
            if fill > 0:
                intent.bids.append((lv.price, fill))
                pos += fill

        if pos < 70:
            # ACCUMULATE: buy aggressively up to fv+8
            buy_limit = fv + 8
            for lv in ctx.book.ask_levels_sorted():
                if lv.price > buy_limit or lv.price < fv:
                    continue
                fill = min(lv.bot_vol, lim - pos)
                if fill > 0:
                    intent.bids.append((lv.price, fill))
                    pos += fill
                if pos >= lim:
                    break
            remaining = lim - pos
            if remaining > 0:
                intent.bids.append((bb + 1, remaining))
        else:
            # HOLD + MM
            buy_cap = lim - pos
            if buy_cap > 0:
                bid_price = min(bb + 1, fv - 1)
                intent.bids.append((bid_price, buy_cap))
            sell_qty = min(8, lim + pos)
            if sell_qty > 0:
                ask_price = max(ba - 1, fv + 1)
                intent.asks.append((ask_price, sell_qty))

        return intent
    return strategy
