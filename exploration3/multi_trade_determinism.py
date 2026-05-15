"""Multi-trade timestamps — are they DETERMINISTIC across days?

Finding: ts=15100 has qty split (2,8) on all 3 days. Same for 96900.
Hypothesis: there's a seeded bot-taker schedule keyed on timestamp.

Test: enumerate all multi-trade ticks across all 3 days, check cross-day
overlap + qty stability.

Then: identify SINGLE-trade ticks that appear on the same ts across
days with the same qty (deterministic singletons).
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


def main():
    for product in ("OSM", "PEP"):
        print(f"\n{'='*100}\n{product}  —  DETERMINISTIC TRADE SCHEDULE?\n{'='*100}")

        # Build per-day trade map: ts -> list of qtys (sorted to match)
        per_day_trades: dict[int, dict[int, list]] = {}
        for day in (-1, 0, 1):
            trs = load_trades(day, product)
            ts_map = defaultdict(list)
            for _, r in trs.iterrows():
                ts_map[int(r["timestamp"])].append(int(r["quantity"]))
            # sort for canonical comparison
            for ts in ts_map:
                ts_map[ts].sort()
            per_day_trades[day] = dict(ts_map)

        # Union of all timestamps that appeared on ANY day
        all_ts = set()
        for day in per_day_trades:
            all_ts.update(per_day_trades[day].keys())

        # Classify each ts by presence across days
        all3 = 0; ex_all3 = 0   # exact qty match on all 3 days
        any2 = 0; ex_2 = 0
        only_1 = 0

        cross_day_identical = []   # (ts, qty_list) — same on all 3 days
        for ts in sorted(all_ts):
            qtys_by_day = {d: per_day_trades[d].get(ts) for d in (-1, 0, 1)}
            present_count = sum(1 for v in qtys_by_day.values() if v is not None)
            if present_count == 3:
                all3 += 1
                # same qty list?
                qlists = [tuple(q) for q in qtys_by_day.values()]
                if len(set(qlists)) == 1:
                    ex_all3 += 1
                    cross_day_identical.append((ts, qlists[0]))
            elif present_count == 2:
                any2 += 1
                qs_present = [tuple(v) for v in qtys_by_day.values() if v is not None]
                if len(set(qs_present)) == 1:
                    ex_2 += 1
            else:
                only_1 += 1

        print(f"  total unique trade-timestamps across 3 days: {len(all_ts)}")
        print(f"  present on all 3 days: {all3}  (of which EXACT qty match: {ex_all3})")
        print(f"  present on any 2 days: {any2}  (exact match on those 2: {ex_2})")
        print(f"  present on only 1 day:  {only_1}")
        # Baseline: if 3 days were independent random samples, P(same-ts on all 3) = small
        # For OSM: ~470 trades/day over 10000 ticks = 4.7% per-tick trade prob
        # P(trade on all 3 days at same ts) = 0.047^3 = 0.01% = ~1 ts out of 10000
        # We observe {all3} — compare to ~1 expected

        # Sample of cross-day identical trades
        print(f"\n  first 20 cross-day-identical trade events (same ts, same qty list all 3 days):")
        for ts, qtys in cross_day_identical[:20]:
            print(f"    ts={ts:>7d}  qtys={qtys}")

        # Check: is the TRADE PRICE also consistent (offset from FV)?
        if cross_day_identical:
            print(f"\n  price analysis for cross-day-identical events — px relative to FV:")
            for ts, qtys in cross_day_identical[:10]:
                pxs_by_day = {}
                for day in (-1, 0, 1):
                    trs = load_trades(day, product)
                    rows = trs[trs["timestamp"] == ts].sort_values("quantity")
                    pxs_by_day[day] = list(rows["price"])
                # Get FV for that ts
                if product == "OSM":
                    fv = 10001
                    offs = {d: [p - fv for p in pxs_by_day[d]] for d in (-1, 0, 1)}
                else:
                    tick_idx = ts // 100
                    offs = {}
                    for d in (-1, 0, 1):
                        day_start = {-1: 11000, 0: 12000, 1: 13000}[d]
                        fv = day_start + 0.1 * tick_idx
                        offs[d] = [p - fv for p in pxs_by_day[d]]
                print(f"    ts={ts}  offsets_from_fv: d-1={offs[-1]}  d0={offs[0]}  d1={offs[1]}")


if __name__ == "__main__":
    main()
