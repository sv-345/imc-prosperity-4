"""Characterize the deterministic taker schedule.

Questions:
A) Is direction (buy vs sell) deterministic across days?
B) How many ticks per day have DETERMINISTIC-SIDE predictable events?
C) If we KNEW the schedule, how much PnL could we capture vs iter23?
"""
from __future__ import annotations
import pathlib
import pandas as pd
from collections import defaultdict

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "ROUND_2"
PRODUCTS = {"OSM": "ASH_COATED_OSMIUM", "PEP": "INTARIAN_PEPPER_ROOT"}


def load_trades(day, product):
    t = pd.read_csv(DATA / f"trades_round_2_day_{day}.csv", sep=";")
    return t[t["symbol"] == PRODUCTS[product]].sort_values("timestamp").reset_index(drop=True)


def load_prices(day, product):
    p = pd.read_csv(DATA / f"prices_round_2_day_{day}.csv", sep=";")
    p = p[p["product"] == PRODUCTS[product]].sort_values("timestamp").reset_index(drop=True)
    p["mid"] = (p["bid_price_1"] + p["ask_price_1"]) / 2.0
    return p


def classify(p, tr):
    ts = int(tr["timestamp"])
    row = p[p["timestamp"] == ts]
    if row.empty: return None
    bid1, ask1 = row["bid_price_1"].iloc[0], row["ask_price_1"].iloc[0]
    if pd.notna(ask1) and abs(tr["price"] - ask1) < 0.01: return "BUY"
    if pd.notna(bid1) and abs(tr["price"] - bid1) < 0.01: return "SELL"
    if pd.notna(bid1) and pd.notna(ask1):
        if tr["price"] > (bid1 + ask1) / 2: return "BUY"
        return "SELL"
    return None


def main():
    for product in ("OSM", "PEP"):
        print(f"\n{'='*100}\n{product}  —  SCHEDULE DIRECTION DETERMINISM\n{'='*100}")

        # For each ts, collect (day, qty_list, direction_list) tuples
        ts_data: dict[int, dict[int, list]] = defaultdict(lambda: {})
        for day in (-1, 0, 1):
            p = load_prices(day, product)
            trs = load_trades(day, product)
            ts_grouped: dict[int, list] = defaultdict(list)
            for _, tr in trs.iterrows():
                cls = classify(p, tr)
                ts_grouped[int(tr["timestamp"])].append((int(tr["quantity"]), cls))
            for ts, entries in ts_grouped.items():
                # sort by qty for canonical comparison
                entries.sort()
                ts_data[ts][day] = entries

        # Classify timestamps
        total_ts = len(ts_data)
        all3_same_qty = 0
        all3_same_qty_and_dir = 0
        all3_same_dir_only = 0    # qty may vary but dir is consistent
        schedule_trades_sum = 0  # sum of qty × days with the deterministic event

        for ts, by_day in ts_data.items():
            if len(by_day) < 3: continue
            qtys_tup = tuple(sorted(tuple(q for q, _ in by_day[d]) for d in (-1, 0, 1)))
            if len(set(qtys_tup)) == 1:  # all 3 days have same qty list
                all3_same_qty += 1
                # check direction
                dirs = tuple(sorted(tuple(d_ for _, d_ in by_day[d]) for d in (-1, 0, 1)))
                if len(set(dirs)) == 1 and all(x != (None,) for x in dirs):
                    all3_same_qty_and_dir += 1
                    # Add to count
                    for d in (-1, 0, 1):
                        for q, _ in by_day[d]:
                            schedule_trades_sum += q

        print(f"  total unique trade-ts across 3 days: {total_ts}")
        print(f"  on all 3 days with same qty list: {all3_same_qty}")
        print(f"  on all 3 days with same qty + same direction: {all3_same_qty_and_dir}")
        print(f"  total scheduled qty (sum across 3 days, deterministic events): {schedule_trades_sum}")

        # Sample: first 20 deterministic events with direction
        print(f"\n  first 20 deterministic events (ts, qty_list, direction):")
        n = 0
        for ts in sorted(ts_data.keys()):
            if n >= 20: break
            by_day = ts_data[ts]
            if len(by_day) < 3: continue
            qtys_tup = tuple(sorted(tuple(q for q, _ in by_day[d]) for d in (-1, 0, 1)))
            if len(set(qtys_tup)) != 1: continue
            dirs = tuple(sorted(tuple(d_ for _, d_ in by_day[d]) for d in (-1, 0, 1)))
            if len(set(dirs)) != 1: continue
            any_day = next(iter(by_day.values()))
            qs = [q for q, _ in any_day]
            ds = [d for _, d in any_day]
            print(f"    ts={ts:>7d}  qtys={qs}  directions={ds}")
            n += 1

        # Estimate: fraction of taker flow that's deterministic
        total_qty = 0; det_qty = 0
        for day in (-1, 0, 1):
            trs = load_trades(day, product)
            total_qty += int(trs["quantity"].sum())
        det_qty = schedule_trades_sum  # total deterministic qty across 3 days
        print(f"\n  3-day total taker qty: {total_qty}")
        print(f"  3-day deterministic taker qty: {det_qty} ({100*det_qty/max(total_qty,1):.1f}%)")

        # Direction balance in deterministic schedule
        buy_qty = sell_qty = 0
        for ts, by_day in ts_data.items():
            if len(by_day) < 3: continue
            qtys_tup = tuple(sorted(tuple(q for q, _ in by_day[d]) for d in (-1, 0, 1)))
            if len(set(qtys_tup)) != 1: continue
            dirs = tuple(sorted(tuple(d_ for _, d_ in by_day[d]) for d in (-1, 0, 1)))
            if len(set(dirs)) != 1: continue
            any_day = next(iter(by_day.values()))
            for q, d in any_day:
                if d == "BUY": buy_qty += q * 3  # 3 days
                elif d == "SELL": sell_qty += q * 3
        print(f"  deterministic BUY-taker qty: {buy_qty}")
        print(f"  deterministic SELL-taker qty: {sell_qty}")


if __name__ == "__main__":
    main()
