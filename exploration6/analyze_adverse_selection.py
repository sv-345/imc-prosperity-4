"""Find adverse-selection signatures in iter30 server log.

For each fill, look at book state BEFORE the fill (same ts, from activities).
Compare book imbalance, spread, etc. — can we predict which side gets toxic?

A fill is 'toxic' if:
  - our BUY at price P, mid moves UP within next ~3 ticks (stale cheap)
  - our SELL at price P, mid moves DOWN within next ~3 ticks (stale high)
"""
import json
from collections import defaultdict
from pathlib import Path

raw = json.loads(Path("/tmp/prosperity_logs/332955/342005.log").read_text())

act = raw["activitiesLog"].strip().split("\n")[1:]
book = defaultdict(dict)
mids = defaultdict(dict)  # ts -> prod -> mid
for ln in act:
    f = ln.split(";")
    try:
        ts = int(f[1]); prod = f[2]
        bids = [(int(f[3]), int(f[4])) if f[3] else None,
                (int(f[5]), int(f[6])) if f[5] else None,
                (int(f[7]), int(f[8])) if f[7] else None]
        asks = [(int(f[9]), int(f[10])) if f[9] else None,
                (int(f[11]), int(f[12])) if f[11] else None,
                (int(f[13]), int(f[14])) if f[13] else None]
        mid = float(f[15]) if f[15] else None
        book[ts][prod] = {
            "bids": [b for b in bids if b is not None],
            "asks": [a for a in asks if a is not None],
            "mid": mid,
        }
        mids[prod][ts] = mid
    except (ValueError, IndexError):
        continue

trades = raw["tradeHistory"]

# Compute forward mid delta at +3 ticks
def forward_mid_delta(prod, ts, ticks=3):
    future_ts = ts + ticks * 100
    m0 = mids[prod].get(ts)
    mf = mids[prod].get(future_ts)
    if m0 is None or mf is None:
        return None
    return mf - m0

# For each own fill: compute toxic score
toxic_buys = []
toxic_sells = []
good_buys = []
good_sells = []
for t in trades:
    ts = t["timestamp"]; prod = t["symbol"]; price = t["price"]
    side = "BUY" if t["buyer"] == "SUBMISSION" else "SELL"
    b = book.get(ts, {}).get(prod, {})
    mid = b.get("mid")
    fmd = forward_mid_delta(prod, ts, 3)
    if mid is None or fmd is None:
        continue

    # Book imbalance
    bid_vol = sum(x[1] for x in b["bids"]) if b["bids"] else 0
    ask_vol = sum(x[1] for x in b["asks"]) if b["asks"] else 0
    total = bid_vol + ask_vol
    imb = (bid_vol - ask_vol) / total if total else 0  # >0 = buyers dominate

    # Spread
    bb = max(x[0] for x in b["bids"]) if b["bids"] else None
    ba = min(x[0] for x in b["asks"]) if b["asks"] else None
    spread = ba - bb if bb is not None and ba is not None else None

    if side == "BUY":
        # toxic if mid drops (we bought too high — actually no, we want mid to RISE after buying)
        is_toxic = fmd < -1  # mid drops > 1 after we buy
        d = {"ts": ts, "prod": prod, "price": price, "mid": mid, "fmd": fmd,
             "imb": imb, "spread": spread, "qty": t["quantity"]}
        (toxic_buys if is_toxic else good_buys).append(d)
    else:
        # toxic if mid rises (we sold too cheap)
        is_toxic = fmd > 1
        d = {"ts": ts, "prod": prod, "price": price, "mid": mid, "fmd": fmd,
             "imb": imb, "spread": spread, "qty": t["quantity"]}
        (toxic_sells if is_toxic else good_sells).append(d)


print(f"BUY fills: toxic (mid drops after) = {len(toxic_buys)}  good = {len(good_buys)}")
print(f"SELL fills: toxic (mid rises after) = {len(toxic_sells)}  good = {len(good_sells)}")

# Mean imbalance and spread, toxic vs good
def avg(arr, k):
    vals = [x[k] for x in arr if x[k] is not None]
    return sum(vals) / len(vals) if vals else None


print(f"\n=== Book imbalance (bid_vol - ask_vol) / total ===")
print(f"  toxic BUY  (mid fell after our buy):  imb = {avg(toxic_buys, 'imb'):+.3f}")
print(f"  good  BUY  (mid rose after our buy):  imb = {avg(good_buys, 'imb'):+.3f}")
print(f"  toxic SELL (mid rose after our sell): imb = {avg(toxic_sells, 'imb'):+.3f}")
print(f"  good  SELL (mid fell after our sell): imb = {avg(good_sells, 'imb'):+.3f}")

print(f"\n=== Spread ===")
print(f"  toxic BUY:  spread = {avg(toxic_buys, 'spread'):.2f}")
print(f"  good  BUY:  spread = {avg(good_buys, 'spread'):.2f}")
print(f"  toxic SELL: spread = {avg(toxic_sells, 'spread'):.2f}")
print(f"  good  SELL: spread = {avg(good_sells, 'spread'):.2f}")

print(f"\n=== Forward mid delta (at +3 ticks) ===")
print(f"  toxic BUY:  fmd = {avg(toxic_buys, 'fmd'):+.2f}")
print(f"  good  BUY:  fmd = {avg(good_buys, 'fmd'):+.2f}")
print(f"  toxic SELL: fmd = {avg(toxic_sells, 'fmd'):+.2f}")
print(f"  good  SELL: fmd = {avg(good_sells, 'fmd'):+.2f}")

# Per product
print(f"\n=== Per product toxic rates ===")
for prod in ("ASH_COATED_OSMIUM", "INTARIAN_PEPPER_ROOT"):
    tb = sum(1 for x in toxic_buys if x['prod'] == prod)
    gb = sum(1 for x in good_buys if x['prod'] == prod)
    ts_s = sum(1 for x in toxic_sells if x['prod'] == prod)
    gs = sum(1 for x in good_sells if x['prod'] == prod)
    tbq = sum(x['qty'] for x in toxic_buys if x['prod'] == prod)
    tsq = sum(x['qty'] for x in toxic_sells if x['prod'] == prod)
    gbq = sum(x['qty'] for x in good_buys if x['prod'] == prod)
    gsq = sum(x['qty'] for x in good_sells if x['prod'] == prod)
    print(f"  {prod}:")
    print(f"    BUY  toxic={tb}({tbq}q) good={gb}({gbq}q)  ratio qty={tbq/max(tbq+gbq,1):.1%}")
    print(f"    SELL toxic={ts_s}({tsq}q) good={gs}({gsq}q)  ratio qty={tsq/max(tsq+gsq,1):.1%}")
