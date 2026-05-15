"""Pure-edge computation: PEP agg_bid and agg_ask events, measured as
instantaneous edge vs FV at moment of event.

This is the UPPER BOUND on alpha before any unwind/inventory cost.
Separately, we simulate realistic unwind via iter23-style passive buys.
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
    return p


def fv_day(day: int, ts: np.ndarray, product: str) -> np.ndarray:
    if product == "OSM":
        return np.full_like(ts, 10001.0, dtype=float)
    day_start = {-1: 11000, 0: 12000, 1: 13000}[day]
    return day_start + 0.1 * (ts // 100)


def measure_edge(day: int, product: str) -> dict:
    p = load(day, product)
    fv = fv_day(day, p["timestamp"].values, product)
    floor_fv = np.floor(fv).astype(int)

    edge_bid_sum = 0.0  # sum of (bid_px - fv) * qty across aggressive-bid events
    edge_ask_sum = 0.0
    qty_bid_sum = 0
    qty_ask_sum = 0
    events_bid = 0
    events_ask = 0

    for i in range(len(p)):
        ff = floor_fv[i]
        f = fv[i]
        for k in (1, 2, 3):
            bp = p[f"bid_price_{k}"].iloc[i]; bv = p[f"bid_volume_{k}"].iloc[i]
            if pd.notna(bp) and bp >= ff:
                q = int(bv)
                edge_bid_sum += (bp - f) * q
                qty_bid_sum += q
                events_bid += 1
            ap = p[f"ask_price_{k}"].iloc[i]; av = p[f"ask_volume_{k}"].iloc[i]
            if pd.notna(ap) and ap <= ff:
                q = int(av)
                edge_ask_sum += (f - ap) * q
                qty_ask_sum += q
                events_ask += 1

    return dict(
        day=day,
        events_bid=events_bid, qty_bid_sum=qty_bid_sum, edge_bid_sum=edge_bid_sum,
        events_ask=events_ask, qty_ask_sum=qty_ask_sum, edge_ask_sum=edge_ask_sum,
    )


def main() -> None:
    print("=" * 100)
    print("Pure instantaneous edge (sum of (px - fv) * qty) — upper bound")
    print("=" * 100)

    for product in ("PEP", "OSM"):
        print(f"\n### {product} ###")
        tot_bid_edge = tot_ask_edge = 0.0
        tot_bid_qty = tot_ask_qty = 0
        tot_bid_ev = tot_ask_ev = 0
        for day in (-1, 0, 1):
            r = measure_edge(day, product)
            avg_edge_bid = r["edge_bid_sum"] / max(r["qty_bid_sum"], 1)
            avg_edge_ask = r["edge_ask_sum"] / max(r["qty_ask_sum"], 1)
            print(f"  day {day}: "
                  f"bid events={r['events_bid']:4d} qty={r['qty_bid_sum']:5d} edge_sum={r['edge_bid_sum']:8.0f}  avg_edge/unit={avg_edge_bid:+5.2f}  |  "
                  f"ask events={r['events_ask']:4d} qty={r['qty_ask_sum']:5d} edge_sum={r['edge_ask_sum']:8.0f}  avg_edge/unit={avg_edge_ask:+5.2f}")
            tot_bid_edge += r["edge_bid_sum"]
            tot_ask_edge += r["edge_ask_sum"]
            tot_bid_qty += r["qty_bid_sum"]
            tot_ask_qty += r["qty_ask_sum"]
            tot_bid_ev += r["events_bid"]
            tot_ask_ev += r["events_ask"]
        print(f"  --- 3-day totals ---")
        print(f"  bid: events={tot_bid_ev} qty={tot_bid_qty} edge=${tot_bid_edge:.0f}  avg edge/unit=${tot_bid_edge/max(tot_bid_qty,1):.2f}")
        print(f"  ask: events={tot_ask_ev} qty={tot_ask_qty} edge=${tot_ask_edge:.0f}  avg edge/unit=${tot_ask_edge/max(tot_ask_qty,1):.2f}")
        print(f"  per 10k-tick day avg bid-edge=${tot_bid_edge/3:.0f}  ask-edge=${tot_ask_edge/3:.0f}  combined=${(tot_bid_edge+tot_ask_edge)/3:.0f}")


if __name__ == "__main__":
    main()
