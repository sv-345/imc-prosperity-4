"""Build per-fill ledger from official R1 artifacts.

Columns:
  timestamp, product, side, size, price,
  mid_at_fill, edge_at_fill,
  mid_plus_10, mid_plus_50, mid_plus_200,
  realized_pnl_fifo,
  adverse_flag_N4_M20, adverse_flag_N2_M10, adverse_flag_N6_M50,
  inv_before, inv_after

Tick convention: server timestamp steps by 100. "10 ticks" = 1000 ts, etc.
"""
from __future__ import annotations
import csv
from collections import deque
from pathlib import Path

ART = Path(__file__).resolve().parent / "artifacts"

# --- 1. Build mid_price lookup from prices_official ---
mids: dict[tuple[int, str], float] = {}
with (ART / "prices_official.csv").open() as f:
    header = f.readline().strip().split(";")
    idx = {k: i for i, k in enumerate(header)}
    for line in f:
        parts = line.strip().split(";")
        if len(parts) < len(header):
            continue
        ts = int(parts[idx["timestamp"]])
        sym = parts[idx["product"]]
        mid_raw = parts[idx["mid_price"]]
        try:
            mid = float(mid_raw)
        except ValueError:
            continue
        # Drop mid=0 rows — these are data artifacts from empty book (both sides missing).
        # Real OSM is ~10000 and PEP is ~13000; mid of 0 is impossible.
        if mid == 0.0:
            continue
        mids[(ts, sym)] = mid

TIMESTAMPS = sorted({ts for (ts, _) in mids.keys()})
TS_SET = set(TIMESTAMPS)

def mid_at(sym: str, ts: int) -> float | None:
    """Mid at exact timestamp if present, else carry last known mid backward."""
    if (ts, sym) in mids:
        return mids[(ts, sym)]
    # linear search bounded — could be optimized but 10k ticks is cheap
    # find nearest <= ts
    best = None
    best_ts = -1
    for t in TIMESTAMPS:
        if t > ts:
            break
        if (t, sym) in mids and t > best_ts:
            best_ts = t
            best = mids[(t, sym)]
    return best

def mid_forward(sym: str, ts_fill: int, delta_ticks: int) -> float | None:
    target = ts_fill + delta_ticks * 100
    # at-or-after target; if past last tick, use last mid
    if target <= TIMESTAMPS[-1]:
        # find first ts >= target with mid for sym
        for t in TIMESTAMPS:
            if t >= target and (t, sym) in mids:
                return mids[(t, sym)]
    # fallback: last mid for sym
    last = None
    for t in TIMESTAMPS:
        if (t, sym) in mids:
            last = mids[(t, sym)]
    return last


# --- 2. Load our fills in timestamp order ---
fills: list[dict] = []
with (ART / "our_fills.csv").open() as f:
    r = csv.DictReader(f)
    for row in r:
        fills.append({
            "timestamp": int(row["timestamp"]),
            "symbol": row["symbol"],
            "side": row["side"],
            "price": float(row["price"]),
            "quantity": int(row["quantity"]),
        })
fills.sort(key=lambda x: (x["timestamp"], x["symbol"], x["side"]))

# --- 3. FIFO realized PnL per fill ---
# Per symbol, maintain a queue of open positions. Each entry: {qty_remaining, price, ref_idx}.
# When a fill offsets inventory, pair against FIFO queue and attribute realized PnL to
# BOTH sides (the opening leg and the closing leg each get half? No — standard FIFO:
# realized PnL is booked on the closing fill. The opening fill has 0 realized until closed.)
# Convention: assign the full realized_pnl from the match to the closing fill row.
# Positions that never closed contribute nothing to realized_pnl. They'll show up under
# "unrealized / open inventory" in leaks.md.

per_symbol_queue: dict[str, deque] = {"ASH_COATED_OSMIUM": deque(), "INTARIAN_PEPPER_ROOT": deque()}
per_symbol_inv: dict[str, int] = {"ASH_COATED_OSMIUM": 0, "INTARIAN_PEPPER_ROOT": 0}
realized: list[float] = [0.0] * len(fills)
inv_before: list[int] = [0] * len(fills)
inv_after: list[int] = [0] * len(fills)

