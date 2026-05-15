"""Phase 3 verification harness.

Instruments prosperity3bt's match_orders so every SUBMISSION fill is tagged
either PHASE2 (crossed the resting book at tick t) or PHASE3 (filled against a
recorded tape trade at tick t — i.e., filled after Trader.run() returned).

Runs iter25_tb1 on all 3 R2 training days, tallies:
  - fills per phase per product per side
  - tape-trade coverage per product: trades at prices we didn't quote but
    would have matched if we had (phase 3 miss)
  - directional asymmetry: phase 3 buy-fill vol vs sell-fill vol per product
  - window concentration: phase 3 fills binned by 1000-tick windows
  - distribution of phase 3 trade price vs our limit price (signature of
    market-like vs limit-like)

Writes exploration6/phase3_evidence.json + summary to stdout.
"""

import sys
import json
import os
from collections import defaultdict
from pathlib import Path

ROOT = Path("/Users/svelaga/Documents/IMC Prosperity")
BT_ROOT = ROOT / "chrispyroberts-imc-prosperity-4/backtester"
DATA_ROOT = ROOT / "chrispyroberts-imc-prosperity-4/data"
ALGO = ROOT / "exploration4/iter25_tb1.py"

sys.path.insert(0, str(BT_ROOT))
sys.path.insert(0, str(ALGO.parent))

from prosperity3bt import runner as rnr
from prosperity3bt.datamodel import Trade
# iter25_tb1.py does `from datamodel import ...`; alias it.
import prosperity3bt.datamodel as _dm
sys.modules.setdefault("datamodel", _dm)
from prosperity3bt.file_reader import FileSystemReader
from prosperity3bt.models import TradeMatchingMode, MarketTrade

# --------------------------------------------------------------------------
# Phase tracker — stashes per-fill phase info as match_orders processes
# --------------------------------------------------------------------------
FILL_LOG = []   # list of dicts: {ts, symbol, side, price, qty, phase, our_price}
TAPE_LOG = []   # {ts, symbol, price, qty, orig_buy_qty, orig_sell_qty}
QUOTE_LOG = defaultdict(dict)  # ts -> symbol -> {"bids": [(p,q)], "asks": [(p,q)], "book": {...}}

_orig_match_buy = rnr.match_buy_order
_orig_match_sell = rnr.match_sell_order


def match_buy_order_instrumented(state, data, order, market_trades, trade_matching_mode):
    trades = []
    order_depth = state.order_depths[order.symbol]

    price_matches = sorted(p for p in order_depth.sell_orders.keys() if p <= order.price)
    for price in price_matches:
        volume = min(order.quantity, abs(order_depth.sell_orders[price]))
        t = Trade(order.symbol, price, volume, "SUBMISSION", "", state.timestamp)
        trades.append(t)
        FILL_LOG.append({
            "ts": state.timestamp, "symbol": order.symbol, "side": "BUY",
            "price": price, "qty": volume, "phase": "PHASE2_BOOK",
            "our_price": order.price,
        })
        state.position[order.symbol] = state.position.get(order.symbol, 0) + volume
        data.profit_loss[order.symbol] -= price * volume
        order_depth.sell_orders[price] += volume
        if order_depth.sell_orders[price] == 0:
            order_depth.sell_orders.pop(price)
        order.quantity -= volume
        if order.quantity == 0:
            return trades

    if trade_matching_mode == TradeMatchingMode.none:
        return trades

    for mt in market_trades:
        if (
            mt.sell_quantity == 0
            or mt.trade.price > order.price
            or (mt.trade.price == order.price and trade_matching_mode == TradeMatchingMode.worse)
        ):
            continue
        volume = min(order.quantity, mt.sell_quantity)
        t = Trade(order.symbol, order.price, volume, "SUBMISSION", mt.trade.seller, state.timestamp)
        trades.append(t)
        FILL_LOG.append({
            "ts": state.timestamp, "symbol": order.symbol, "side": "BUY",
            "price": order.price, "qty": volume, "phase": "PHASE3_TAPE",
            "our_price": order.price, "tape_price": mt.trade.price,
            "tape_seller": mt.trade.seller or "",
        })
        state.position[order.symbol] = state.position.get(order.symbol, 0) + volume
        data.profit_loss[order.symbol] -= order.price * volume
        mt.sell_quantity -= volume
        order.quantity -= volume
        if order.quantity == 0:
            return trades

    return trades


