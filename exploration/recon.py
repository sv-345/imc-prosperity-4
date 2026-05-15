"""Fast reconnaissance of R2 data — offset distributions, bot-3 rates, periodicity.

Goal: form concrete hypotheses for the visualizer, not exhaustively characterize.

Runs across all 3 days × 2 products. Prints summary to stdout.
"""
from __future__ import annotations
import pathlib
import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "ROUND_2"

PRODUCTS = {"OSM": "ASH_COATED_OSMIUM", "PEP": "INTARIAN_PEPPER_ROOT"}
DAYS = [-1, 0, 1]

# Expected bot offsets from floor(FV) per round2_model.md
# OSM: wall bid=-10, ask=+9, inner bid=-8, ask=+8. Bot-3 passive ±{1..4} aggressive ±{1..4}.
# PEP: wall bid=-10, ask=+10, inner bid=-6, ask=+7. Bot-3 bid mode +4/-3, ask mode -4/+3.
# FV: OSM=10001 constant; PEP = day_start + 0.1*(ts//100). Day starts 11000/12000/13000 for days -1/0/1.


def fv(product: str, day: int, ts: np.ndarray) -> np.ndarray:
    if product == "OSM":
        return np.full_like(ts, 10001.0, dtype=float)
    day_start = {-1: 11000, 0: 12000, 1: 13000}[day]
    return day_start + 0.1 * (ts // 100)


def load_prices(day: int, product: str) -> pd.DataFrame:
    p = pd.read_csv(DATA / f"prices_round_2_day_{day}.csv", sep=";")
    p = p[p["product"] == PRODUCTS[product]].sort_values("timestamp").reset_index(drop=True)
    return p


def load_trades(day: int, product: str) -> pd.DataFrame:
    t = pd.read_csv(DATA / f"trades_round_2_day_{day}.csv", sep=";")
    t = t[t["symbol"] == PRODUCTS[product]].sort_values("timestamp").reset_index(drop=True)
    return t


def offset_distribution(prices: pd.DataFrame, fv_arr: np.ndarray) -> dict:
    """For each side, count offsets of each level."""
    out = {}
    for side in ("bid", "ask"):
        for i in (1, 2, 3):
            px = prices[f"{side}_price_{i}"]
            vol = prices[f"{side}_volume_{i}"]
            mask = px.notna()
            if not mask.any():
                continue
            offs = (px[mask].values - fv_arr[mask.values]).astype(int)
            out[f"{side}_L{i}"] = {
                "count": len(offs),
                "unique_offsets": dict(zip(*np.unique(offs, return_counts=True))),
                "vol_mean": float(vol[mask].mean()),
                "vol_std": float(vol[mask].std()),
                "vol_min": int(vol[mask].min()),
                "vol_max": int(vol[mask].max()),
            }
    return out


def level_count_distribution(prices: pd.DataFrame) -> dict:
    """How many levels per side are populated each tick?"""
    out = {}
    for side in ("bid", "ask"):
        counts = np.zeros(len(prices), dtype=int)
        for i in (1, 2, 3):
            counts += prices[f"{side}_price_{i}"].notna().astype(int).values
        unique, cnts = np.unique(counts, return_counts=True)
        out[side] = dict(zip(unique.tolist(), cnts.tolist()))
    return out


def bot3_detection(prices: pd.DataFrame, fv_arr: np.ndarray, product: str) -> dict:
    """Detect bot-3 via offset signature.

    Bot-3 quote is at offset in {±1, ±2, ±3, ±4} from floor(FV), while walls are at ±10/±9 and
    inner at ±8/±7/±6. So bot-3 presence = any level has |offset| <= 5 (with some slack).
    """
    # Thresholds per product
    if product == "OSM":
        inner_bid_off = -8
        inner_ask_off = 8
    else:
        inner_bid_off = -6
        inner_ask_off = 7
    results = {"bid_bot3_ticks": [], "ask_bot3_ticks": [], "bid_bot3_mode": {}, "ask_bot3_mode": {}}
    for idx in range(len(prices)):
        ts = prices["timestamp"].iloc[idx]
        f = fv_arr[idx]
        # Bid bot-3: any bid price in (floor(F)-5, floor(F)+5) that's NOT the inner_bid
        bid_prices = [prices[f"bid_price_{i}"].iloc[idx] for i in (1, 2, 3)]
        bid_prices = [bp for bp in bid_prices if pd.notna(bp)]
        # Find any bid with offset in [-5, +5] — that's bot-3 territory
        bot3_bid_offs = []
        for bp in bid_prices:
            off = bp - f
            if -5 <= off <= 5 and off != inner_bid_off:
                # not the inner — it's a bot-3
                bot3_bid_offs.append(int(off))
        if bot3_bid_offs:
            results["bid_bot3_ticks"].append(ts)
            for off in bot3_bid_offs:
                results["bid_bot3_mode"][off] = results["bid_bot3_mode"].get(off, 0) + 1

        ask_prices = [prices[f"ask_price_{i}"].iloc[idx] for i in (1, 2, 3)]
        ask_prices = [ap for ap in ask_prices if pd.notna(ap)]
        bot3_ask_offs = []
        for ap in ask_prices:
            off = ap - f
            if -5 <= off <= 5 and off != inner_ask_off:
                bot3_ask_offs.append(int(off))
        if bot3_ask_offs:
            results["ask_bot3_ticks"].append(ts)
            for off in bot3_ask_offs:
                results["ask_bot3_mode"][off] = results["ask_bot3_mode"].get(off, 0) + 1
    return results


def intertick_gap_stats(event_timestamps: list[int]) -> dict:
    if len(event_timestamps) < 2:
        return {"n": len(event_timestamps)}
    diffs = np.diff(event_timestamps)
    return {
        "n": len(event_timestamps),
        "gap_mean": float(diffs.mean()),
        "gap_median": float(np.median(diffs)),
        "gap_mode": int(np.bincount(diffs).argmax()) if diffs.max() < 10000 else None,
        "gap_p10": int(np.percentile(diffs, 10)),
        "gap_p90": int(np.percentile(diffs, 90)),
        "gap_unique_top5": dict(zip(*np.unique(diffs, return_counts=True)))  # raw
    }


def main() -> None:
    print("=" * 80)
    print("R2 bot reconnaissance")
    print("=" * 80)

    for product in ("OSM", "PEP"):
        print(f"\n### {product} ({PRODUCTS[product]}) ###")
        for day in DAYS:
            prices = load_prices(day, product)
            trades = load_trades(day, product)
            fv_arr = fv(product, day, prices["timestamp"].values)
            print(f"\n--- day {day} --- ticks={len(prices)}, trades={len(trades)}")

            # 1. level count
            lc = level_count_distribution(prices)
            print(f"  level-count: bid={lc['bid']}, ask={lc['ask']}")

            # 2. offset dist for L1-3
            od = offset_distribution(prices, fv_arr)
            for key in sorted(od.keys()):
                info = od[key]
                top5 = sorted(info["unique_offsets"].items(), key=lambda x: -x[1])[:5]
                print(f"  {key}: vol_mean={info['vol_mean']:.1f}  top_offsets={top5}")

            # 3. bot-3 detection
            b3 = bot3_detection(prices, fv_arr, product)
            print(f"  bid bot-3 ticks: {len(b3['bid_bot3_ticks'])}/{len(prices)}  ({100*len(b3['bid_bot3_ticks'])/len(prices):.1f}%)")
            print(f"  ask bot-3 ticks: {len(b3['ask_bot3_ticks'])}/{len(prices)}  ({100*len(b3['ask_bot3_ticks'])/len(prices):.1f}%)")
            bidmode = sorted(b3["bid_bot3_mode"].items(), key=lambda x: -x[1])[:6]
            askmode = sorted(b3["ask_bot3_mode"].items(), key=lambda x: -x[1])[:6]
            print(f"  bid bot-3 offsets: {bidmode}")
            print(f"  ask bot-3 offsets: {askmode}")

            # 4. bot-3 timing
            stats_bid = intertick_gap_stats(b3["bid_bot3_ticks"])
            stats_ask = intertick_gap_stats(b3["ask_bot3_ticks"])
            def summarise(stats):
                if "gap_mean" not in stats:
                    return f"n={stats['n']}"
                top = sorted(stats["gap_unique_top5"].items(), key=lambda x: -x[1])[:5]
                return f"gap_mean={stats['gap_mean']:.0f} med={stats['gap_median']:.0f} top_gaps={top}"
            print(f"  bid bot-3 gap: {summarise(stats_bid)}")
            print(f"  ask bot-3 gap: {summarise(stats_ask)}")

            # 5. trade-side breakdown (who's the taker?)
            if not trades.empty:
                # trade price relative to snapshot mid
                # merge trades with latest book
                prices_idx = prices.set_index("timestamp")
                trade_sides = []
                for _, tr in trades.iterrows():
                    ts = tr["timestamp"]
                    # find book at same ts
                    if ts in prices_idx.index:
                        b = prices_idx.loc[ts]
                        bid1 = b["bid_price_1"]
                        ask1 = b["ask_price_1"]
                        if pd.notna(bid1) and pd.notna(ask1):
                            mid = (bid1 + ask1) / 2.0
                            if tr["price"] >= ask1 - 0.0001:
                                trade_sides.append("buy_hit_ask")
                            elif tr["price"] <= bid1 + 0.0001:
                                trade_sides.append("sell_hit_bid")
                            else:
                                trade_sides.append("inside")
                from collections import Counter
                c = Counter(trade_sides)
                print(f"  trade-side: {dict(c)}")


if __name__ == "__main__":
    main()
