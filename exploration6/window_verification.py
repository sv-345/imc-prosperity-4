"""Verify phase 3 concentration at the precise windows 34.3K-48.1K and 76.1K-90.1K.

On training data (3 days × 1M ts/day), these windows occupy ts 34,300-48,100
and 76,100-90,100 ON EACH DAY (assuming daily reset). Also check scaled
equivalents: same fraction at the day-scale (3.43-4.81M ts and 7.61-9.01M ts)
if the leaderboard curve was plotted at day-scale.

Runs iter25_tb1 and tallies phase 3 tape qty/notional in:
  - inside the raw server-scale windows (ts 34.3K-48.1K, 76.1K-90.1K)
  - inside day-scale equivalents (ts 343K-481K, 761K-901K)
  - outside both
"""
import sys, json
from collections import defaultdict
from pathlib import Path

ROOT = Path("/Users/svelaga/Documents/IMC Prosperity")
BT_ROOT = ROOT / "chrispyroberts-imc-prosperity-4/backtester"
DATA_ROOT = ROOT / "chrispyroberts-imc-prosperity-4/data"

sys.path.insert(0, str(BT_ROOT))
sys.path.insert(0, str(ROOT / "exploration4"))

from prosperity3bt import runner as rnr
import prosperity3bt.datamodel as _dm
sys.modules.setdefault("datamodel", _dm)
from prosperity3bt.file_reader import FileSystemReader
from prosperity3bt.models import TradeMatchingMode

# Instrumentation: log every phase 3 fill with ts, sym, side, qty, our_price
FILLS = []
_orig_buy = rnr.match_buy_order
_orig_sell = rnr.match_sell_order


def _bp(state, data, order, mt, tmm):
    order_depth = state.order_depths[order.symbol]
    # phase 2 match
    from prosperity3bt.datamodel import Trade
    trades = []
    price_matches = sorted(p for p in order_depth.sell_orders.keys() if p <= order.price)
    for price in price_matches:
        v = min(order.quantity, abs(order_depth.sell_orders[price]))
        trades.append(Trade(order.symbol, price, v, "SUBMISSION", "", state.timestamp))
        state.position[order.symbol] = state.position.get(order.symbol, 0) + v
        data.profit_loss[order.symbol] -= price * v
        order_depth.sell_orders[price] += v
        if order_depth.sell_orders[price] == 0:
            order_depth.sell_orders.pop(price)
        order.quantity -= v
        if order.quantity == 0: return trades
    if tmm == TradeMatchingMode.none: return trades
    for m in mt:
        if m.sell_quantity == 0 or m.trade.price > order.price or \
           (m.trade.price == order.price and tmm == TradeMatchingMode.worse):
            continue
        v = min(order.quantity, m.sell_quantity)
        trades.append(Trade(order.symbol, order.price, v, "SUBMISSION", m.trade.seller, state.timestamp))
        FILLS.append({"ts": state.timestamp, "sym": order.symbol, "side": "BUY",
                      "qty": v, "price": order.price, "tape_price": m.trade.price})
        state.position[order.symbol] = state.position.get(order.symbol, 0) + v
        data.profit_loss[order.symbol] -= order.price * v
        m.sell_quantity -= v
        order.quantity -= v
        if order.quantity == 0: return trades
    return trades


def _sp(state, data, order, mt, tmm):
    order_depth = state.order_depths[order.symbol]
    from prosperity3bt.datamodel import Trade
    trades = []
    price_matches = sorted((p for p in order_depth.buy_orders.keys() if p >= order.price), reverse=True)
    for price in price_matches:
        v = min(abs(order.quantity), order_depth.buy_orders[price])
        trades.append(Trade(order.symbol, price, v, "", "SUBMISSION", state.timestamp))
        state.position[order.symbol] = state.position.get(order.symbol, 0) - v
        data.profit_loss[order.symbol] += price * v
        order_depth.buy_orders[price] -= v
        if order_depth.buy_orders[price] == 0: order_depth.buy_orders.pop(price)
        order.quantity += v
        if order.quantity == 0: return trades
    if tmm == TradeMatchingMode.none: return trades
    for m in mt:
        if m.buy_quantity == 0 or m.trade.price < order.price or \
           (m.trade.price == order.price and tmm == TradeMatchingMode.worse):
            continue
        v = min(abs(order.quantity), m.buy_quantity)
        trades.append(Trade(order.symbol, order.price, v, m.trade.buyer, "SUBMISSION", state.timestamp))
        FILLS.append({"ts": state.timestamp, "sym": order.symbol, "side": "SELL",
                      "qty": v, "price": order.price, "tape_price": m.trade.price})
        state.position[order.symbol] = state.position.get(order.symbol, 0) - v
        data.profit_loss[order.symbol] += order.price * v
        m.buy_quantity -= v
        order.quantity += v
        if order.quantity == 0: return trades
    return trades


