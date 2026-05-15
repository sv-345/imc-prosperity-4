"""Compare fills between edge=10 and edge=80 for a single seed.
Report: fill count by price, total cash, total position, mtm PnL."""
from __future__ import annotations
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from book_replay import BookReplayer, load_ticks
from mc_r1_v1 import OSMIUM
from strategies_r1 import make_osmium_stable

ticks = load_ticks("ASH_COATED_OSMIUM")
print(f"ticks: {len(ticks)}")

for edge in (10, 80, 200, 1000):
    strat = make_osmium_stable(fv_anchor=10000.0, edge=edge, min_inside_qty=15, limit=80)
    r = BookReplayer(OSMIUM, strat, ticks, seed=0, position_limit=80)
    r.run()
    print(f"\n=== edge={edge} ===")
    print(f"  final position: {r.position}")
    print(f"  final cash:     {r.cash:.2f}")
    print(f"  mtm PnL:        {r.mtm_pnl():.2f}")
    print(f"  total fills:    {len(r.fills)}")
    # Break down by price and direction
    buys = [f for f in r.fills if f.side == "BUY"]
    sells = [f for f in r.fills if f.side == "SELL"]
    print(f"  buy fills:  n={len(buys)}, total qty={sum(f.qty for f in buys)}, avg price={sum(f.price*f.qty for f in buys)/max(sum(f.qty for f in buys),1):.2f}")
    print(f"  sell fills: n={len(sells)}, total qty={sum(f.qty for f in sells)}, avg price={sum(f.price*f.qty for f in sells)/max(sum(f.qty for f in sells),1):.2f}")
    # Price histogram
    buy_prices = Counter(f.price for f in buys)
    sell_prices = Counter(f.price for f in sells)
    print(f"  ALL buy prices:  {dict(sorted(buy_prices.items()))}")
    print(f"  ALL sell prices: {dict(sorted(sell_prices.items()))}")
    # By reason
    reasons = Counter(f.counterparty for f in r.fills)
    print(f"  fill reasons: {dict(reasons)}")