def match_sell_order_instrumented(state, data, order, market_trades, trade_matching_mode):
    trades = []
    order_depth = state.order_depths[order.symbol]

    price_matches = sorted((p for p in order_depth.buy_orders.keys() if p >= order.price), reverse=True)
    for price in price_matches:
        volume = min(abs(order.quantity), order_depth.buy_orders[price])
        t = Trade(order.symbol, price, volume, "", "SUBMISSION", state.timestamp)
        trades.append(t)
        FILL_LOG.append({
            "ts": state.timestamp, "symbol": order.symbol, "side": "SELL",
            "price": price, "qty": volume, "phase": "PHASE2_BOOK",
            "our_price": order.price,
        })
        state.position[order.symbol] = state.position.get(order.symbol, 0) - volume
        data.profit_loss[order.symbol] += price * volume
        order_depth.buy_orders[price] -= volume
        if order_depth.buy_orders[price] == 0:
            order_depth.buy_orders.pop(price)
        order.quantity += volume
        if order.quantity == 0:
            return trades

    if trade_matching_mode == TradeMatchingMode.none:
        return trades

    for mt in market_trades:
        if (
            mt.buy_quantity == 0
            or mt.trade.price < order.price
            or (mt.trade.price == order.price and trade_matching_mode == TradeMatchingMode.worse)
        ):
            continue
        volume = min(abs(order.quantity), mt.buy_quantity)
        t = Trade(order.symbol, order.price, volume, mt.trade.buyer, "SUBMISSION", state.timestamp)
        trades.append(t)
        FILL_LOG.append({
            "ts": state.timestamp, "symbol": order.symbol, "side": "SELL",
            "price": order.price, "qty": volume, "phase": "PHASE3_TAPE",
            "our_price": order.price, "tape_price": mt.trade.price,
            "tape_buyer": mt.trade.buyer or "",
        })
        state.position[order.symbol] = state.position.get(order.symbol, 0) - volume
        data.profit_loss[order.symbol] += order.price * volume
        mt.buy_quantity -= volume
        order.quantity += volume
        if order.quantity == 0:
            return trades

    return trades


# also log tape + quotes. Wrap match_orders itself.
_orig_match_orders = rnr.match_orders


def match_orders_instrumented(state, data, orders, result, trade_matching_mode):
    # snapshot quotes we're about to submit (post-limit-enforcement)
    ts = state.timestamp
    for sym, olist in orders.items():
        od = state.order_depths.get(sym)
        book = {
            "bids": dict(sorted(od.buy_orders.items(), reverse=True)[:5]) if od else {},
            "asks": dict(sorted(od.sell_orders.items())[:5]) if od else {},
        }
        QUOTE_LOG[ts][sym] = {
            "orders": [(o.price, o.quantity) for o in olist],
            "book": book,
        }

    # snapshot tape we're about to match against
    for sym, trades in data.trades[ts].items():
        for t in trades:
            TAPE_LOG.append({
                "ts": ts, "symbol": sym, "price": t.price, "qty": t.quantity,
                "buyer": t.buyer or "", "seller": t.seller or "",
            })

    return _orig_match_orders(state, data, orders, result, trade_matching_mode)


# --------------------------------------------------------------------------
def run_all():
    import iter25_tb1

    rnr.match_buy_order = match_buy_order_instrumented
    rnr.match_sell_order = match_sell_order_instrumented
    rnr.match_orders = match_orders_instrumented

    reader = FileSystemReader(DATA_ROOT)
    results = {}
    for day in (-1, 0, 1):
        FILL_LOG.clear()
        TAPE_LOG.clear()
        QUOTE_LOG.clear()

        trader = iter25_tb1.Trader()
        res = rnr.run_backtest(
            trader, reader, 2, day, False, TradeMatchingMode.all, True, False,
        )
        last_ts = res.activity_logs[-1].timestamp
        day_pnl = 0.0
        per_prod_pnl = {}
        for row in reversed(res.activity_logs):
            if row.timestamp != last_ts:
                break
            per_prod_pnl[row.columns[2]] = row.columns[-1]
            day_pnl += row.columns[-1]

        # aggregate this day's fill log
        agg = analyze_fills(FILL_LOG, TAPE_LOG, QUOTE_LOG)
        agg["pnl"] = day_pnl
        agg["per_product_pnl"] = per_prod_pnl
        results[day] = agg
        print(f"Day {day}: PnL={day_pnl:,.0f} | "
              f"P2_fills={agg['totals']['PHASE2_BOOK']['qty']} "
              f"P3_fills={agg['totals']['PHASE3_TAPE']['qty']}")

    return results


