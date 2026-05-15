"""Trace what actually differs between edge=12 and edge=22 on OSM.

Hypothesis: with price_tol=0 takers, deep quote price shouldn't matter — we
only fill at penny-jump. So why does edge=22 MC show +160 vs edge=12?

Count fill prices and quantities by edge.
"""
from __future__ import annotations
from collections import Counter
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from parametric_trader import make_trader
from server_book_replay import run_server_session


def analyze(edge, seed=0):
    t = make_trader(osm={"quote_edge": edge})
    r = run_server_session(t, "ASH_COATED_OSMIUM", seed=seed)
    buys = [(f.price, f.qty) for f in r.fills if f.side == "BUY"]
    sells = [(f.price, f.qty) for f in r.fills if f.side == "SELL"]
    buy_prices = Counter()
    sell_prices = Counter()
    for p, q in buys:
        buy_prices[p] += q
    for p, q in sells:
        sell_prices[p] += q
    source_counts = Counter(f.source for f in r.fills)
    return {
        "pnl": r.pnl,
        "fills": len(r.fills),
        "final_pos": r.final_pos,
        "buy_prices": sorted(buy_prices.items()),
        "sell_prices": sorted(sell_prices.items()),
        "sources": dict(source_counts),
    }


def main():
    for edge in [12, 16, 22, 30]:
        print(f"\n=== edge={edge}, seed=0 ===")
        r = analyze(edge, seed=0)
        print(f"  PnL={r['pnl']:.0f}  fills={r['fills']}  final_pos={r['final_pos']}")
        print(f"  sources={r['sources']}")
        print(f"  buy_prices (low→high):")
        for p, q in r["buy_prices"]:
            print(f"    {p} × {q}")
        print(f"  sell_prices (low→high):")
        for p, q in r["sell_prices"]:
            print(f"    {p} × {q}")


if __name__ == "__main__":
    main()
