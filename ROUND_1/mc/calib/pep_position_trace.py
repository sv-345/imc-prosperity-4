"""Trace PEP position trajectory in v2 to look for structural improvements.

Questions:
- When does pos hit accumulate_threshold?
- How much time in accumulate vs hold?
- What's final_pos?
- Are there moments where we'd want to sell harder / buy harder?
"""
from __future__ import annotations
import io
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from parametric_trader import make_trader
from synth_replay import (
    Order, OrderDepth, TradingState, Trade,
    SessionResult, _cross_trader_orders, _apply_taker, _build_order_depth,
)
from server_book_replay import DATA, load_ticks, load_market_trades, _mt_to_trade
from server_book_replay_v2 import _trades_to_takers_v2


def trace(trader, product, session="127989"):
    ticks = load_ticks(product, session=session)
    mt_by_ts = load_market_trades(product, session=session)
    position = 0
    cash = 0.0
    trader_data = ""
    sink = io.StringIO()
    history = []  # (ts, pos, cash, bb, ba, n_fills_this_tick)

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
        history.append((r["ts"], position, cash, bb, ba, fills))

    return history


def main():
    t = make_trader(pep={"accumulate_threshold": 65, "cooldown_up": 0})
    h = trace(t, "INTARIAN_PEPPER_ROOT")

    # Key stats
    positions = [p for _, p, _, _, _, _ in h]
    print(f"PEP (t65+cu0): positions across {len(h)} ticks")
    print(f"  min={min(positions)}  max={max(positions)}  final={positions[-1]}")
    print(f"  avg={sum(positions)/len(positions):.1f}")
    thr = 65
    above = sum(1 for p in positions if p >= thr)
    print(f"  ticks at or above thr={thr}: {above} ({100*above/len(h):.1f}%)")

    # When did pos cross 65 first?
    for ts, p, _, _, _, _ in h:
        if p >= 65:
            print(f"  first hit pos≥65: ts={ts}")
            break

    # Pos at key ticks
    print(f"\n  pos at ts=20000: {h[200][1] if len(h)>200 else '?'}")
    print(f"  pos at ts=50000: {h[500][1] if len(h)>500 else '?'}")
    print(f"  pos at ts=80000: {h[800][1] if len(h)>800 else '?'}")
    print(f"  final:          {h[-1][1]}")

    # Cash + mark
    last_mid = None
    for r in load_ticks("INTARIAN_PEPPER_ROOT"):
        if r["mid_price"]:
            last_mid = r["mid_price"]
    last_cash = h[-1][2]
    print(f"\n  final cash={last_cash:.0f}  final_pos={h[-1][1]}  mid={last_mid}")
    print(f"  total PnL={last_cash + h[-1][1]*last_mid:.0f}")


if __name__ == "__main__":
    main()
