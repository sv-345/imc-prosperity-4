"""Ports of the other submitted R1 strategies (110534, 113620, 114525) to
MC v1's TickContext/OrderIntent interface.

Used for Phase 3 Level 2 validation (strategy-ranking preservation): do our
MC PnLs rank these four submissions the same way the server did?

Server ranking (total PnL):
  127989 (10721) > 114525 (10412) > 113620 (10114) > 110534 (3940)

Per-product:
  OSMIUM : 127989 (3144)  > 114525 (3127) > 113620 (2828) > 110534 (1981)
  PEPPER : 127989 (7577)  > {113620, 114525} tied (7286) > 110534 (1959)
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


def make_osmium_stable_nopj(fv_anchor: float = 10000.0, edge: int = 7,
                            limit: int = 50, acc_thresh: int = 0):
    """110534-style OSMIUM: smart sweep (includes at-FV fills when inventory
    favors it) + single-level quote at fv±edge. NO penny-jump.

    Matches submission 110534's _trade_stable.
    """
    def strategy(ctx: TickContext) -> OrderIntent:
        fv = fv_anchor
        lim = limit
        intent = OrderIntent()
        pos = ctx.position
        opos = pos

        # Sweep asks below FV
        for lv in ctx.book.ask_levels_sorted():
            if lv.price >= fv:
                break
            fill = min(lv.bot_vol, lim - pos)
            if fill > 0:
                intent.bids.append((lv.price, fill))
                pos += fill

        # Hit bids above FV
        for lv in ctx.book.bid_levels_sorted():
            if lv.price <= fv:
                break
            fill = min(lv.bot_vol, lim + pos)
            if fill > 0:
                intent.asks.append((lv.price, fill))
                pos -= fill

        # Accept at-FV fills based on inventory lean
        buy_at_fv = (pos < 0) or (pos < acc_thresh)
        sell_at_fv = (pos > 0) or (pos > -acc_thresh)

        if buy_at_fv:
            for lv in ctx.book.ask_levels_sorted():
                if lv.price != fv:
                    continue
                fill = min(lv.bot_vol, lim - pos)
                if fill > 0:
                    intent.bids.append((lv.price, fill))
                    pos += fill

        if sell_at_fv:
            for lv in ctx.book.bid_levels_sorted():
                if lv.price != fv:
                    continue
                fill = min(lv.bot_vol, lim + pos)
                if fill > 0:
                    intent.asks.append((lv.price, fill))
                    pos -= fill

        buy_sweep = max(0, pos - opos)
        sell_sweep = max(0, opos - pos)
        buy_cap = max(0, lim - opos - buy_sweep)
        sell_cap = max(0, lim + opos - sell_sweep)

        # Single-level quote at FV ± edge
        if buy_cap > 0:
            intent.bids.append((int(fv) - edge, buy_cap))
        if sell_cap > 0:
            intent.asks.append((int(fv) + edge, sell_cap))

        return intent
    return strategy


def make_pepper_rw_mm(limit: int = 50, edge: int = 7, min_inside_qty: int = 10):
    """110534-style PEPPER: FV estimated from wall midpoint, smart sweep +
    dual-level penny-jump quoting (L1 at BB/BA, L2 at BB+1/BA-1).

    Matches submission 110534's _trade_random_walk with wall_offset=None
    (midpoint mode).
    """
    def strategy(ctx: TickContext) -> OrderIntent:
        lim = limit
        bb = _best_bid(ctx)
        ba = _best_ask(ctx)
        intent = OrderIntent()
        if bb is None or ba is None:
            return intent

        # Estimate FV from wall midpoint (wall_offset=None mode)
        worst_bid = min(lv.price for lv in ctx.book.bid_levels_sorted())
        worst_ask = max(lv.price for lv in ctx.book.ask_levels_sorted())
        wall_spread = worst_ask - worst_bid
        if wall_spread < 10 or wall_spread > 30:
            # Fallback: simple penny-jump
            bid1 = bb + 1
            ask1 = ba - 1
            if bid1 >= ask1:
                mid = (bb + ba) // 2
                bid1, ask1 = mid, mid + 1
            buy_room = max(0, lim - ctx.position)
            sell_room = max(0, lim + ctx.position)
            if buy_room > 0:
                intent.bids.append((bid1, buy_room))
            if sell_room > 0:
                intent.asks.append((ask1, sell_room))
            return intent

        fv = (worst_bid + worst_ask) // 2
        pos = ctx.position
        opos = pos

        # Smart sweep (with acc_thresh=0)
        for lv in ctx.book.ask_levels_sorted():
            if lv.price >= fv:
                break
            fill = min(lv.bot_vol, lim - pos)
            if fill > 0:
                intent.bids.append((lv.price, fill))
                pos += fill
        for lv in ctx.book.bid_levels_sorted():
            if lv.price <= fv:
                break
            fill = min(lv.bot_vol, lim + pos)
            if fill > 0:
                intent.asks.append((lv.price, fill))
                pos -= fill

        buy_sweep = max(0, pos - opos)
        sell_sweep = max(0, opos - pos)
        buy_cap = max(0, lim - opos - buy_sweep)
        sell_cap = max(0, lim + opos - sell_sweep)

        # L2 (inside) penny-jump, clamped
        bid_L2 = bb + 1
        ask_L2 = ba - 1
        if bid_L2 >= ask_L2:
            bid_L2, ask_L2 = fv - 1, fv + 1
        bid_L2 = min(bid_L2, fv - 1)
        ask_L2 = max(ask_L2, fv + 1)

        # L1 (outside) at BB/BA, clamped
        bid_L1 = min(bb, fv - 1)
        ask_L1 = max(ba, fv + 1)

        # Bid side
        if bid_L1 == bid_L2:
            if buy_cap > 0:
                intent.bids.append((bid_L2, buy_cap))
        else:
            buy_L2 = min(min_inside_qty, buy_cap)
            buy_L1 = buy_cap - buy_L2
            if buy_L1 > 0:
                intent.bids.append((bid_L1, buy_L1))
            if buy_L2 > 0:
                intent.bids.append((bid_L2, buy_L2))

        # Ask side
        if ask_L1 == ask_L2:
            if sell_cap > 0:
                intent.asks.append((ask_L2, sell_cap))
        else:
            sell_L2 = min(min_inside_qty, sell_cap)
            sell_L1 = sell_cap - sell_L2
            if sell_L1 > 0:
                intent.asks.append((ask_L1, sell_L1))
            if sell_L2 > 0:
                intent.asks.append((ask_L2, sell_L2))

        return intent
    return strategy


def make_pepper_buyonly(limit: int = 80):
    """113620 / 114525 PEPPER: sweep all asks, bid bb+1 for remainder.
    NEVER sells. Once at limit, no orders.
    """
    def strategy(ctx: TickContext) -> OrderIntent:
        lim = limit
        intent = OrderIntent()
        pos = ctx.position
        if pos >= lim:
            return intent

        # Sweep ALL asks
        for lv in ctx.book.ask_levels_sorted():
            fill = min(lv.bot_vol, lim - pos)
            if fill > 0:
                intent.bids.append((lv.price, fill))
                pos += fill
            if pos >= lim:
                break

        remaining = lim - pos
        if remaining > 0:
            bb = _best_bid(ctx)
            if bb is not None:
                intent.bids.append((bb + 1, remaining))
        return intent
    return strategy
