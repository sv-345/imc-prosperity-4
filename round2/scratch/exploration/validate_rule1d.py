"""Redo signal & edge using inner-mid based aggressive detection.

For OSM especially — the model FV=10001 is stale (actual mid ~10004).
The real "aggressive" signal is: bid >= a dynamic reference (inner_mid of nearby
ticks), or ask <= ref.

For PEP, the model FV is accurate (drift +0.1/tick). But let's verify by also
computing using inner-mid reference.

Definition:
  'agg_bid' = bid at tick t with price >= ceil(ref_t) where ref_t is a local mid estimate.
  'agg_ask' = ask at tick t with price <= floor(ref_t).
Where ref_t = rolling median of inner_mid over nearby ticks (window 21 centered).

Then measure forward detrended-mid change.
"""
from __future__ import annotations
import pathlib
import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "ROUND_2"
PRODUCTS = {"OSM": "ASH_COATED_OSMIUM", "PEP": "INTARIAN_PEPPER_ROOT"}


def load(day: int, product: str) -> pd.DataFrame:
    p = pd.read_csv(DATA / f"prices_round_2_day_{day}.csv", sep=";")
    p = p[p["product"] == PRODUCTS[product]].sort_values("timestamp").reset_index(drop=True)
    p["mid"] = (p["bid_price_1"] + p["ask_price_1"]) / 2.0
    return p


def rolling_ref(p: pd.DataFrame, window: int = 51) -> pd.Series:
    """Rolling median of inner mid over surrounding window (centered)."""
    return p["mid"].rolling(window, center=True, min_periods=5).median()


def classify_by_inner_ref(p: pd.DataFrame, ref: pd.Series) -> dict:
    """Find aggressive quotes by price >= ref (bid) or price <= ref (ask)."""
    n = len(p)
    agg_bid_events = []
    agg_ask_events = []
    for i in range(n):
        r = ref.iloc[i]
        if pd.isna(r):
            continue
        for k in (1, 2, 3):
            bp = p[f"bid_price_{k}"].iloc[i]; bv = p[f"bid_volume_{k}"].iloc[i]
            ap = p[f"ask_price_{k}"].iloc[i]; av = p[f"ask_volume_{k}"].iloc[i]
            if pd.notna(bp) and bp > r:
                agg_bid_events.append(dict(i=i, px=int(bp), vol=int(bv), ref=r))
            if pd.notna(ap) and ap < r:
                agg_ask_events.append(dict(i=i, px=int(ap), vol=int(av), ref=r))
    return dict(agg_bid_events=agg_bid_events, agg_ask_events=agg_ask_events)


def fwd_change(p: pd.DataFrame, idxs: list[int], k: int = 1, ref_col: str = "mid_minus_ref") -> float:
    arr = p[ref_col].values
    diffs = []
    for i in idxs:
        if 0 <= i + k < len(arr) and not (np.isnan(arr[i]) or np.isnan(arr[i+k])):
            diffs.append(arr[i+k] - arr[i])
    return float(np.mean(diffs)) if diffs else float("nan")


def main() -> None:
    print("=" * 100)
    print("Rolling-mid reference aggressive-quote detection")
    print("=" * 100)

    for product in ("PEP", "OSM"):
        print(f"\n### {product} ###")
        total_bid_edge = 0.0
        total_ask_edge = 0.0
        total_bid_qty = 0
        total_ask_qty = 0
        total_bid_ev = 0
        total_ask_ev = 0
        for day in (-1, 0, 1):
            p = load(day, product)
            p["ref"] = rolling_ref(p, window=51)
            p["mid_minus_ref"] = p["mid"] - p["ref"]
            classes = classify_by_inner_ref(p, p["ref"])
            agg_bid = classes["agg_bid_events"]
            agg_ask = classes["agg_ask_events"]

            # De-duplicate by tick
            bid_ticks = sorted(set(e["i"] for e in agg_bid))
            ask_ticks = sorted(set(e["i"] for e in agg_ask))

            # Compute per-event edge
            bid_edge_sum = sum((e["px"] - e["ref"]) * e["vol"] for e in agg_bid)
            ask_edge_sum = sum((e["ref"] - e["px"]) * e["vol"] for e in agg_ask)
            bid_qty_sum = sum(e["vol"] for e in agg_bid)
            ask_qty_sum = sum(e["vol"] for e in agg_ask)

            # Forward change
            fwd1_bid = fwd_change(p, bid_ticks, k=1)
            fwd1_ask = fwd_change(p, ask_ticks, k=1)

            print(f"  day {day}:  bid_ticks={len(bid_ticks):4d}  bid_qty={bid_qty_sum:5d}  bid_edge=${bid_edge_sum:6.0f}  fwd1={fwd1_bid:+.2f}  |  "
                  f"ask_ticks={len(ask_ticks):4d}  ask_qty={ask_qty_sum:5d}  ask_edge=${ask_edge_sum:6.0f}  fwd1={fwd1_ask:+.2f}")
            total_bid_edge += bid_edge_sum
            total_ask_edge += ask_edge_sum
            total_bid_qty += bid_qty_sum
            total_ask_qty += ask_qty_sum
            total_bid_ev += len(bid_ticks)
            total_ask_ev += len(ask_ticks)

        print(f"  --- 3-day totals ---")
        print(f"  bid events={total_bid_ev}  qty={total_bid_qty}  edge=${total_bid_edge:.0f}  avg edge/unit=${total_bid_edge/max(total_bid_qty,1):.2f}")
        print(f"  ask events={total_ask_ev}  qty={total_ask_qty}  edge=${total_ask_edge:.0f}  avg edge/unit=${total_ask_edge/max(total_ask_qty,1):.2f}")
        print(f"  per 10k-tick day bid-edge=${total_bid_edge/3:.0f}  ask-edge=${total_ask_edge/3:.0f}  combined=${(total_bid_edge+total_ask_edge)/3:.0f}")


if __name__ == "__main__":
    main()
