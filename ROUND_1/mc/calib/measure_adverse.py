"""Measure adverse selection in 127989 server fills.

For each own fill, compute mid drift over next K ticks, signed by our side:
    signed_drift = (mid[t+K] - fill_price) * sign(our_side)
    where sign(BUY) = +1, sign(SELL) = -1

A POSITIVE signed_drift means the fill was PROFITABLE (mid moved in our favor).
A NEGATIVE signed_drift means we were adversely selected.

If the distribution of signed_drift is centered on ZERO (symmetric), there is
no systematic adverse selection — fills are from uninformed flow.
If the mean is significantly NEGATIVE, fills were informed against us.

We report this per-product for K={1,3,5,10,20}. A meaningful negative mean
would explain why v15's tighter quotes under-performed on server: tighter
quotes take more fills, each one slightly losing to informed flow.
"""
from __future__ import annotations
import json
import statistics
from pathlib import Path


DATA = Path(__file__).parent.parent.parent / "data" / "calib"
FILLS = json.loads((DATA / "127989_own_fills.json").read_text())
ACTS = json.loads((DATA / "127989_activities.json").read_text())


def per_product():
    # index mids by (product, ts) for O(1) lookup
    mid_idx: dict = {}
    for r in ACTS:
        if r.get("mid_price") is not None:
            mid_idx[(r["product"], r["ts"])] = r["mid_price"]

    products = set(f["product"] for f in FILLS)
    for prod in sorted(products):
        fills = [f for f in FILLS if f["product"] == prod]
        print(f"\n=== {prod}  ({len(fills)} fills) ===")
        for K in (1, 3, 5, 10, 20):
            signed = []
            buy_sd = []
            sell_sd = []
            for f in fills:
                ts = f["ts"]
                future_ts = ts + K * 100
                future_mid = mid_idx.get((prod, future_ts))
                if future_mid is None:
                    continue
                raw = future_mid - f["price"]
                sign = 1 if f["side"] == "BUY" else -1
                sd = raw * sign
                signed.append(sd)
                (buy_sd if f["side"] == "BUY" else sell_sd).append(sd)
            if not signed:
                continue
            n = len(signed)
            mu = statistics.mean(signed)
            sd = statistics.stdev(signed) if n > 1 else 0
            # Per-trade PnL sign count
            win = sum(1 for s in signed if s > 0)
            lose = sum(1 for s in signed if s < 0)
            zero = sum(1 for s in signed if s == 0)
            buy_mu = statistics.mean(buy_sd) if buy_sd else 0
            sell_mu = statistics.mean(sell_sd) if sell_sd else 0
            print(f"  K={K:2d}  n={n}  mean_signed_drift={mu:+.3f}  "
                  f"std={sd:.2f}  W/L/T={win}/{lose}/{zero}  "
                  f"buy_mu={buy_mu:+.3f}  sell_mu={sell_mu:+.3f}")


def neighborhood_drift_by_side():
    """Condition mid-drift on our fill SIDE. If buys followed by DOWN drift,
    that's adverse."""
    mid_idx = {(r["product"], r["ts"]): r["mid_price"] for r in ACTS if r.get("mid_price")}
    products = set(f["product"] for f in FILLS)
    print("\n--- Unsigned drift by side (mid[t+10] - mid[t] for taker side) ---")
    for prod in sorted(products):
        fills = [f for f in FILLS if f["product"] == prod]
        buy_drift, sell_drift = [], []
        for f in fills:
            ts = f["ts"]
            mid_now = mid_idx.get((prod, ts))
            mid_future = mid_idx.get((prod, ts + 1000))  # K=10 ticks = 1000ms
            if mid_now is None or mid_future is None:
                continue
            d = mid_future - mid_now
            if f["side"] == "BUY":
                buy_drift.append(d)
            else:
                sell_drift.append(d)
        print(f"  {prod}  after BUY:  n={len(buy_drift):3d}  "
              f"mean_drift={statistics.mean(buy_drift):+.3f}" if buy_drift else "  (no data)")
        print(f"  {prod}  after SELL: n={len(sell_drift):3d}  "
              f"mean_drift={statistics.mean(sell_drift):+.3f}" if sell_drift else "  (no data)")


if __name__ == "__main__":
    per_product()
    neighborhood_drift_by_side()
