"""Do trades happen AT aggressive bot-3 quote prices?
If YES: someone (bot or trader) is already hitting them. Edge is consumed.
If NO: opportunity is free.
"""
from __future__ import annotations
import pathlib
import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "ROUND_2"
PRODUCTS = {"OSM": "ASH_COATED_OSMIUM", "PEP": "INTARIAN_PEPPER_ROOT"}


def load_prices(day: int, product: str) -> pd.DataFrame:
    p = pd.read_csv(DATA / f"prices_round_2_day_{day}.csv", sep=";")
    return p[p["product"] == PRODUCTS[product]].sort_values("timestamp").reset_index(drop=True)


def load_trades(day: int, product: str) -> pd.DataFrame:
    t = pd.read_csv(DATA / f"trades_round_2_day_{day}.csv", sep=";")
    return t[t["symbol"] == PRODUCTS[product]].sort_values("timestamp").reset_index(drop=True)


def fv_day(day: int, ts: np.ndarray, product: str) -> np.ndarray:
    if product == "OSM":
        return np.full_like(ts, 10001.0, dtype=float)
    day_start = {-1: 11000, 0: 12000, 1: 13000}[day]
    return day_start + 0.1 * (ts // 100)


def check(day: int, product: str) -> dict:
    p = load_prices(day, product)
    trades = load_trades(day, product)
    fv = fv_day(day, p["timestamp"].values, product)
    floor_fv = np.floor(fv).astype(int)

    # Build ts -> book map
    book_map = {}
    for i in range(len(p)):
        ts = p["timestamp"].iloc[i]
        ff = floor_fv[i]
        bid_pool, ask_pool = [], []
        for k in (1, 2, 3):
            bp = p[f"bid_price_{k}"].iloc[i]; bv = p[f"bid_volume_{k}"].iloc[i]
            ap = p[f"ask_price_{k}"].iloc[i]; av = p[f"ask_volume_{k}"].iloc[i]
            if pd.notna(bp): bid_pool.append((int(bp), int(bv)))
            if pd.notna(ap): ask_pool.append((int(ap), int(av)))
        book_map[ts] = (ff, bid_pool, ask_pool)

    # For each aggressive quote seen, check if a trade at that price happened in same tick
    n_agg_bid_total = 0
    n_agg_bid_traded_at = 0
    agg_bid_vol_total = 0
    agg_bid_vol_traded = 0

    n_agg_ask_total = 0
    n_agg_ask_traded_at = 0
    agg_ask_vol_total = 0
    agg_ask_vol_traded = 0

    # For each tick with agg quotes, check trades at those prices
    trades_by_ts = {}
    for _, tr in trades.iterrows():
        trades_by_ts.setdefault(int(tr["timestamp"]), []).append((int(tr["price"]), int(tr["quantity"])))

    for ts, (ff, bid_pool, ask_pool) in book_map.items():
        trs_this = trades_by_ts.get(ts, [])
        for (bp, bv) in bid_pool:
            if bp >= ff:  # aggressive
                n_agg_bid_total += 1
                agg_bid_vol_total += bv
                # Did a trade happen AT this bid price?
                for (tpx, tqty) in trs_this:
                    if tpx == bp:
                        n_agg_bid_traded_at += 1
                        agg_bid_vol_traded += min(tqty, bv)
                        break
        for (ap, av) in ask_pool:
            if ap <= ff:
                n_agg_ask_total += 1
                agg_ask_vol_total += av
                for (tpx, tqty) in trs_this:
                    if tpx == ap:
                        n_agg_ask_traded_at += 1
                        agg_ask_vol_traded += min(tqty, av)
                        break

    return dict(
        n_agg_bid=n_agg_bid_total,
        n_agg_bid_traded=n_agg_bid_traded_at,
        agg_bid_vol=agg_bid_vol_total,
        agg_bid_vol_traded=agg_bid_vol_traded,
        n_agg_ask=n_agg_ask_total,
        n_agg_ask_traded=n_agg_ask_traded_at,
        agg_ask_vol=agg_ask_vol_total,
        agg_ask_vol_traded=agg_ask_vol_traded,
    )


def main() -> None:
    print("=" * 100)
    print("Do trades happen AT aggressive-quote prices?")
    print("=" * 100)
    for product in ("PEP", "OSM"):
        print(f"\n### {product} ###")
        for day in (-1, 0, 1):
            r = check(day, product)
            bid_pct = 100 * r["n_agg_bid_traded"] / max(r["n_agg_bid"], 1)
            ask_pct = 100 * r["n_agg_ask_traded"] / max(r["n_agg_ask"], 1)
            bid_vol_pct = 100 * r["agg_bid_vol_traded"] / max(r["agg_bid_vol"], 1)
            ask_vol_pct = 100 * r["agg_ask_vol_traded"] / max(r["agg_ask_vol"], 1)
            print(f"  day {day}:  agg_bid events={r['n_agg_bid']:4d} hit={r['n_agg_bid_traded']:4d} ({bid_pct:5.1f}%)  "
                  f"vol_hit={r['agg_bid_vol_traded']:4d}/{r['agg_bid_vol']:5d} ({bid_vol_pct:.1f}%)  ||  "
                  f"agg_ask events={r['n_agg_ask']:4d} hit={r['n_agg_ask_traded']:4d} ({ask_pct:5.1f}%)  "
                  f"vol_hit={r['agg_ask_vol_traded']:4d}/{r['agg_ask_vol']:5d} ({ask_vol_pct:.1f}%)")


if __name__ == "__main__":
    main()