rnr.match_buy_order = _bp
rnr.match_sell_order = _sp


# server-scale windows (ts in [34300,48100], [76100, 90100])
# day-scale windows (×10): [343000,481000], [761000, 901000]
SERVER_W = [(34300, 48100), (76100, 90100)]
DAY_W = [(343000, 481000), (761000, 901000)]


def in_windows(ts, windows):
    for lo, hi in windows:
        if lo <= ts <= hi:
            return True
    return False


def run_day(day):
    FILLS.clear()
    sys.path.insert(0, str(ROOT / "exploration4"))
    import importlib
    import iter25_tb1
    importlib.reload(iter25_tb1)
    reader = FileSystemReader(DATA_ROOT)
    trader = iter25_tb1.Trader()
    rnr.run_backtest(trader, reader, 2, day, False, TradeMatchingMode.all, True, False)
    return list(FILLS)


totals = {
    "server_windows": defaultdict(lambda: defaultdict(int)),  # sym -> side -> qty
    "day_windows": defaultdict(lambda: defaultdict(int)),
    "outside": defaultdict(lambda: defaultdict(int)),
}
notional = {k: defaultdict(float) for k in totals}
ticks_per_day = 10000

for day in (-1, 0, 1):
    fs = run_day(day)
    print(f"\nDay {day}: {len(fs)} phase 3 fills")
    for f in fs:
        ts = f["ts"]
        edge = abs(f["price"] - 10001) if f["sym"] == "ASH_COATED_OSMIUM" else None
        qty = f["qty"]
        if in_windows(ts, SERVER_W):
            totals["server_windows"][f["sym"]][f["side"]] += qty
            notional["server_windows"][f["sym"]] += qty * f["price"]
        elif in_windows(ts, DAY_W):
            totals["day_windows"][f["sym"]][f["side"]] += qty
            notional["day_windows"][f["sym"]] += qty * f["price"]
        else:
            totals["outside"][f["sym"]][f["side"]] += qty
            notional["outside"][f["sym"]] += qty * f["price"]


# Width in ts: server = 13800+14000 = 27800 ts/day out of 1000000
server_width_frac = (48100-34300 + 90100-76100) / 1000000
day_width_frac = (481000-343000 + 901000-761000) / 1000000
outside_frac = 1 - server_width_frac - day_width_frac

print(f"\n=== Phase 3 qty by window (3-day total) ===")
print(f"(Width share of day: server_windows={server_width_frac:.2%} day_windows={day_width_frac:.2%} outside={outside_frac:.2%})\n")
for bucket in ("server_windows", "day_windows", "outside"):
    print(f"--- {bucket} ---")
    for sym in ("ASH_COATED_OSMIUM", "INTARIAN_PEPPER_ROOT"):
        buy = totals[bucket][sym].get("BUY", 0)
        sell = totals[bucket][sym].get("SELL", 0)
        total = buy + sell
        if total == 0: continue
        print(f"  {sym}: buy={buy:>5} sell={sell:>5} total={total:>5} (net={buy-sell:+})")

# Concentration ratio: if flat, server_windows would have 2.78% of qty. If
# concentrated, much higher.
print("\n=== Concentration metrics (3-day total) ===")
all_q = defaultdict(int)
for bucket in totals:
    for sym, sides in totals[bucket].items():
        all_q[sym] += sum(sides.values())
for bucket in ("server_windows", "day_windows", "outside"):
    for sym in ("ASH_COATED_OSMIUM", "INTARIAN_PEPPER_ROOT"):
        q = sum(totals[bucket][sym].values())
        if all_q[sym] == 0: continue
        pct = q / all_q[sym]
        if bucket == "server_windows":
            expected = server_width_frac
        elif bucket == "day_windows":
            expected = day_width_frac
        else:
            expected = outside_frac
        ratio = pct / expected if expected > 0 else 0
        print(f"  {sym:22s} {bucket:16s}: {pct:.2%} qty (expected under uniform {expected:.2%})  concentration x{ratio:.2f}")

# save raw
Path(__file__).parent.joinpath("window_evidence.json").write_text(
    json.dumps({k: {s: dict(v) for s, v in d.items()} for k, d in totals.items()}, indent=2))