for i, fl in enumerate(fills):
    sym = fl["symbol"]
    q = fl["quantity"]
    p = fl["price"]
    side = fl["side"]
    inv_before[i] = per_symbol_inv[sym]
    dq = per_symbol_queue[sym]

    # Signed quantity: + for buy, - for sell
    signed = q if side == "BUY" else -q
    remaining = abs(signed)
    pnl_this = 0.0

    # If inventory is opposite-signed, we are closing; else opening.
    cur_inv = per_symbol_inv[sym]
    # Direction of this fill vs inventory:
    #   If inventory >0 (long) and we SELL, close; close-pnl = (fill_price - open_price) * qty
    #   If inventory <0 (short) and we BUY, close; close-pnl = (open_price - fill_price) * qty
    while remaining > 0 and dq:
        head = dq[0]
        head_qty = head["qty"]
        head_price = head["price"]
        head_side = head["side"]  # side that opened this lot (BUY=long, SELL=short)
        # Can this fill close head?
        if head_side == side:
            # same direction; can't close, stop
            break
        match_qty = min(head_qty, remaining)
        if head_side == "BUY":
            # we were long; selling now
            pnl_this += (p - head_price) * match_qty
        else:
            # we were short; buying now
            pnl_this += (head_price - p) * match_qty
        head["qty"] -= match_qty
        remaining -= match_qty
        if head["qty"] == 0:
            dq.popleft()

    if remaining > 0:
        # opens new position (in current fill's direction)
        dq.append({"qty": remaining, "price": p, "side": side})

    per_symbol_inv[sym] = cur_inv + signed
    inv_after[i] = per_symbol_inv[sym]
    realized[i] = pnl_this


# --- 4. Adverse selection flags ---
# N = threshold in ticks of adverse move against us
# M = window in ticks (where 1 tick = 1 book update = 100 ts)
# Adverse:
#   BUY fill is adverse if min(mid) within next M ticks drops by ≥ N below fill price.
#   SELL fill is adverse if max(mid) within next M ticks rises by ≥ N above fill price.
# Note: we compare against the fill price (aggressive definition — measures immediate loss).
# An alternative uses mid_at_fill as the reference; we report both N/M pairs.

def min_mid_in_window(sym: str, ts0: int, m_ticks: int) -> float | None:
    t_end = ts0 + m_ticks * 100
    lo = None
    for t in TIMESTAMPS:
        if t <= ts0:
            continue
        if t > t_end:
            break
        v = mids.get((t, sym))
        if v is None:
            continue
        lo = v if lo is None else min(lo, v)
    return lo

def max_mid_in_window(sym: str, ts0: int, m_ticks: int) -> float | None:
    t_end = ts0 + m_ticks * 100
    hi = None
    for t in TIMESTAMPS:
        if t <= ts0:
            continue
        if t > t_end:
            break
        v = mids.get((t, sym))
        if v is None:
            continue
        hi = v if hi is None else max(hi, v)
    return hi


# --- 5. Build rows ---
out_rows = []
# Pre-pair (ts, sym) to speed up mid_at by bisect
import bisect
ts_sorted = TIMESTAMPS
def mid_at_fast(sym: str, ts: int) -> float | None:
    # find latest t <= ts
    i = bisect.bisect_right(ts_sorted, ts) - 1
    while i >= 0:
        t = ts_sorted[i]
        v = mids.get((t, sym))
        if v is not None:
            return v
        i -= 1
    return None

def mid_forward_fast(sym: str, ts_fill: int, delta_ticks: int) -> float | None:
    target = ts_fill + delta_ticks * 100
    i = bisect.bisect_left(ts_sorted, target)
    while i < len(ts_sorted):
        t = ts_sorted[i]
        v = mids.get((t, sym))
        if v is not None:
            return v
        i += 1
    # past end, use last
    for i in range(len(ts_sorted) - 1, -1, -1):
        t = ts_sorted[i]
        v = mids.get((t, sym))
        if v is not None:
            return v
    return None

def min_in_fast(sym: str, ts0: int, m: int) -> float | None:
    t_end = ts0 + m * 100
    i = bisect.bisect_right(ts_sorted, ts0)
    lo = None
    while i < len(ts_sorted) and ts_sorted[i] <= t_end:
        v = mids.get((ts_sorted[i], sym))
        if v is not None:
            lo = v if lo is None else min(lo, v)
        i += 1
    return lo

def max_in_fast(sym: str, ts0: int, m: int) -> float | None:
    t_end = ts0 + m * 100
    i = bisect.bisect_right(ts_sorted, ts0)
    hi = None
    while i < len(ts_sorted) and ts_sorted[i] <= t_end:
        v = mids.get((ts_sorted[i], sym))
        if v is not None:
            hi = v if hi is None else max(hi, v)
        i += 1
    return hi

