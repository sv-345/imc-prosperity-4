"""Explore other bot behavior patterns: time-of-day, wall moves, wall volume.

Questions:
A) Does OSM have a time-of-day regime? (sriram's "middle exploits")
B) When does wall bot move? Does it predict direction?
C) Is wall volume predictive of incoming taker flow?
D) Do OSM and PEP events correlate cross-product?
E) Does the taker flow itself have patterns?
"""
from __future__ import annotations
import pathlib
import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "ROUND_2"
PRODUCTS = {"OSM": "ASH_COATED_OSMIUM", "PEP": "INTARIAN_PEPPER_ROOT"}


def load_prod(day: int, product: str) -> pd.DataFrame:
    p = pd.read_csv(DATA / f"prices_round_2_day_{day}.csv", sep=";")
    p = p[p["product"] == PRODUCTS[product]].sort_values("timestamp").reset_index(drop=True)
    p["mid"] = (p["bid_price_1"] + p["ask_price_1"]) / 2.0
    p["wall_bid"] = p.apply(lambda r: max([r[f"bid_price_{k}"] for k in (1,2,3) if pd.notna(r[f"bid_price_{k}"])], default=np.nan), axis=1)
    # wall = outer-most, which for bid is MIN of existing prices
    p["wall_bid_px"] = p.apply(lambda r: min([r[f"bid_price_{k}"] for k in (1,2,3) if pd.notna(r[f"bid_price_{k}"])], default=np.nan), axis=1)
    p["wall_ask_px"] = p.apply(lambda r: max([r[f"ask_price_{k}"] for k in (1,2,3) if pd.notna(r[f"ask_price_{k}"])], default=np.nan), axis=1)
    return p


def load_trades(day: int, product: str) -> pd.DataFrame:
    t = pd.read_csv(DATA / f"trades_round_2_day_{day}.csv", sep=";")
    return t[t["symbol"] == PRODUCTS[product]].sort_values("timestamp").reset_index(drop=True)


def fv_day(day: int, ts: np.ndarray, product: str) -> np.ndarray:
    if product == "OSM":
        return np.full_like(ts, 10001.0, dtype=float)
    day_start = {-1: 11000, 0: 12000, 1: 13000}[day]
    return day_start + 0.1 * (ts // 100)


def time_of_day_analysis(product: str):
    """Split each day into quartiles by time; compute stats per quartile."""
    print(f"\n### {product} — quartile analysis ###")
    print(f"{'day/quartile':<15}  {'trades':>7}  {'buy%':>6}  {'agg_bid':>8}  {'agg_ask':>8}  {'mid_range':>12}  {'wall_move':>10}")
    for day in (-1, 0, 1):
        p = load_prod(day, product)
        trades = load_trades(day, product)
        fv = fv_day(day, p["timestamp"].values, product)
        floor_fv = np.floor(fv).astype(int)
        p["floor_fv"] = floor_fv

        # compute aggressive event per-row
        agg_bid = np.zeros(len(p), dtype=bool)
        agg_ask = np.zeros(len(p), dtype=bool)
        for k in (1, 2, 3):
            bp = p[f"bid_price_{k}"].values
            ap = p[f"ask_price_{k}"].values
            agg_bid |= (~pd.isna(bp)) & (bp >= floor_fv)
            agg_ask |= (~pd.isna(ap)) & (ap <= floor_fv)

        # Wall moves: wall_bid_px changes tick-to-tick
        wall_bid_move = (p["wall_bid_px"].diff().abs() >= 1).astype(int)
        wall_ask_move = (p["wall_ask_px"].diff().abs() >= 1).astype(int)

        # Merge trades with quarter
        n = len(p)
        quarter_size = n // 4
        for q in range(4):
            lo = q * quarter_size
            hi = (q + 1) * quarter_size if q < 3 else n
            ts_lo = p["timestamp"].iloc[lo]
            ts_hi = p["timestamp"].iloc[hi - 1]
            tr = trades[(trades["timestamp"] >= ts_lo) & (trades["timestamp"] <= ts_hi)]
            # estimate buy-side fraction
            if len(tr) > 0:
                # A trade is 'buy-hit-ask' if price is at or above last ask_1
                buy_count = 0
                for _, row in tr.iterrows():
                    mb = p[p["timestamp"] == row["timestamp"]]
                    if len(mb) > 0:
                        ask1 = mb["ask_price_1"].iloc[0]
                        if pd.notna(ask1) and row["price"] >= ask1 - 0.01:
                            buy_count += 1
                buy_pct = buy_count / len(tr) * 100
            else:
                buy_pct = 0.0

            mid_vals = p["mid"].iloc[lo:hi].dropna()
            mid_range = f"{mid_vals.min():.0f}..{mid_vals.max():.0f}"

            wall_moves = int(wall_bid_move.iloc[lo:hi].sum() + wall_ask_move.iloc[lo:hi].sum())

            print(f"  day{day} Q{q+1}     {len(tr):>7}  {buy_pct:5.1f}%  {int(agg_bid[lo:hi].sum()):>8}  {int(agg_ask[lo:hi].sum()):>8}  {mid_range:>12}  {wall_moves:>10}")


def cross_product_correlation():
    """Do OSM events correlate with PEP events at same timestamp?"""
    print("\n### Cross-product event correlation ###")
    for day in (-1, 0, 1):
        osm = load_prod(day, "OSM")
        pep = load_prod(day, "PEP")
        osm_fv = fv_day(day, osm["timestamp"].values, "OSM")
        pep_fv = fv_day(day, pep["timestamp"].values, "PEP")
        osm_floor = np.floor(osm_fv).astype(int)
        pep_floor = np.floor(pep_fv).astype(int)

        # Compute agg_bid/agg_ask for each
        def agg_events(p, floor_fv):
            ab = np.zeros(len(p), dtype=bool)
            aa = np.zeros(len(p), dtype=bool)
            for k in (1, 2, 3):
                bp = p[f"bid_price_{k}"].values
                ap = p[f"ask_price_{k}"].values
                ab |= (~pd.isna(bp)) & (bp >= floor_fv)
                aa |= (~pd.isna(ap)) & (ap <= floor_fv)
            return ab, aa
        osm_ab, osm_aa = agg_events(osm, osm_floor)
        pep_ab, pep_aa = agg_events(pep, pep_floor)

        # timestamps should align; index is same
        if len(osm) != len(pep):
            print(f"  day {day}: length mismatch OSM={len(osm)} PEP={len(pep)}")
            continue
        # Count co-occurrences
        both_agg_bid = (osm_ab & pep_ab).sum()
        both_agg_ask = (osm_aa & pep_aa).sum()
        print(f"  day {day}: OSM agg_bid={osm_ab.sum()}  PEP agg_bid={pep_ab.sum()}  CO={both_agg_bid}  "
              f"(expected by chance: {osm_ab.sum() * pep_ab.sum() / len(osm):.1f})")
        print(f"  day {day}: OSM agg_ask={osm_aa.sum()}  PEP agg_ask={pep_aa.sum()}  CO={both_agg_ask}  "
              f"(expected by chance: {osm_aa.sum() * pep_aa.sum() / len(osm):.1f})")


def main() -> None:
    print("=" * 100)
    print("OTHER BOT PATTERNS")
    print("=" * 100)

    for product in ("OSM", "PEP"):
        time_of_day_analysis(product)

    cross_product_correlation()


if __name__ == "__main__":
    main()
