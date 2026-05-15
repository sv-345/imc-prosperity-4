"""Validate candidate rule 1 — PEP aggressive-bid take.

For each day, run a minimal simulator that:
- Iterates through prices CSV tick-by-tick.
- On each tick, examines the PEP book.
- If any bid level has price >= floor(FV), submit a sell at that price for qty=min(bid_vol, remaining_short_cap).
- Record fills: cash += price * qty.
- Mark-to-market at end: MTM = cash + position * final_mid.

Two variants:
  (A) "take only": take agg_bid and agg_ask. No ongoing MM. Measures pure signal.
  (B) "take + defer exit": same as A but unwind position at a later tick,
      giving realistic capture.

We also report: how many of the events we captured (filled), how many
iter23 would've captured (0 for agg_bid, some for agg_ask via ap<fv_int).
"""
from __future__ import annotations
import pathlib
import numpy as np
import pandas as pd
from collections import defaultdict

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


def simulate_rule1(day: int, product: str, pos_limit: int = 100, take_sides: str = "both",
                   unwind_at_mid: bool = True) -> dict:
    """Run the 'hit aggressive quotes' strategy on one day.

    take_sides: 'bid' / 'ask' / 'both'. 'bid' means take aggressive bids (=sell).
    unwind_at_mid: after taking, mark-to-market on next-tick mid (approximates immediate unwind).
    """
    p = load(day, product)
    fv = fv_day(day, p["timestamp"].values, product)
    floor_fv = np.floor(fv).astype(int)

    cash = 0.0
    position = 0  # signed: + long, - short
    fills: list[dict] = []
    captured_bid_events = 0
    captured_ask_events = 0
    total_bid_events = 0
    total_ask_events = 0

    for i in range(len(p)):
        ff = floor_fv[i]
        ts = p["timestamp"].iloc[i]

        # Collect all bids and asks with offsets
        bid_pool = []  # list of (price, vol)
        ask_pool = []
        for k in (1, 2, 3):
            bp = p[f"bid_price_{k}"].iloc[i]
            bv = p[f"bid_volume_{k}"].iloc[i]
            ap = p[f"ask_price_{k}"].iloc[i]
            av = p[f"ask_volume_{k}"].iloc[i]
            if pd.notna(bp): bid_pool.append((int(bp), int(bv)))
            if pd.notna(ap): ask_pool.append((int(ap), int(av)))

        # Detect aggressive events
        agg_bids = [(px, vol) for (px, vol) in bid_pool if px >= ff]
        agg_asks = [(px, vol) for (px, vol) in ask_pool if px <= ff]

        if agg_bids:
            total_bid_events += 1
            if take_sides in ("bid", "both"):
                # sell at agg bid prices, highest first (best price for us)
                agg_bids.sort(reverse=True)
                for (px, vol) in agg_bids:
                    # short cap: position - (-pos_limit) = position + pos_limit
                    short_cap = pos_limit + position
                    if short_cap <= 0:
                        break
                    qty = min(vol, short_cap)
                    if qty > 0:
                        cash += px * qty
                        position -= qty
                        fills.append(dict(ts=ts, side="SELL", px=px, qty=qty))
                        captured_bid_events += 1

        if agg_asks:
            total_ask_events += 1
            if take_sides in ("ask", "both"):
                agg_asks.sort()
                for (px, vol) in agg_asks:
                    long_cap = pos_limit - position
                    if long_cap <= 0:
                        break
                    qty = min(vol, long_cap)
                    if qty > 0:
                        cash -= px * qty
                        position += qty
                        fills.append(dict(ts=ts, side="BUY", px=px, qty=qty))
                        captured_ask_events += 1

        # Unwind policy: after 1 tick, MTM at next-tick's normal mid
        # (we don't actually unwind in this simulator — we track ending PnL)

    # Mark-to-market at end of day using final inner mid
    final_bid = p["bid_price_1"].iloc[-1]
    final_ask = p["ask_price_1"].iloc[-1]
    final_mid = (final_bid + final_ask) / 2.0
    mtm = cash + position * final_mid

    # FV-based MTM (cleaner — no bid-ask bounce)
    final_fv = fv[-1]
    mtm_fv = cash + position * final_fv

    return dict(
        day=day,
        cash=cash,
        position=position,
        final_mid=final_mid,
        final_fv=final_fv,
        mtm_mid=mtm,
        mtm_fv=mtm_fv,
        n_fills=len(fills),
        total_bid_events=total_bid_events,
        total_ask_events=total_ask_events,
        captured_bid_events=captured_bid_events,
        captured_ask_events=captured_ask_events,
        fills=fills,
    )


