"""Trace OSM position trajectory in v2 to look for structural improvements.

Mirrors pep_position_trace. OSM flow is 28 BUY / 5242 SELL (two-sided) — massively
SELL-biased, so we expect position to skew NEGATIVE (we absorb selling).

Questions:
- Does OSM pos hit -80 and stall?
- Or does pos oscillate / mean-revert?
- When does the MM make money vs lose it?
"""
from __future__ import annotations
import io
import sys
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from parametric_trader import make_trader
from synth_replay import (
    Order, OrderDepth, TradingState, Trade,
    _cross_trader_orders, _apply_taker, _build_order_depth,
)
from server_book_replay import load_ticks, load_market_trades, _mt_to_trade
from server_book_replay_v2 import _trades_to_takers_v2


def trace(trader, product, session="127989"):
    ticks = load_ticks(product, session=session)
    mt_by_ts = load_market_trades(product, session=session)
    position = 0
    cash = 0.0
    trader_data = ""
    sink = io.StringIO()
    history = []  # (ts, pos, cash, bb, ba, n_fills, pnl_mark)

    for r in ticks:
        book_buys = {int(p): int(v) for p, v in r["bids"]}
        book_sells = {int(p): int(v) for p, v in r["asks"]}
        strat_buys: dict = {}
        strat_sells: dict = {}
        tick_mts = [_mt_to_trade(m) for m in mt_by_ts.get(r["ts"], [])]

        od = _build_order_depth(book_buys, book_sells)
        state = TradingState(
            timestamp=r["ts"],
            order_depths={product: od},
            position={product: position},
            market_trades={product: tick_mts},
            own_trades={product: []},
            trader_data=trader_data,
        )
        with redirect_stdout(sink):
            rd, _conv, trader_data = trader.run(state)
        orders = rd.get(product, []) or []

        fills = 0
        cross_fills, position, cash_delta = _cross_trader_orders(
            orders, book_buys, book_sells, strat_buys, strat_sells,
            position, limit=80, ts=r["ts"],
        )
        cash += cash_delta
        fills += len(cross_fills)

        for ev in _trades_to_takers_v2(tick_mts, book_buys, book_sells):
            t_fills, position, cash_delta = _apply_taker(
                ev, book_buys, book_sells, strat_buys, strat_sells,
                position, limit=80, ts=r["ts"],
            )
            cash += cash_delta
            fills += len(t_fills)

        bb = max(book_buys) if book_buys else None
        ba = min(book_sells) if book_sells else None
        mid = (bb + ba) / 2 if bb and ba else (r["mid_price"] or 10000)
        mark = cash + position * mid
        history.append((r["ts"], position, cash, bb, ba, fills, mark))

    return history


def summary(h, label):
    positions = [p for _, p, _, _, _, _, _ in h]
    marks = [m for _, _, _, _, _, _, m in h]
    print(f"\n== {label} ==")
    print(f"  ticks={len(h)}  min_pos={min(positions)}  max_pos={max(positions)}  final={positions[-1]}")
    print(f"  avg_pos={sum(positions)/len(positions):.1f}")

    # Time at limits
    at_lower = sum(1 for p in positions if p <= -80)
    at_upper = sum(1 for p in positions if p >= 80)
    print(f"  at pos=-80: {at_lower} ticks ({100*at_lower/len(h):.1f}%)")
    print(f"  at pos=+80: {at_upper} ticks ({100*at_upper/len(h):.1f}%)")

    # Distribution
    buckets = {"<-60": 0, "-60..-40": 0, "-40..-20": 0, "-20..0": 0,
               "0..20": 0, "20..40": 0, "40..60": 0, ">60": 0}
    for p in positions:
        if p < -60: buckets["<-60"] += 1
        elif p < -40: buckets["-60..-40"] += 1
        elif p < -20: buckets["-40..-20"] += 1
        elif p < 0: buckets["-20..0"] += 1
        elif p < 20: buckets["0..20"] += 1
        elif p < 40: buckets["20..40"] += 1
        elif p < 60: buckets["40..60"] += 1
        else: buckets[">60"] += 1
    total = len(h)
    print(f"  position distribution:")
    for k, v in buckets.items():
        print(f"    {k:>8s}: {v:4d} ({100*v/total:5.1f}%)")

    # Mark trajectory: when do we make money?
    print(f"  mark at q25={marks[len(marks)//4]:.0f}  q50={marks[len(marks)//2]:.0f}  "
          f"q75={marks[3*len(marks)//4]:.0f}  final={marks[-1]:.0f}")


def main():
    # Baseline: 127989 defaults (no custom OSM params)
    t = make_trader()
    h_base = trace(t, "ASH_COATED_OSMIUM")
    summary(h_base, "OSM baseline (127989 defaults)")

    # Current best: e22 wider edge (predicts v2 +1406 on combined, but mostly OSM-driven)
    t = make_trader(osm={"quote_edge": 22})
    h_e22 = trace(t, "ASH_COATED_OSMIUM")
    summary(h_e22, "OSM quote_edge=22")

    # Do we need a tighter edge for the buy side (we're SELL-absorbing so pos goes negative)?
    t = make_trader(osm={"buy_edge": 10, "sell_edge": 22})
    h_asy = trace(t, "ASH_COATED_OSMIUM")
    summary(h_asy, "OSM buy_edge=10, sell_edge=22")


if __name__ == "__main__":
    main()
