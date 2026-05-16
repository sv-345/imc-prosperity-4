"""Replay a submission Trader against 127989's EXACT server book snapshots.

Unlike synth_replay.py (which generates synthetic books from bot formulas),
this uses the per-tick book snapshots from `data/calib/127989_activities.json`
— the real books the server presented. Only the taker flow is MC-sampled
(since server doesn't log enough of it).

This isolates: does the submission trader (127989 or v15) produce the same
fills/PnL when fed the SAME book that 127989 saw?
"""
from __future__ import annotations
import io
import json
import random
import statistics
from contextlib import redirect_stdout
from dataclasses import dataclass, field
from pathlib import Path

from synth_replay import (
    Order, OrderDepth, TradingState, Trade,
    Fill, SessionResult, _cross_trader_orders, _apply_taker, _build_order_depth,
    _load_trader_from_path,
)
from synth_book import TakerEvent


DATA = Path(__file__).parent.parent / "data" / "calib"


def load_ticks(product, session="127989"):
    acts = json.loads((DATA / f"{session}_activities.json").read_text())
    return [r for r in acts if r["product"] == product]


def load_market_trades(product, session="127989"):
    """Index market_trades by ts so we can look up per-tick."""
    path = DATA / f"{session}_market_trades.json"
    if not path.exists():
        return {}
    mts = json.loads(path.read_text())
    by_ts: dict = {}
    for t in mts:
        if t["product"] != product:
            continue
        by_ts.setdefault(t["ts"], []).append(t)
    return by_ts


def _mt_to_trade(mt):
    return Trade(
        symbol=mt["product"], price=mt["price"], quantity=mt["quantity"],
        buyer=mt.get("buyer", ""), seller=mt.get("seller", ""),
        timestamp=mt.get("ts_trade", mt["ts"]),
    )


def _server_snap_to_book(r):
    """Convert server snapshot to (book_buys {px: qty}, book_sells {px: qty})."""
    book_buys = {int(p): int(v) for p, v in r["bids"]}
    book_sells = {int(p): int(v) for p, v in r["asks"]}  # stored as positive vols
    return book_buys, book_sells


def run_server_session(
    trader, product, seed=0,
    taker_rate=None, qty_range=None,
):
    """Run one replay using server book snapshots. Takers are MC-sampled."""
    if product == "ASH_COATED_OSMIUM":
        # Calibrated to match 127989 server fills (87) and PnL (3144) at fill count
        taker_rate = 0.060 if taker_rate is None else taker_rate
        qty_range = (3, 10) if qty_range is None else qty_range
    else:
        taker_rate = 0.015 if taker_rate is None else taker_rate
        qty_range = (3, 8) if qty_range is None else qty_range

    ticks = load_ticks(product)
    mt_idx = load_market_trades(product)
    result = SessionResult(product=product, seed=seed)
    position = 0
    cash = 0.0
    trader_data = ""
    rng = random.Random(seed)

    sink = io.StringIO()

    for r in ticks:
        book_buys, book_sells = _server_snap_to_book(r)
        strat_buys: dict = {}
        strat_sells: dict = {}
        tick_mts = [_mt_to_trade(m) for m in mt_idx.get(r["ts"], [])]

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

        cross_fills, position, cash_delta = _cross_trader_orders(
            orders, book_buys, book_sells, strat_buys, strat_sells,
            position, limit=80, ts=r["ts"],
        )
        cash += cash_delta
        for f in cross_fills:
            f.product = product
            result.fills.append(f)

        # MC takers
        if rng.random() < taker_rate:
            side = "BUY" if rng.random() < 0.5 else "SELL"
            qty = rng.randint(*qty_range)
            ev = TakerEvent(side=side, qty=qty, price_tol=0)
            t_fills, position, cash_delta = _apply_taker(
                ev, book_buys, book_sells, strat_buys, strat_sells,
                position, limit=80, ts=r["ts"],
            )
            cash += cash_delta
            for f in t_fills:
                f.product = product
                result.fills.append(f)

    result.cash = cash
    result.final_pos = position
    # final fv from last tick's mid
    last_mid = ticks[-1].get("mid_price", 10000)
    result.final_fv = last_mid or 10000
    return result


def compare(path_a, name_a, path_b, name_b, product, n_seeds=50):
    print(f"\n== Server-book replay  {product}  ({n_seeds} seeds) ==")
    a_pnls, b_pnls = [], []
    a_fills, b_fills = [], []
    for s in range(n_seeds):
        ta = _load_trader_from_path(path_a)
        tb = _load_trader_from_path(path_b)
        ra = run_server_session(ta, product, seed=s)
        rb = run_server_session(tb, product, seed=s)
        a_pnls.append(ra.pnl)
        b_pnls.append(rb.pnl)
        a_fills.append(len(ra.fills))
        b_fills.append(len(rb.fills))
    print(f"  {name_a}:  PnL mean={statistics.mean(a_pnls):5.0f}±{statistics.stdev(a_pnls):.0f}  "
          f"fills mean={statistics.mean(a_fills):.1f}")
    print(f"  {name_b}:  PnL mean={statistics.mean(b_pnls):5.0f}±{statistics.stdev(b_pnls):.0f}  "
          f"fills mean={statistics.mean(b_fills):.1f}")
    d = [b - a for a, b in zip(a_pnls, b_pnls)]
    wins = sum(1 for x in d if x > 0)
    print(f"  paired {name_b}-{name_a}: mean={statistics.mean(d):+.0f}  "
          f"wins={wins}/{n_seeds}")
    return a_pnls, b_pnls


if __name__ == "__main__":
    P127989 = "<repo>/ROUND_1/submissions/127989/127989.py"
    V15 = "<repo>/ROUND_1/submissions/v15_wall_aware/v15_wall_aware.py"
    print("Server ground-truth PnL: 127989 OSM=3144 PEP=7577; v15 OSM=2983 PEP=7577")
    compare(P127989, "127989", V15, "v15", "ASH_COATED_OSMIUM", n_seeds=50)
    compare(P127989, "127989", V15, "v15", "INTARIAN_PEPPER_ROOT", n_seeds=50)
