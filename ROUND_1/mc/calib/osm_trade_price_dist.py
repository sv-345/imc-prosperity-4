"""Distribution of BUY-taker and SELL-taker trade prices in OSM across sessions.

If max BUY-taker price is 10002, wider sell edge can never fill. Structural ceiling.
"""
from __future__ import annotations
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from server_book_replay import load_ticks, load_market_trades, _mt_to_trade
from server_book_replay_v2 import _trade_side
from training_book_replay import load_day_ticks, load_day_trades


def analyze_live(product):
    ticks = load_ticks(product)
    mt_by_ts = load_market_trades(product)
    tick_books = {r["ts"]: ({int(p): int(v) for p, v in r["bids"]},
                            {int(p): int(v) for p, v in r["asks"]})
                  for r in ticks}
    buy_prices = []
    sell_prices = []
    for ts, trades in mt_by_ts.items():
        if ts not in tick_books:
            continue
        bb, ba = tick_books[ts]
        for m in trades:
            t = _mt_to_trade(m)
            s = _trade_side(t.price, bb, ba)
            if s == "BUY":
                buy_prices.append(t.price)
            elif s == "SELL":
                sell_prices.append(t.price)
    return buy_prices, sell_prices


def analyze_training(product, day):
    ticks = load_day_ticks(day)
    trades = load_day_trades(day)
    prod_books = {r["ts"]: ({int(p): int(v) for p, v in r["bids"]},
                            {int(p): int(v) for p, v in r["asks"]})
                  for (p, ts), r in ticks.items() if p == product}
    buy_prices = []
    sell_prices = []
    for (p, ts), tlist in trades.items():
        if p != product:
            continue
        if ts not in prod_books:
            continue
        bb, ba = prod_books[ts]
        for t in tlist:
            s = _trade_side(t.price, bb, ba)
            if s == "BUY":
                buy_prices.append(t.price)
            elif s == "SELL":
                sell_prices.append(t.price)
    return buy_prices, sell_prices


print("=== OSM LIVE 127989 ===")
b, s = analyze_live("ASH_COATED_OSMIUM")
print(f"  BUY takers ({len(b)}): min={min(b)} max={max(b)} mean={sum(b)/len(b):.1f}")
c = Counter(b)
print(f"    price counts: {sorted(c.items())}")
print(f"  SELL takers ({len(s)}): min={min(s)} max={max(s)} mean={sum(s)/len(s):.1f}")
c = Counter(s)
print(f"    price counts: {sorted(c.items())[:8]}  ... {sorted(c.items())[-5:]}")

print("\n=== OSM TRAINING (aggregate -2, -1, 0) ===")
all_b, all_s = [], []
for d in ["-2", "-1", "0"]:
    b, s = analyze_training("ASH_COATED_OSMIUM", d)
    all_b.extend(b)
    all_s.extend(s)
print(f"  BUY takers ({len(all_b)}): min={min(all_b)} max={max(all_b)} mean={sum(all_b)/len(all_b):.1f}")
c = Counter(all_b)
hi = sorted(c.items())[-10:]
print(f"    highest 10 prices: {hi}")
print(f"  SELL takers ({len(all_s)}): min={min(all_s)} max={max(all_s)} mean={sum(all_s)/len(all_s):.1f}")

print("\n=== PEP LIVE 127989 ===")
b, s = analyze_live("INTARIAN_PEPPER_ROOT")
print(f"  BUY takers ({len(b)}): min={min(b)} max={max(b)} mean={sum(b)/len(b):.1f}")
print(f"  SELL takers ({len(s)}): min={min(s)} max={max(s)} mean={sum(s)/len(s):.1f}")
