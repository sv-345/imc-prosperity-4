"""OSM simulator variants:
  A) static quote + static take gate (iter23 as-is)
  B) static quote + DYNAMIC take gate (uses inner_mid as take reference)
  C) DYNAMIC quote + DYNAMIC take gate (both use dynamic)
  D) rolling-window gate (wider smoothing)

Goal: isolate which of these captures the $2-4k/day fix from the 305289 analysis.
"""
from __future__ import annotations
import pathlib
import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "ROUND_2"


def load(day: int):
    p = pd.read_csv(DATA / f"prices_round_2_day_{day}.csv", sep=";")
    p = p[p["product"] == "ASH_COATED_OSMIUM"].sort_values("timestamp").reset_index(drop=True)
    p["mid"] = (p["bid_price_1"] + p["ask_price_1"]) / 2.0
    return p


def rolling_ref(p: pd.DataFrame, window: int = 51) -> pd.Series:
    return p["mid"].rolling(window, center=True, min_periods=5).median()


def bb_ba(row):
    bid = row["bid_price_1"]; ask = row["ask_price_1"]
    return (int(bid) if pd.notna(bid) else None, int(ask) if pd.notna(ask) else None)


def step_book(row):
    bids, asks = {}, {}
    for k in (1, 2, 3):
        bp = row[f"bid_price_{k}"]; bv = row[f"bid_volume_{k}"]
        ap = row[f"ask_price_{k}"]; av = row[f"ask_volume_{k}"]
        if pd.notna(bp): bids[int(bp)] = int(bv)
        if pd.notna(ap): asks[int(ap)] = int(av)
    return bids, asks


def simulate(day: int, take_gate: str = "static", quote_anchor: str = "static", take_edge: int = 2, take_vol: int = 9) -> dict:
    """
    take_gate:    'static' (10001) | 'dynamic' (inner_mid int) | 'rolling' (51-tick median mid)
    quote_anchor: 'static' | 'dynamic' | 'rolling'
    take_edge:    real_edge >= N to take (default 2)
    take_vol:     vol <= N also triggers take (default 9)
    """
    p = load(day)
    p["ref"] = rolling_ref(p, window=51)
    cash = 0.0
    position = 0
    my_orders_next: list[tuple[int, int]] = []
    LIMIT = 50

    for i in range(len(p)):
        row = p.iloc[i]
        bids, asks = step_book(row)
        bb, ba = bb_ba(row)

        dynamic_mid = (bb + ba) / 2.0 if bb is not None and ba is not None else None
        rolling_ref_v = p["ref"].iloc[i]

        def resolve(mode):
            if mode == "static": return 10001
            if mode == "dynamic" and dynamic_mid is not None: return int(round(dynamic_mid))
            if mode == "rolling" and pd.notna(rolling_ref_v): return int(round(rolling_ref_v))
            return 10001

        take_gate_v = resolve(take_gate)
        quote_anchor_v = resolve(quote_anchor)
        dynamic_fv = dynamic_mid if dynamic_mid is not None else 10001.0

        # Resting orders: fill against this tick's book
        for (op, oq) in my_orders_next:
            if oq > 0:
                need = oq; filled = 0
                for apx in sorted(asks):
                    if apx > op or filled >= need: break
                    avail = asks[apx]; take = min(avail, need - filled)
                    if take > 0:
                        cash -= apx * take; position += take; filled += take; asks[apx] -= take
            else:
                need = -oq; filled = 0
                for bpx in sorted(bids, reverse=True):
                    if bpx < op or filled >= need: break
                    avail = bids[bpx]; take = min(avail, need - filled)
                    if take > 0:
                        cash += bpx * take; position -= take; filled += take; bids[bpx] -= take
        my_orders_next = []

        # Take-ask
        for apx in sorted(asks.keys()):
            if apx >= take_gate_v: break
            vol = asks[apx]
            real_edge = dynamic_fv - apx
            if vol <= take_vol or real_edge >= take_edge:
                cap = LIMIT - position
                if cap <= 0: break
                q = min(vol, cap)
                if q > 0:
                    cash -= apx * q; position += q; asks[apx] -= q
        # Take-bid
        for bpx in sorted(bids.keys(), reverse=True):
            if bpx <= take_gate_v: break
            vol = bids[bpx]
            real_edge = bpx - dynamic_fv
            if vol <= take_vol or real_edge >= take_edge:
                cap = LIMIT + position
                if cap <= 0: break
                q = min(vol, cap)
                if q > 0:
                    cash += bpx * q; position -= q; bids[bpx] -= q

        # Quote: iter23-style with edge=20, mi=15
        edge = 20
        buy_cap = max(0, LIMIT - position)
        sell_cap = max(0, LIMIT + position)
        if bb is not None and ba is not None:
            bid_pj = min(bb + 1, quote_anchor_v - 1)
            ask_pj = max(ba - 1, quote_anchor_v + 1)
            bid_edge = quote_anchor_v - edge
            ask_edge = quote_anchor_v + edge
            mi = 15
            if bid_pj <= bid_edge:
                if buy_cap > 0: my_orders_next.append((bid_edge, buy_cap))
            else:
                bpj = min(mi, buy_cap); be = buy_cap - bpj
                if be > 0: my_orders_next.append((bid_edge, be))
                if bpj > 0: my_orders_next.append((bid_pj, bpj))
            if ask_pj >= ask_edge:
                if sell_cap > 0: my_orders_next.append((ask_edge, -sell_cap))
            else:
                spj = min(mi, sell_cap); se = sell_cap - spj
                if se > 0: my_orders_next.append((ask_edge, -se))
                if spj > 0: my_orders_next.append((ask_pj, -spj))

    final_mid = (p["bid_price_1"].iloc[-1] + p["ask_price_1"].iloc[-1]) / 2
    mtm_mid = cash + position * final_mid
    return dict(day=day, cash=cash, position=position, mtm_mid=mtm_mid, final_mid=final_mid)


def run_config(name: str, **kwargs) -> None:
    total = 0
    detail = []
    for day in (-1, 0, 1):
        r = simulate(day, **kwargs)
        detail.append(r)
        total += r["mtm_mid"]
    print(f"\n{name}")
    for r in detail:
        print(f"  day {r['day']}: cash={r['cash']:+9.0f}  pos={r['position']:+4d}  MTM_mid={r['mtm_mid']:+8.0f}  final_mid={r['final_mid']:.1f}")
    print(f"  TOTAL MTM_mid={total:+.0f}  avg/day={total/3:+.0f}")


def main() -> None:
    print("=" * 100)
    print("OSM — take gate and quote anchor variants")
    print("=" * 100)

    run_config("A) iter23 baseline: static take + static quote",
               take_gate="static", quote_anchor="static")
    run_config("B) DYNAMIC take + static quote",
               take_gate="dynamic", quote_anchor="static")
    run_config("C) DYNAMIC take + DYNAMIC quote",
               take_gate="dynamic", quote_anchor="dynamic")
    run_config("D) ROLLING take + static quote",
               take_gate="rolling", quote_anchor="static")
    run_config("E) ROLLING take + ROLLING quote",
               take_gate="rolling", quote_anchor="rolling")
    run_config("F) DYNAMIC take, no vol<=9 trigger (tighter)",
               take_gate="dynamic", quote_anchor="static", take_vol=0)
    run_config("G) DYNAMIC take, edge>=1 (looser)",
               take_gate="dynamic", quote_anchor="static", take_edge=1)


if __name__ == "__main__":
    main()
