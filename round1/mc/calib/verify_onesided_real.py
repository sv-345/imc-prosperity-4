"""Are MC's one-sided fills REAL or fabricated?

MC uses RNG to sample takers. At a one-sided book tick, if RNG says BUY,
our deep quote fills. But did a REAL taker show up at that tick?

Check: for each one-sided OSM/PEP tick in 127989, did a market_trade occur?
"""
from __future__ import annotations
import json
from pathlib import Path

DATA = Path(__file__).parent.parent.parent / "data" / "calib"


def main():
    acts = json.loads((DATA / "127989_activities.json").read_text())
    mts = json.loads((DATA / "127989_market_trades.json").read_text())

    # index market_trades by (product, ts)
    mt_idx: dict = {}
    for t in mts:
        mt_idx.setdefault((t["product"], t["ts"]), []).append(t)

    for prod in ["ASH_COATED_OSMIUM", "INTARIAN_PEPPER_ROOT"]:
        onesided = [a for a in acts if a["product"] == prod
                    and (not a["bids"] or not a["asks"])]
        with_trade = [a for a in onesided if mt_idx.get((prod, a["ts"]))]
        print(f"\n=== {prod} ===")
        print(f"  one-sided ticks: {len(onesided)}")
        print(f"  with real trades: {len(with_trade)} ({100*len(with_trade)/max(1,len(onesided)):.1f}%)")
        # Sample a few
        for a in with_trade[:5]:
            tr = mt_idx[(prod, a["ts"])]
            side = "no_ask" if not a["asks"] else "no_bid"
            prices = [t["price"] for t in tr]
            qtys = [t["quantity"] for t in tr]
            print(f"    ts={a['ts']} ({side}) mid={a['mid_price']}  "
                  f"bids={a['bids']} asks={a['asks']} trades: {list(zip(prices, qtys))}")


if __name__ == "__main__":
    main()
