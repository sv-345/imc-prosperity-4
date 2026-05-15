"""Extract deterministic taker schedule from 3-day training data.

Output: Python dict literal of `{ts: [(direction, qty), ...]}` saved
to exploration3/osm_schedule.py and pep_schedule.py for hardcoding.

Only includes ts that have SAME qty list + SAME direction list on all
3 days. This is the 'guaranteed' portion.
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
    return p[p["product"] == PRODUCTS[product]].sort_values("timestamp").reset_index(drop=True)


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
        ts_data: dict[int, dict[int, list]] = defaultdict(lambda: {})
        for day in (-1, 0, 1):
            p = load_prices(day, product)
            trs = load_trades(day, product)
            ts_grouped: dict[int, list] = defaultdict(list)
            for _, tr in trs.iterrows():
                cls = classify(p, tr)
                if cls is None: continue
                ts_grouped[int(tr["timestamp"])].append((cls, int(tr["quantity"])))
            for ts, entries in ts_grouped.items():
                entries.sort()
                ts_data[ts][day] = entries

        # Keep only ts with same (sorted) tuple on all 3 days
        schedule: dict[int, list] = {}
        for ts, by_day in ts_data.items():
            if len(by_day) < 3: continue
            tuples = tuple(tuple(by_day[d]) for d in (-1, 0, 1))
            if len(set(tuples)) == 1:
                schedule[ts] = list(tuples[0])

        # Write as Python literal
        out = ROOT / "exploration3" / f"{product.lower()}_schedule.py"
        with out.open("w") as f:
            f.write(f'# Auto-generated deterministic taker schedule for {product}\n')
            f.write(f'# Extracted from 3-day R2 training CSVs; ts -> [(direction, qty), ...]\n')
            f.write(f'# n_scheduled_ticks = {len(schedule)}\n\n')
            f.write(f'{product}_SCHEDULE = {{\n')
            for ts in sorted(schedule.keys()):
                items = schedule[ts]
                items_str = ", ".join(f'("{d}", {q})' for d, q in items)
                f.write(f'    {ts}: [{items_str}],\n')
            f.write('}\n')
        print(f"wrote {out} — {len(schedule)} scheduled ts")

        # Quick stats
        buy_qty = sum(q for items in schedule.values() for d, q in items if d == "BUY")
        sell_qty = sum(q for items in schedule.values() for d, q in items if d == "SELL")
        print(f"  BUY qty: {buy_qty}, SELL qty: {sell_qty}")


if __name__ == "__main__":
    main()