def simulate_rule1_with_unwind(day: int, product: str, pos_limit: int = 100) -> dict:
    """More realistic: after hitting aggressive quote, unwind on NEXT tick at mid."""
    p = load(day, product)
    fv = fv_day(day, p["timestamp"].values, product)
    floor_fv = np.floor(fv).astype(int)

    cash = 0.0
    position = 0
    fills: list[dict] = []
    unwind_queue: list[tuple[int, int]] = []  # (qty_to_trade, next_idx) where qty is signed

    for i in range(len(p)):
        ff = floor_fv[i]
        ts = p["timestamp"].iloc[i]

        # Unwind anything due this tick
        next_bid = p["bid_price_1"].iloc[i]
        next_ask = p["ask_price_1"].iloc[i]
        if pd.notna(next_bid) and pd.notna(next_ask):
            mid_now = (next_bid + next_ask) / 2.0
            new_q = []
            for (qty, when) in unwind_queue:
                if when <= i:
                    # cover at mid
                    if qty < 0:   # short -> buy back
                        cover_qty = -qty
                        cash -= mid_now * cover_qty
                        position += cover_qty
                    else:
                        cash += mid_now * qty
                        position -= qty
                else:
                    new_q.append((qty, when))
            unwind_queue = new_q

        # Scan book
        bid_pool, ask_pool = [], []
        for k in (1, 2, 3):
            bp = p[f"bid_price_{k}"].iloc[i]
            bv = p[f"bid_volume_{k}"].iloc[i]
            ap = p[f"ask_price_{k}"].iloc[i]
            av = p[f"ask_volume_{k}"].iloc[i]
            if pd.notna(bp): bid_pool.append((int(bp), int(bv)))
            if pd.notna(ap): ask_pool.append((int(ap), int(av)))

        agg_bids = sorted([(px, vol) for (px, vol) in bid_pool if px >= ff], reverse=True)
        agg_asks = sorted([(px, vol) for (px, vol) in ask_pool if px <= ff])

        for (px, vol) in agg_bids:
            short_cap = pos_limit + position
            if short_cap <= 0: break
            qty = min(vol, short_cap)
            if qty > 0:
                cash += px * qty
                position -= qty
                fills.append(dict(ts=ts, side="SELL", px=px, qty=qty))
                unwind_queue.append((-qty, i + 1))

        for (px, vol) in agg_asks:
            long_cap = pos_limit - position
            if long_cap <= 0: break
            qty = min(vol, long_cap)
            if qty > 0:
                cash -= px * qty
                position += qty
                fills.append(dict(ts=ts, side="BUY", px=px, qty=qty))
                unwind_queue.append((qty, i + 1))

    # Flush any remaining unwinds
    final_mid = (p["bid_price_1"].iloc[-1] + p["ask_price_1"].iloc[-1]) / 2
    for (qty, when) in unwind_queue:
        if qty < 0:
            cash -= final_mid * (-qty)
            position += (-qty)
        else:
            cash += final_mid * qty
            position -= qty
    return dict(day=day, cash=cash, position=position, n_fills=len(fills))


def main() -> None:
    print("=" * 100)
    print("RULE 1 VALIDATION — PEP aggressive-quote take")
    print("=" * 100)

    # Variant A: no unwind, MTM at final mid
    print("\n## Variant A: hold-and-MTM at final mid ##\n")
    for product in ("PEP", "OSM"):
        print(f"\n### {product} — take both sides ###")
        total_mtm = 0
        total_captured_bid = 0
        total_bid_events = 0
        total_captured_ask = 0
        total_ask_events = 0
        for day in (-1, 0, 1):
            r = simulate_rule1(day, product, pos_limit=100, take_sides="both")
            print(f"  day {day}: fills={r['n_fills']:3d}  pos_end={r['position']:+4d}  "
                  f"cash={r['cash']:+10.2f}  MTM_mid={r['mtm_mid']:+10.2f}  MTM_fv={r['mtm_fv']:+10.2f}  "
                  f"agg_bid_captured={r['captured_bid_events']}/{r['total_bid_events']}  "
                  f"agg_ask_captured={r['captured_ask_events']}/{r['total_ask_events']}")
            total_mtm += r["mtm_fv"]
            total_captured_bid += r["captured_bid_events"]
            total_bid_events += r["total_bid_events"]
            total_captured_ask += r["captured_ask_events"]
            total_ask_events += r["total_ask_events"]
        print(f"  total 3-day MTM_fv: ${total_mtm:.2f}")
        print(f"  per 10k-tick day avg: ${total_mtm/3:.2f}")
        print(f"  bid capture: {total_captured_bid}/{total_bid_events}  ask capture: {total_captured_ask}/{total_ask_events}")

    # Variant B: 1-tick unwind
    print("\n\n## Variant B: unwind on next tick at mid ##\n")
    for product in ("PEP", "OSM"):
        print(f"\n### {product} ###")
        total_cash = 0
        for day in (-1, 0, 1):
            r = simulate_rule1_with_unwind(day, product, pos_limit=100)
            print(f"  day {day}: fills={r['n_fills']:3d}  pos_end={r['position']:+4d}  cash={r['cash']:+10.2f}")
            total_cash += r["cash"]
        print(f"  total 3-day cash: ${total_cash:.2f}")
        print(f"  per 10k-tick day avg: ${total_cash/3:.2f}")

    # Variant C: take only aggressive bids on PEP (since iter23 already does agg_ask on OSM & some on PEP)
    print("\n\n## Variant C: PEP aggressive-BID only (isolating the missed alpha) ##\n")
    total_mtm = 0
    for day in (-1, 0, 1):
        r = simulate_rule1(day, "PEP", pos_limit=100, take_sides="bid")
        print(f"  day {day}: fills={r['n_fills']:3d}  pos_end={r['position']:+4d}  cash={r['cash']:+10.2f}  "
              f"MTM_mid={r['mtm_mid']:+10.2f}  MTM_fv={r['mtm_fv']:+10.2f}  "
              f"captured_events={r['captured_bid_events']}/{r['total_bid_events']}")
        total_mtm += r["mtm_fv"]
    print(f"  total 3-day MTM_fv: ${total_mtm:.2f}")
    print(f"  per 10k-tick day avg: ${total_mtm/3:.2f}")


if __name__ == "__main__":
    main()
