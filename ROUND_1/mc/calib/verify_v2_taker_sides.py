"""Verify v2 taker side classification at one-sided OSM ticks.

Goal: count how many no_ask BUY and no_bid SELL real trades exist — these are
the only taker events that genuinely reward wider edge.
"""
from __future__ import annotations
import json
from pathlib import Path

DATA = Path(__file__).parent.parent.parent / "data" / "calib"


def classify(trade, book_buys, book_sells):
    best_bid = max(book_buys) if book_buys else None
    best_ask = min(book_sells) if book_sells else None
    if best_bid is not None and best_ask is not None:
        mid = (best_bid + best_ask) / 2
        return "BUY" if trade["price"] > mid else "SELL"
    elif best_bid is not None:
        return "BUY" if trade["price"] > best_bid else "SELL"
    elif best_ask is not None:
        return "BUY" if trade["price"] >= best_ask else "SELL"
    return None


def main():
    acts = json.loads((DATA / "127989_activities.json").read_text())
    mts = json.loads((DATA / "127989_market_trades.json").read_text())
    mt_idx: dict = {}
    for t in mts:
        mt_idx.setdefault((t["product"], t["ts"]), []).append(t)

    for prod in ["ASH_COATED_OSMIUM", "INTARIAN_PEPPER_ROOT"]:
        no_ask_buy = 0
        no_ask_sell = 0
        no_bid_buy = 0
        no_bid_sell = 0
        two_sided_buy = 0
        two_sided_sell = 0
        for a in acts:
            if a["product"] != prod:
                continue
            bbs = {int(p): int(v) for p, v in a["bids"]}
            bss = {int(p): int(v) for p, v in a["asks"]}
            tick_trades = mt_idx.get((prod, a["ts"]), [])
            for t in tick_trades:
                side = classify(t, bbs, bss)
                if not bss:  # no_ask
                    if side == "BUY":
                        no_ask_buy += t["quantity"]
                    else:
                        no_ask_sell += t["quantity"]
                elif not bbs:  # no_bid
                    if side == "BUY":
                        no_bid_buy += t["quantity"]
                    else:
                        no_bid_sell += t["quantity"]
                else:
                    if side == "BUY":
                        two_sided_buy += t["quantity"]
                    else:
                        two_sided_sell += t["quantity"]
        print(f"\n=== {prod} ===")
        print(f"  two-sided: BUY={two_sided_buy}  SELL={two_sided_sell}")
        print(f"  no_ask:    BUY={no_ask_buy}  SELL={no_ask_sell}  "
              f"← BUY here fills our deep sell")
        print(f"  no_bid:    BUY={no_bid_buy}  SELL={no_bid_sell}  "
              f"← SELL here fills our deep buy")


if __name__ == "__main__":
    main()