def analyze_fills(fills, tapes, quotes):
    totals = {
        "PHASE2_BOOK": {"fills": 0, "qty": 0, "notional": 0.0},
        "PHASE3_TAPE": {"fills": 0, "qty": 0, "notional": 0.0},
    }
    per_prod = defaultdict(lambda: {
        "PHASE2_BOOK": {"buy_qty": 0, "sell_qty": 0, "fills": 0},
        "PHASE3_TAPE": {"buy_qty": 0, "sell_qty": 0, "fills": 0},
    })
    windows = defaultdict(lambda: defaultdict(int))  # window_idx -> phase -> qty

    p3_tape_price_delta = []  # tape_price - our_price (buys); our_price - tape_price (sells) — edge captured

    for f in fills:
        phase = f["phase"]
        totals[phase]["fills"] += 1
        totals[phase]["qty"] += f["qty"]
        totals[phase]["notional"] += f["qty"] * f["price"]
        p = per_prod[f["symbol"]][phase]
        p["fills"] += 1
        if f["side"] == "BUY":
            p["buy_qty"] += f["qty"]
        else:
            p["sell_qty"] += f["qty"]
        win = (f["ts"] // 100) // 1000  # 1000-tick window (i.e., 100k-ts window)
        windows[win][phase] += f["qty"]
        if phase == "PHASE3_TAPE":
            if f["side"] == "BUY":
                delta = f.get("tape_price", f["our_price"]) - f["our_price"]
            else:
                delta = f["our_price"] - f.get("tape_price", f["our_price"])
            p3_tape_price_delta.append(delta)

    # tape-trade coverage by product
    tape_by_prod_side = defaultdict(lambda: {"n": 0, "qty": 0})
    for t in tapes:
        # classify side against the mid of the book at that tick — but we only
        # have the book via QUOTE_LOG; skip this and just count raw tape
        tape_by_prod_side[t["symbol"]]["n"] += 1
        tape_by_prod_side[t["symbol"]]["qty"] += t["qty"]

    # missed phase-3 fills: tape trades we could have captured if quoting
    # tighter. For each tape trade at ts, compare tape price against our best
    # bid/ask in QUOTE_LOG[ts][sym]. Count only trades outside our quotes.
    # A tape buy (buyer non-empty, seller empty) means someone bought from the
    # tape side at tape.price — if we had an ask ≤ tape.price, we would have
    # been filled. Our quote is in QUOTE_LOG[ts][sym].orders (price, qty>0 bid,
    # qty<0 ask).
    misses = defaultdict(lambda: {"ask_misses": 0, "bid_misses": 0,
                                   "ask_miss_qty": 0, "bid_miss_qty": 0})
    for t in tapes:
        sym = t["symbol"]
        ts = t["ts"]
        q = quotes.get(ts, {}).get(sym)
        if not q:
            continue
        # Our best ask / best bid we submitted
        our_asks = sorted([(p, -qn) for (p, qn) in q["orders"] if qn < 0])
        our_bids = sorted([(p, qn) for (p, qn) in q["orders"] if qn > 0], reverse=True)

        # tape side inference: if buyer present and seller empty → market buy
        # (someone lifted ask); if seller present and buyer empty → market
        # sell. Treat SUBMISSION-side trades as already-accounted.
        buyer = t["buyer"]
        seller = t["seller"]
        if "SUBMISSION" in buyer or "SUBMISSION" in seller:
            continue
        # Aggressor direction unknown in Prosperity CSV — both sides often
        # blank. We use price-vs-book instead: if tape price crossed our
        # notional quote, we'd have been matched.
        # Simpler: match tape against our quotes using the same rule as the
        # backtester (buyer-tape has sell_quantity we could hit with an ask).
        # In the backtester every tape entry has BOTH buy_quantity and
        # sell_quantity = t.quantity, then decrement per match. So to detect
        # "would we have filled if quote X?", for each tape trade at price P,
        # qty Q, we check: (a) any of our asks with price ≤ P → could have
        # sold up to Q; (b) any of our bids with price ≥ P → could have bought.
        for ap, aq in our_asks:
            if ap <= t["price"]:
                # actually fired as phase 3 — don't double-count
                pass
        # Miss = tape price offers fill that our CURRENT quote doesn't reach.
        # Our best ask > tape price (we'd need to lower ask to ap <= tp).
        if our_asks:
            best_ask = our_asks[0][0]
            if best_ask > t["price"]:
                misses[sym]["ask_misses"] += 1
                misses[sym]["ask_miss_qty"] += t["qty"]
        else:
            misses[sym]["ask_misses"] += 1
            misses[sym]["ask_miss_qty"] += t["qty"]
        if our_bids:
            best_bid = our_bids[0][0]
            if best_bid < t["price"]:
                misses[sym]["bid_misses"] += 1
                misses[sym]["bid_miss_qty"] += t["qty"]
        else:
            misses[sym]["bid_misses"] += 1
            misses[sym]["bid_miss_qty"] += t["qty"]

    # tape price signature for phase 3 fills
    p3_delta_hist = {"<0": 0, "==0": 0, ">0": 0}
    for d in p3_tape_price_delta:
        if d < 0:
            p3_delta_hist["<0"] += 1
        elif d == 0:
            p3_delta_hist["==0"] += 1
        else:
            p3_delta_hist[">0"] += 1

    return {
        "totals": totals,
        "per_product": {k: v for k, v in per_prod.items()},
        "windows": {str(k): dict(v) for k, v in sorted(windows.items())},
        "tape_counts": {k: v for k, v in tape_by_prod_side.items()},
        "misses": {k: v for k, v in misses.items()},
        "phase3_price_vs_ours": p3_delta_hist,
    }


if __name__ == "__main__":
    res = run_all()
    out = Path(__file__).parent / "phase3_evidence.json"
    with open(out, "w") as f:
        json.dump(res, f, indent=2, default=str)
    print(f"\nSaved evidence → {out}")

    # crisp summary
    print("\n=== SUMMARY across 3 days ===")
    p2 = sum(res[d]["totals"]["PHASE2_BOOK"]["qty"] for d in res)
    p3 = sum(res[d]["totals"]["PHASE3_TAPE"]["qty"] for d in res)
    p2_not = sum(res[d]["totals"]["PHASE2_BOOK"]["notional"] for d in res)
    p3_not = sum(res[d]["totals"]["PHASE3_TAPE"]["notional"] for d in res)
    print(f"Phase 2 book-match qty: {p2:>7}  notional: {p2_not:>14,.0f}")
    print(f"Phase 3 tape-match qty: {p3:>7}  notional: {p3_not:>14,.0f}")
    if p2 + p3:
        print(f"Phase 3 share of fills: {p3 / (p2 + p3):.1%}")

    print("\n--- Per product, per phase, per side (3-day total) ---")
    prods = set()
    for d in res:
        prods.update(res[d]["per_product"].keys())
    for sym in sorted(prods):
        for phase in ("PHASE2_BOOK", "PHASE3_TAPE"):
            buy = sum(res[d]["per_product"].get(sym, {}).get(phase, {}).get("buy_qty", 0) for d in res)
            sell = sum(res[d]["per_product"].get(sym, {}).get(phase, {}).get("sell_qty", 0) for d in res)
            print(f"{sym:22s} {phase:12s}  buy={buy:>6} sell={sell:>6}  net={buy-sell:+6}")

    print("\n--- Phase 3 fill price vs our quote price (edge signature) ---")
    delta = defaultdict(int)
    for d in res:
        for k, v in res[d]["phase3_price_vs_ours"].items():
            delta[k] += v
    print(f"  tape better than our quote (>0): {delta['>0']}")
    print(f"  tape equal to our quote  (==0): {delta['==0']}")
    print(f"  tape worse than our quote  (<0): {delta['<0']}")
