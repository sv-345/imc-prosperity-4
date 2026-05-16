"""Tape-price distribution vs FV and vs our quotes, for exploitation sizing.

Reruns iter25_tb1 and collects: for every tape trade at tick t, the price
relative to FV (OSM_FV=10001, PEP fv from tb1) and to our best bid/ask.
Also computes the conditional: given take_sig at t, what does tape look like
at t+0 (same tick, post-Trader.run)?
"""

import sys, json
from collections import defaultdict
from pathlib import Path

ROOT = Path("<repo>")
BT_ROOT = ROOT / "chrispyroberts-imc-prosperity-4/backtester"
DATA_ROOT = ROOT / "chrispyroberts-imc-prosperity-4/data"
ALGO = ROOT / "exploration4/iter25_tb1.py"

sys.path.insert(0, str(BT_ROOT))
sys.path.insert(0, str(ALGO.parent))

from prosperity3bt import runner as rnr
import prosperity3bt.datamodel as _dm
sys.modules.setdefault("datamodel", _dm)
from prosperity3bt.file_reader import FileSystemReader
from prosperity3bt.models import TradeMatchingMode

TAPE = []  # per-tape dict

_orig_match_orders = rnr.match_orders
def _mo(state, data, orders, result, tmm):
    ts = state.timestamp
    for sym, olist in orders.items():
        od = state.order_depths.get(sym)
        if not od or not od.buy_orders or not od.sell_orders:
            continue
        bb = max(od.buy_orders); ba = min(od.sell_orders)
        mid = (bb + ba) / 2.0
        our_bids = [o.price for o in olist if o.quantity > 0]
        our_asks = [o.price for o in olist if o.quantity < 0]
        our_bb = max(our_bids) if our_bids else None
        our_ba = min(our_asks) if our_asks else None
        for t in data.trades[ts].get(sym, []):
            buyer = t.buyer or ""; seller = t.seller or ""
            if "SUBMISSION" in buyer or "SUBMISSION" in seller:
                continue
            TAPE.append({
                "ts": ts, "sym": sym, "price": t.price, "qty": t.quantity,
                "mid": mid, "dev_from_mid": t.price - mid,
                "our_bb": our_bb, "our_ba": our_ba,
                "above_our_ba": (our_ba is not None and t.price >= our_ba),
                "below_our_bb": (our_bb is not None and t.price <= our_bb),
                "buyer": buyer, "seller": seller,
            })
    return _orig_match_orders(state, data, orders, result, tmm)

rnr.match_orders = _mo

import iter25_tb1
reader = FileSystemReader(DATA_ROOT)
for day in (-1, 0, 1):
    trader = iter25_tb1.Trader()
    rnr.run_backtest(trader, reader, 2, day, False, TradeMatchingMode.all, True, False)

# Aggregate
per_prod = defaultdict(lambda: {"n": 0, "qty": 0, "above_ba": 0, "below_bb": 0,
                                 "buyer_named": 0, "seller_named": 0,
                                 "dev_hist": defaultdict(int)})
for t in TAPE:
    p = per_prod[t["sym"]]
    p["n"] += 1; p["qty"] += t["qty"]
    if t["above_our_ba"]: p["above_ba"] += t["qty"]
    if t["below_our_bb"]: p["below_bb"] += t["qty"]
    if t["buyer"]: p["buyer_named"] += 1
    if t["seller"]: p["seller_named"] += 1
    # bucket dev_from_mid into [-inf,-5), [-5,-3), [-3,-1), [-1,1], (1,3], (3,5], (5,inf)
    d = t["dev_from_mid"]
    if d < -5: b = "(-inf,-5)"
    elif d < -3: b = "[-5,-3)"
    elif d < -1: b = "[-3,-1)"
    elif d <= 1: b = "[-1,1]"
    elif d <= 3: b = "(1,3]"
    elif d <= 5: b = "(3,5]"
    else: b = "(5,inf)"
    p["dev_hist"][b] += t["qty"]

print(f"Total tape events (non-SUBMISSION): {len(TAPE)}")
print()
for sym, s in per_prod.items():
    print(f"=== {sym} ===")
    print(f"  tape_n={s['n']} tape_qty={s['qty']}")
    print(f"  above our ASK (would fill our ask): qty={s['above_ba']} ({s['above_ba']/max(s['qty'],1):.1%})")
    print(f"  below our BID (would fill our bid): qty={s['below_bb']} ({s['below_bb']/max(s['qty'],1):.1%})")
    print(f"  buyer_named={s['buyer_named']}  seller_named={s['seller_named']}")
    print("  tape_price - mid distribution:")
    total = sum(s["dev_hist"].values())
    for b in ["(-inf,-5)", "[-5,-3)", "[-3,-1)", "[-1,1]", "(1,3]", "(3,5]", "(5,inf)"]:
        q = s["dev_hist"].get(b, 0)
        print(f"    {b:>12}: {q:>6} ({q/max(total,1):.1%})")
    print()

out = Path(__file__).parent / "tape_distribution.json"
json.dump({sym: {k: (dict(v) if isinstance(v, defaultdict) else v) for k, v in s.items()}
           for sym, s in per_prod.items()}, open(out, "w"), indent=2)
print(f"saved {out}")