ADVERSE_CONFIGS = [
    ("adverse_N4_M20", 4, 20),
    ("adverse_N2_M10", 2, 10),
    ("adverse_N6_M50", 6, 50),
]

for i, fl in enumerate(fills):
    sym = fl["symbol"]
    ts = fl["timestamp"]
    side = fl["side"]
    price = fl["price"]
    qty = fl["quantity"]

    mid_fill = mid_at_fast(sym, ts)
    # edge: mid - price for buys, price - mid for sells (positive = good)
    if mid_fill is None:
        edge = None
    else:
        edge = (mid_fill - price) if side == "BUY" else (price - mid_fill)

    m10 = mid_forward_fast(sym, ts, 10)
    m50 = mid_forward_fast(sym, ts, 50)
    m200 = mid_forward_fast(sym, ts, 200)

    adverse_flags = {}
    for name, N, M in ADVERSE_CONFIGS:
        if side == "BUY":
            lo = min_in_fast(sym, ts, M)
            adverse_flags[name] = 1 if (lo is not None and price - lo >= N) else 0
        else:  # SELL
            hi = max_in_fast(sym, ts, M)
            adverse_flags[name] = 1 if (hi is not None and hi - price >= N) else 0

    out_rows.append({
        "timestamp": ts,
        "product": sym,
        "side": side,
        "size": qty,
        "price": price,
        "mid_at_fill": mid_fill,
        "edge_at_fill": edge,
        "mid_plus_10": m10,
        "mid_plus_50": m50,
        "mid_plus_200": m200,
        "realized_pnl_fifo": realized[i],
        **adverse_flags,
        "inv_before": inv_before[i],
        "inv_after": inv_after[i],
    })


# --- 6. Write ledger ---
ledger_csv = ART / "ledger.csv"
fieldnames = [
    "timestamp", "product", "side", "size", "price",
    "mid_at_fill", "edge_at_fill",
    "mid_plus_10", "mid_plus_50", "mid_plus_200",
    "realized_pnl_fifo",
    "adverse_N4_M20", "adverse_N2_M10", "adverse_N6_M50",
    "inv_before", "inv_after",
]
with ledger_csv.open("w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=fieldnames)
    w.writeheader()
    for r in out_rows:
        w.writerow(r)


# --- 7. Summary stats ---
total_realized = sum(r["realized_pnl_fifo"] for r in out_rows)
# Open positions at end
open_inv = per_symbol_inv
# MTM at end of session for open positions
last_mids = {s: mid_forward_fast(s, TIMESTAMPS[-1], 0) for s in open_inv}
# MTM against final mid minus avg open price in queue
open_value_by_sym = {}
for sym, dq in per_symbol_queue.items():
    if not dq:
        open_value_by_sym[sym] = 0.0
        continue
    total = 0.0
    total_qty = 0
    # unrealized = for longs, (last_mid - open_price) * qty; for shorts opposite
    last_mid = last_mids[sym]
    for lot in dq:
        if lot["side"] == "BUY":
            total += (last_mid - lot["price"]) * lot["qty"]
            total_qty += lot["qty"]
        else:
            total += (lot["price"] - last_mid) * lot["qty"]
            total_qty -= lot["qty"]
    open_value_by_sym[sym] = total

summary = {
    "n_fills": len(out_rows),
    "total_realized_pnl_fifo": total_realized,
    "end_inventory": open_inv,
    "end_unrealized_mtm_by_symbol": open_value_by_sym,
    "fills_by_symbol_side": {},
    "sum_adverse_N4_M20": sum(r["adverse_N4_M20"] for r in out_rows),
    "sum_adverse_N2_M10": sum(r["adverse_N2_M10"] for r in out_rows),
    "sum_adverse_N6_M50": sum(r["adverse_N6_M50"] for r in out_rows),
    "official_profit": 101199.6875,
}
for sym in ("ASH_COATED_OSMIUM", "INTARIAN_PEPPER_ROOT"):
    for s in ("BUY", "SELL"):
        n = sum(1 for r in out_rows if r["product"] == sym and r["side"] == s)
        q = sum(r["size"] for r in out_rows if r["product"] == sym and r["side"] == s)
        summary["fills_by_symbol_side"][f"{sym}_{s}"] = {"count": n, "qty": q}

import json
with (ART / "ledger_summary.json").open("w") as f:
    json.dump(summary, f, indent=2, default=str)

print(json.dumps(summary, indent=2, default=str))
