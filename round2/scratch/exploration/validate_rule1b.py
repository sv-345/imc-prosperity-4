"""Refined validation — PEP agg_bid ONLY vs agg_ask ONLY with 1-tick unwind.

Also check: if we simulate iter23's existing PEP take logic (ap < fv_int),
how much of the agg_ask value does it already capture?
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


def simulate(day: int, product: str, pos_limit: int, mode: str) -> dict:
    """
    mode options:
      'bid_only':  take aggressive bids (sell), unwind next tick at mid
      'ask_only':  take aggressive asks (buy), unwind next tick at mid
      'both':      take both, unwind next tick at mid
      'iter23_ask': replicate iter23's ap < fv_int logic on PEP
    """
    p = load(day, product)
    fv = fv_day(day, p["timestamp"].values, product)
    floor_fv = np.floor(fv).astype(int)
    fv_int = np.round(fv).astype(int)  # iter23 uses int(round(fv))

    cash = 0.0
    position = 0
    fills = []
    # unwind: list of (signed qty, due_index)
    unwind_queue: list[tuple[int, int]] = []

    for i in range(len(p)):
        ff = floor_fv[i]
        fi = fv_int[i]
        ts = p["timestamp"].iloc[i]

        bid1 = p["bid_price_1"].iloc[i]
        ask1 = p["ask_price_1"].iloc[i]
        if pd.notna(bid1) and pd.notna(ask1):
            mid_now = (bid1 + ask1) / 2.0
        else:
            mid_now = float("nan")

        # Handle unwinds: pop any with due_index <= i, unwind at current mid
        new_q = []
        for (qty, when) in unwind_queue:
            if when <= i and not np.isnan(mid_now):
                if qty < 0:  # short → buy back
                    cash -= mid_now * (-qty); position += (-qty)
                else:        # long → sell
                    cash += mid_now * qty; position -= qty
            else:
                new_q.append((qty, when))
        unwind_queue = new_q

        # Gather book
        bid_pool, ask_pool = [], []
        for k in (1, 2, 3):
            bp = p[f"bid_price_{k}"].iloc[i]; bv = p[f"bid_volume_{k}"].iloc[i]
            ap = p[f"ask_price_{k}"].iloc[i]; av = p[f"ask_volume_{k}"].iloc[i]
            if pd.notna(bp): bid_pool.append((int(bp), int(bv)))
            if pd.notna(ap): ask_pool.append((int(ap), int(av)))

        # Decide what to take
        if mode == "bid_only":
            agg_bids = sorted([(px, vol) for (px, vol) in bid_pool if px >= ff], reverse=True)
            for (px, vol) in agg_bids:
                cap = pos_limit + position
                if cap <= 0: break
                qty = min(vol, cap)
                if qty > 0:
                    cash += px * qty; position -= qty
                    fills.append(dict(ts=ts, side="SELL", px=px, qty=qty))
                    unwind_queue.append((-qty, i + 1))
        elif mode == "ask_only":
            agg_asks = sorted([(px, vol) for (px, vol) in ask_pool if px <= ff])
            for (px, vol) in agg_asks:
                cap = pos_limit - position
                if cap <= 0: break
                qty = min(vol, cap)
                if qty > 0:
                    cash -= px * qty; position += qty
                    fills.append(dict(ts=ts, side="BUY", px=px, qty=qty))
                    unwind_queue.append((qty, i + 1))
        elif mode == "both":
            agg_bids = sorted([(px, vol) for (px, vol) in bid_pool if px >= ff], reverse=True)
            agg_asks = sorted([(px, vol) for (px, vol) in ask_pool if px <= ff])
            for (px, vol) in agg_bids:
                cap = pos_limit + position
                if cap <= 0: break
                qty = min(vol, cap)
                if qty > 0:
                    cash += px * qty; position -= qty
                    fills.append(dict(ts=ts, side="SELL", px=px, qty=qty))
                    unwind_queue.append((-qty, i + 1))
            for (px, vol) in agg_asks:
                cap = pos_limit - position
                if cap <= 0: break
                qty = min(vol, cap)
                if qty > 0:
                    cash -= px * qty; position += qty
                    fills.append(dict(ts=ts, side="BUY", px=px, qty=qty))
                    unwind_queue.append((qty, i + 1))
        elif mode == "iter23_ask":
            # iter23 _trade_pepper: take asks < fv_int
            asks_sorted = sorted(ask_pool)
            for (px, vol) in asks_sorted:
                if px >= fi:
                    break
                cap = pos_limit - position
                if cap <= 0: break
                qty = min(vol, cap)
                if qty > 0:
                    cash -= px * qty; position += qty
                    fills.append(dict(ts=ts, side="BUY", px=px, qty=qty))
                    unwind_queue.append((qty, i + 1))

    # Flush remaining at final mid
    final_mid = (p["bid_price_1"].iloc[-1] + p["ask_price_1"].iloc[-1]) / 2
    for (qty, when) in unwind_queue:
        if qty < 0:
            cash -= final_mid * (-qty); position += (-qty)
        else:
            cash += final_mid * qty; position -= qty
    return dict(cash=cash, position=position, n_fills=len(fills))


def main() -> None:
    print("=" * 100)
    print("Refined validation — PEP+OSM by side, 1-tick unwind")
    print("=" * 100)

    for product in ("PEP", "OSM"):
        print(f"\n### {product} ###")
        for mode in ("bid_only", "ask_only", "both", "iter23_ask"):
            total = 0
            by_day = []
            for day in (-1, 0, 1):
                r = simulate(day, product, pos_limit=100, mode=mode)
                by_day.append(r["cash"])
                total += r["cash"]
            print(f"  {mode:12s}: day_-1={by_day[0]:+9.0f}  day_0={by_day[1]:+9.0f}  day_1={by_day[2]:+9.0f}  TOTAL={total:+9.0f}  avg={total/3:+8.0f}/day")


if __name__ == "__main__":
    main()
