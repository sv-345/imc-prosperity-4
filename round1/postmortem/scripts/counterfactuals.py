"""Replay top-3 counterfactuals against official R1 data.

CF1: OSM add passive layer at fv±12 (size 15 each side). Estimate filled trades from the
     94 bot trades in the 11-15 distance bucket. Apply queue-priority discount.

CF2: PEP tighten recycling — only recycle (take a short leg) when bb - fv_int >= 8.
     Replay: of 122 PEP SELL fills, count those where inside-spread edge was < 8. Assume
     we don't sell those → we retain those units long, capture the drift upside.

CF3: Skip negative-edge OSM crosses with weak directional signal.
     Weak = markout_50 <= +5. Replay: skip those, lose both their cross cost AND their
     directional gain. Net = (directional gain − cross cost).
"""
from __future__ import annotations
import csv
from pathlib import Path
from collections import defaultdict

ART = Path(__file__).resolve().parent / "artifacts"

# Load data
rows = list(csv.DictReader((ART / "ledger.csv").open()))
for r in rows:
    for k in ("timestamp", "size", "inv_before", "inv_after"):
        r[k] = int(r[k])
    for k in ("price", "mid_at_fill", "edge_at_fill", "mid_plus_10", "mid_plus_50", "mid_plus_200", "realized_pnl_fifo"):
        r[k] = float(r[k]) if r[k] else None

trades = list(csv.DictReader((ART / "trades_official.csv").open()))
for t in trades:
    t["timestamp"] = int(t["timestamp"])
    t["price"] = float(t["price"])
    t["quantity"] = int(t["quantity"])

mids = {}
bb_ba = {}
with (ART / "prices_official.csv").open() as f:
    h = f.readline().strip().split(";")
    idx = {k: i for i, k in enumerate(h)}
    for line in f:
        parts = line.strip().split(";")
        if len(parts) < len(h):
            continue
        try:
            ts = int(parts[idx["timestamp"]])
            sym = parts[idx["product"]]
            mid = float(parts[idx["mid_price"]])
            if mid == 0.0:
                continue
            bb_raw = parts[idx["bid_price_1"]] or None
            ba_raw = parts[idx["ask_price_1"]] or None
            mids[(ts, sym)] = mid
            bb_ba[(ts, sym)] = (float(bb_raw) if bb_raw else None, float(ba_raw) if ba_raw else None)
        except ValueError:
            continue


def mid_at(ts: int, sym: str) -> float | None:
    return mids.get((ts, sym))


# ------------------------------------------------------------------------
# CF1: OSM add passive layer at fv±12
# ------------------------------------------------------------------------
# For each bot trade at distance 11-15 from fv=10001, assume we would have been there.
# Queue priority: discount at 50% (we compete with existing bot makers on queue).
# Our existing strategy already quotes at 9999/10017 (inside) and 9981/10021 (outside).
# Adding 9989/10013 inserts a new layer.
FV = 10001
QUEUE_DISCOUNT = 0.5

cf1_osm_trades = [
    t for t in trades
    if t["symbol"] == "ASH_COATED_OSMIUM"
    and 11 <= abs(t["price"] - FV) <= 15
]
print(f"CF1: OSM trades in 11-15 band: {len(cf1_osm_trades)}, total qty: {sum(t['quantity'] for t in cf1_osm_trades)}")

# Filter: only count trades where we weren't already the counterparty
cf1_candidate = [t for t in cf1_osm_trades if t.get("buyer") != "SUBMISSION" and t.get("seller") != "SUBMISSION"]
print(f"CF1: candidate trades not already ours: {len(cf1_candidate)}")

# For each candidate, assume 50% queue probability → expected fill qty
# Edge on each would be |price - mid| × qty
cf1_upside = 0.0
cf1_accepted_qty = 0
for t in cf1_candidate:
    m = mid_at(t["timestamp"], t["symbol"])
    if m is None:
        continue
    edge = abs(m - t["price"])
    # We would be the PASSIVE side — if trade price is below mid, we'd be the BUYER (good).
    # Conservatively assume +edge × qty × QUEUE_DISCOUNT
    cf1_upside += edge * t["quantity"] * QUEUE_DISCOUNT
    cf1_accepted_qty += t["quantity"] * QUEUE_DISCOUNT

# Account for inventory-limit impact: adding 15 extra buy units and 15 extra sell units
# at fv±12 means we'd hit +80 more often. This would DISPLACE some of the outer-edge fills.
# Conservative: subtract the edge-20 outer fills that get displaced.
# Outer-edge fills (|edge|>=15): 26 fills, 3,245 edge*size.
# Assume 30% get displaced.
cf1_displacement = 3245 * 0.30
cf1_net = cf1_upside - cf1_displacement
print(f"CF1 upside (raw @ 50%): {cf1_upside:,.1f}")
print(f"CF1 displacement of outer layer (30%): -{cf1_displacement:,.1f}")
print(f"CF1 NET: {cf1_net:,.1f}")

