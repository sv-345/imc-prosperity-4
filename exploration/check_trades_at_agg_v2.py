"""v2: use rolling-mid reference (51-tick centered median) for aggressive detection.

An 'aggressive' quote is:
  bid > ref  (i.e., bid crosses above local mid)
  ask < ref  (i.e., ask crosses below local mid)

This is the correct definition for OSM where mid drifts around.
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
    p = p[p["product"] == PRODUCTS[product]].sort_values("timestamp").reset_index(drop=True)
    p["mid"] = (p["bid_price_1"] + p["ask_price_1"]) / 2.0
    p["ref"] = p["mid"].rolling(51, center=True, min_periods=5).median()
    return p


def load_trades(day: int, product: str) -> pd.DataFrame:
    t = pd.read_csv(DATA / f"trades_round_2_day_{day}.csv", sep=";")
    return t[t["symbol"] == PRODUCTS[product]].sort_values("timestamp").reset_index(drop=True)


def check(day: int, product: str) -> dict:
    p = load_prices(day, product)
    trades = load_trades(day, product)

    n_bid_ev = 0; n_bid_hit = 0; bid_vol = 0; bid_vol_hit = 0
    n_ask_ev = 0; n_ask_hit = 0; ask_vol = 0; ask_vol_hit = 0

    trades_by_ts = {}
    for _, tr in trades.iterrows():
        trades_by_ts.setdefault(int(tr["timestamp"]), []).append((int(tr["price"]), int(tr["quantity"])))

    agg_bid_edge_sum = 0.0
    agg_ask_edge_sum = 0.0
    agg_bid_edge_count = 0
    agg_ask_edge_count = 0

    for i in range(len(p)):
        r = p["ref"].iloc[i]
        ts = p["timestamp"].iloc[i]
        if pd.isna(r): continue
        trs_this = trades_by_ts.get(int(ts), [])
        for k in (1, 2, 3):
            bp = p[f"bid_price_{k}"].iloc[i]; bv = p[f"bid_volume_{k}"].iloc[i]
            ap = p[f"ask_price_{k}"].iloc[i]; av = p[f"ask_volume_{k}"].iloc[i]
            if pd.notna(bp) and bp > r:  # agg bid
                n_bid_ev += 1
                bid_vol += int(bv)
                agg_bid_edge_sum += (bp - r) * int(bv)
                agg_bid_edge_count += int(bv)
                for (tpx, tqty) in trs_this:
                    if tpx == bp:
                        n_bid_hit += 1
                        bid_vol_hit += min(tqty, int(bv))
                        break
            if pd.notna(ap) and ap < r:
                n_ask_ev += 1
                ask_vol += int(av)
                agg_ask_edge_sum += (r - ap) * int(av)
                agg_ask_edge_count += int(av)
                for (tpx, tqty) in trs_this:
                    if tpx == ap:
                        n_ask_hit += 1
                        ask_vol_hit += min(tqty, int(av))
                        break

    return dict(
        n_bid_ev=n_bid_ev, n_bid_hit=n_bid_hit, bid_vol=bid_vol, bid_vol_hit=bid_vol_hit,
        n_ask_ev=n_ask_ev, n_ask_hit=n_ask_hit, ask_vol=ask_vol, ask_vol_hit=ask_vol_hit,
        avg_bid_edge=agg_bid_edge_sum / max(agg_bid_edge_count, 1),
        avg_ask_edge=agg_ask_edge_sum / max(agg_ask_edge_count, 1),
        total_bid_edge=agg_bid_edge_sum,
        total_ask_edge=agg_ask_edge_sum,
    )


def main() -> None:
    print("=" * 100)
    print("Trades AT aggressive-quote prices — using ROLLING-MID reference")
    print("=" * 100)
    for product in ("PEP", "OSM"):
        print(f"\n### {product} ###")
        for day in (-1, 0, 1):
            r = check(day, product)
            bid_hitpct = 100 * r["n_bid_hit"] / max(r["n_bid_ev"], 1)
            ask_hitpct = 100 * r["n_ask_hit"] / max(r["n_ask_ev"], 1)
            bid_voltpct = 100 * r["bid_vol_hit"] / max(r["bid_vol"], 1)
            ask_voltpct = 100 * r["ask_vol_hit"] / max(r["ask_vol"], 1)
            print(f"  day {day}: agg_bid ev={r['n_bid_ev']:4d} hit={r['n_bid_hit']:3d} ({bid_hitpct:4.1f}%) "
                  f"vol {r['bid_vol_hit']}/{r['bid_vol']} ({bid_voltpct:4.1f}%) avg_edge=${r['avg_bid_edge']:.2f}  "
                  f"total_edge_unhit=${r['total_bid_edge']*(1-bid_voltpct/100):.0f}")
            print(f"         agg_ask ev={r['n_ask_ev']:4d} hit={r['n_ask_hit']:3d} ({ask_hitpct:4.1f}%) "
                  f"vol {r['ask_vol_hit']}/{r['ask_vol']} ({ask_voltpct:4.1f}%) avg_edge=${r['avg_ask_edge']:.2f}  "
                  f"total_edge_unhit=${r['total_ask_edge']*(1-ask_voltpct/100):.0f}")


if __name__ == "__main__":
    main()
