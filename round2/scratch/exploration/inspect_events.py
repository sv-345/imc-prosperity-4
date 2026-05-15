"""Inspect specific aggressive bot-3 events — print the book around them."""
from __future__ import annotations
import pathlib
import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "ROUND_2"
PRODUCTS = {"OSM": "ASH_COATED_OSMIUM", "PEP": "INTARIAN_PEPPER_ROOT"}


def fv_of(product: str, day: int, ts: np.ndarray) -> np.ndarray:
    if product == "OSM":
        return np.full_like(ts, 10001.0, dtype=float)
    day_start = {-1: 11000, 0: 12000, 1: 13000}[day]
    return day_start + 0.1 * (ts // 100)


def load(day: int, product: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    p = pd.read_csv(DATA / f"prices_round_2_day_{day}.csv", sep=";")
    t = pd.read_csv(DATA / f"trades_round_2_day_{day}.csv", sep=";")
    p = p[p["product"] == PRODUCTS[product]].sort_values("timestamp").reset_index(drop=True)
    t = t[t["symbol"] == PRODUCTS[product]].sort_values("timestamp").reset_index(drop=True)
    p["fv"] = fv_of(product, day, p["timestamp"].values)
    p["floor_fv"] = np.floor(p["fv"]).astype(int)
    return p, t


def print_book(row: pd.Series, trades_at: pd.DataFrame, label: str = "") -> None:
    f = row["fv"]
    ff = row["floor_fv"]
    print(f"\n  ts={row['timestamp']}  FV={f:.1f}  floor={ff}  {label}")
    for i in (3, 2, 1):
        ap = row[f"ask_price_{i}"]; av = row[f"ask_volume_{i}"]
        if pd.notna(ap):
            marker = ""
            if not trades_at.empty and (ap == trades_at["price"]).any():
                marker = "  <-- TRADE"
            print(f"    ASK L{i}  px={int(ap)} (off={int(ap-ff):+d})  vol={int(av)}{marker}")
    mid = (row["bid_price_1"] + row["ask_price_1"]) / 2 if pd.notna(row["bid_price_1"]) and pd.notna(row["ask_price_1"]) else float('nan')
    print(f"    ── mid={mid:.1f}  (mid-FV={mid-f:+.1f})")
    for i in (1, 2, 3):
        bp = row[f"bid_price_{i}"]; bv = row[f"bid_volume_{i}"]
        if pd.notna(bp):
            marker = ""
            if not trades_at.empty and (bp == trades_at["price"]).any():
                marker = "  <-- TRADE"
            print(f"    BID L{i}  px={int(bp)} (off={int(bp-ff):+d})  vol={int(bv)}{marker}")
    if not trades_at.empty:
        for _, tr in trades_at.iterrows():
            print(f"    TRADE  px={int(tr['price'])}  qty={int(tr['quantity'])}  (off={int(tr['price']-ff):+d})")


def find_events(p: pd.DataFrame, product: str, kind: str = "agg_bid", limit: int = 5) -> list[int]:
    """Return indices of aggressive events (bid crossing F+ or ask crossing F-)."""
    events = []
    ff = p["floor_fv"].values
    for i in range(len(p)):
        has_agg_bid = False
        has_agg_ask = False
        for k in (1, 2, 3):
            bp = p[f"bid_price_{k}"].iloc[i]
            ap = p[f"ask_price_{k}"].iloc[i]
            if pd.notna(bp) and bp >= ff[i]:
                has_agg_bid = True
            if pd.notna(ap) and ap <= ff[i]:
                has_agg_ask = True
        if (kind == "agg_bid" and has_agg_bid) or (kind == "agg_ask" and has_agg_ask):
            events.append(i)
            if len(events) >= limit:
                break
    return events


def main() -> None:
    for product in ("PEP", "OSM"):
        print(f"\n========================================\n{product} aggressive events (day 0)\n========================================")
        p, t = load(0, product)
        for kind in ("agg_bid", "agg_ask"):
            idxs = find_events(p, product, kind=kind, limit=5)
            print(f"\n--- {kind}: first {len(idxs)} events ---")
            for idx in idxs:
                ts = p["timestamp"].iloc[idx]
                trades_now = t[t["timestamp"] == ts]
                print(f"\n### event @ idx={idx} ts={ts} ###")
                # show prev, event, next-2 snapshots
                for offset in (-1, 0, 1, 2):
                    j = idx + offset
                    if 0 <= j < len(p):
                        t_at = t[t["timestamp"] == p["timestamp"].iloc[j]]
                        print_book(p.iloc[j], t_at, label=f"[t{'+' if offset>=0 else ''}{offset}]")


if __name__ == "__main__":
    main()