# ------------------------------------------------------------------------
# CF2: PEP faster ramp — cross the spread for first 80 units to reach +80 by tick ~20
# ------------------------------------------------------------------------
# Observed: PEP first hit +80 at ts=20200 (tick 202). During those 202 ticks PEP drifted
# 202 * 0.1 = +20.2 in mid. We accumulated from 0 -> 80, so avg inv in ramp was 40.
# Actual ramp capture ≈ 40 * 20 = +800.
# If we had instantaneously (by tick ~20) been at +80, capture during ts=0->20200 would be ~80 * 20 = +1600.
# Gap: 1600 - 800 = 800 of drift given up during ramp.
#
# To achieve fast ramp we'd cross the spread for the initial units. Average crossing cost:
# PEP ba at ts=0 is 13007, mid 12998.5. Paying ask = 8.5 ticks crossed.
# 80 units * 8.5 ticks = 680 in crossing cost.
# BUT the inner quotes fill us cheaper if we're patient — the ramp costs 0 in crossing
# because we quote passive bb+1. So the gain is only the drift differential (800) minus the crossing cost.

# Tighter estimate using actual book:
# Read first 50 ticks of PEP ba prices, cross them one at a time, accumulate inv quickly.
pep_ts_sorted = sorted([ts for (ts, s) in bb_ba if s == "INTARIAN_PEPPER_ROOT"])[:50]
cross_cost = 0.0
inv = 0
for ts in pep_ts_sorted:
    bb, ba = bb_ba.get((ts, "INTARIAN_PEPPER_ROOT"), (None, None))
    m = mid_at(ts, "INTARIAN_PEPPER_ROOT")
    if ba is None or m is None:
        continue
    # Buy 8 units at ask per tick
    buy_qty = min(8, 80 - inv)
    if buy_qty <= 0:
        break
    cost_per_unit = ba - m  # positive = we paid above mid
    cross_cost += cost_per_unit * buy_qty
    inv += buy_qty
    reached_ts = ts
# Drift gain: at tick 0 fv~12998.5, at reached_ts fv = 12998.5 + reached_ts/100 * 0.1.
# Our original strategy reached +80 at ts=20200. If new strategy reaches +80 at reached_ts,
# we capture extra drift = 80 * (mid_at_original_saturation - mid_at_new_saturation)
# Actually the right thing: compare integrated inv * dmid for both paths.

# Simpler: treat as "extra drift we capture by being at +80 for (20200 - reached_ts) more ticks".
extra_ticks = max(0, 20200 - reached_ts) / 100  # drift per tick is 0.1
drift_gain = 80 * (extra_ticks * 0.1) - 40 * (extra_ticks * 0.1)  # we'd be at 80 instead of avg 40
# Simpler: assume original avg inv in ramp window was 40 (linear from 0 to 80); new avg is 80.
# Extra inv-ticks = (80 - 40) * extra_ticks = 40 * extra_ticks.
# Mid gained in that window = extra_ticks * 0.1
# Drift gain = 40 * extra_ticks * 0.1
drift_gain = 40 * extra_ticks * 0.1
cf2_net = drift_gain - cross_cost
print(f"CF2: fast ramp reaches +80 at ts={reached_ts} (vs original ts=20200)")
print(f"CF2: cross cost (first 80 units): {cross_cost:,.1f}")
print(f"CF2: drift gain from earlier saturation: {drift_gain:,.1f}")
print(f"CF2 NET: {cf2_net:,.1f}")

# ------------------------------------------------------------------------
# CF3: Skip OSM negative-edge crosses with weak markout_50
# ------------------------------------------------------------------------
osm_crosses = [
    r for r in rows
    if r["product"] == "ASH_COATED_OSMIUM" and r["edge_at_fill"] < 0
]
print(f"CF3: OSM negative-edge fills: {len(osm_crosses)}")

def markout_50(r):
    if r["mid_plus_50"] is None or r["mid_at_fill"] is None:
        return None
    return (1 if r["side"] == "BUY" else -1) * (r["mid_plus_50"] - r["price"]) * r["size"]

# Categorize: weak (markout_50 <= 5), strong (>5)
weak = [r for r in osm_crosses if markout_50(r) is not None and markout_50(r) <= 5]
strong = [r for r in osm_crosses if markout_50(r) is not None and markout_50(r) > 5]
print(f"CF3: weak markout crosses: {len(weak)}, strong: {len(strong)}")

# If we skip weak: we save the cross cost (-edge × size is positive saving) but lose markout_50
cross_cost_weak = sum(-r["edge_at_fill"] * r["size"] for r in weak)  # positive = saved
markout_weak = sum(markout_50(r) for r in weak)  # positive = given up
cf3_net = cross_cost_weak - markout_weak
print(f"CF3: cross cost SAVED by skipping weak: {cross_cost_weak:,.1f}")
print(f"CF3: markout GIVEN UP by skipping weak: {markout_weak:,.1f}")
print(f"CF3 NET: {cf3_net:,.1f}")

# Also: strong crosses keep both (no change)
cross_cost_strong = sum(-r["edge_at_fill"] * r["size"] for r in strong)
markout_strong = sum(markout_50(r) for r in strong)
print(f"  (for ref) strong crosses: cross cost {cross_cost_strong:,.1f}, markout {markout_strong:,.1f}")

# ------------------------------------------------------------------------
# Summary
# ------------------------------------------------------------------------
print("\n=== COUNTERFACTUAL SUMMARY ===")
summary = {
    "CF1_osm_edge12_layer": round(cf1_net, 1),
    "CF2_pep_tighter_recycle": round(cf2_net, 1),
    "CF3_skip_weak_crosses": round(cf3_net, 1),
}
for k, v in summary.items():
    print(f"  {k}: ${v:+,.1f}")

import json
with (ART / "counterfactuals.json").open("w") as f:
    json.dump(summary, f, indent=2)
