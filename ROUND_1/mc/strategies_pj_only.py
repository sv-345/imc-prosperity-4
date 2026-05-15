"""A stripped OSMIUM strategy: sweep below-FV asks, then quote penny-jump
only (no edge quote). Tests the hypothesis that the edge quote is net-negative
due to adverse selection at the wall price.

Also: same strategy but with a variable penny-jump size.
"""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from mc_r1_v1 import OrderIntent, TickContext


def _best_bid(ctx):
    lv = ctx.book.best_bid()
    return lv.price if lv else None


def _best_ask(ctx):
    lv = ctx.book.best_ask()
    return lv.price if lv else None


def make_osmium_pj_only(fv_anchor: float = 10000.0, pj_size: int = 15,
                         limit: int = 80):
    """Penny-jump only, no edge quote. fv-sweep retained for free-profit takes."""
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

        buy_sweep = max(0, pos - opos)
        sell_sweep = max(0, opos - pos)
        buy_cap = max(0, lim - opos - buy_sweep)
        sell_cap = max(0, lim + opos - sell_sweep)

        bb = _best_bid(ctx)
        ba = _best_ask(ctx)

        if bb is not None:
            bid_pj = min(bb + 1, int(fv) - 1)
            bpj = min(pj_size, buy_cap)
            if bpj > 0:
                intent.bids.append((bid_pj, bpj))
        if ba is not None:
            ask_pj = max(ba - 1, int(fv) + 1)
            spj = min(pj_size, sell_cap)
            if spj > 0:
                intent.asks.append((ask_pj, spj))
        return intent
    return strategy
