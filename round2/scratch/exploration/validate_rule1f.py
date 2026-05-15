"""iter23-like OSM simulator — with and without a TIGHTENED take gate.

iter23's OSM gate is `ap >= fv=10001` and `bp <= fv=10001`. But actual mid
drifts around 10003-10004. The stale gate misses:
- Asks at 10002-10004 that are "aggressive" vs actual mid but iter23 skips.
- Bids at 10000-10002 that are "aggressive" vs actual mid but iter23 skips.

This replaces the constant 10001 with a dynamic reference (rolling-median mid).
"""
from __future__ import annotations
import pathlib
import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "ROUND_2"


def load(day: int):
    p = pd.read_csv(DATA / f"prices_round_2_day_{day}.csv", sep=";")
    t = pd.read_csv(DATA / f"trades_round_2_day_{day}.csv", sep=";")
    p = p[p["product"] == "ASH_COATED_OSMIUM"].sort_values("timestamp").reset_index(drop=True)
    t = t[t["symbol"] == "ASH_COATED_OSMIUM"].sort_values("timestamp").reset_index(drop=True)
    p["mid"] = (p["bid_price_1"] + p["ask_price_1"]) / 2.0
    return p, t


def rolling_ref(p: pd.DataFrame, window: int = 51) -> pd.Series:
    return p["mid"].rolling(window, center=True, min_periods=5).median()


def bb_ba(row):
    bid = row["bid_price_1"]
    ask = row["ask_price_1"]
    return (int(bid) if pd.notna(bid) else None, int(ask) if pd.notna(ask) else None)


def step_book(row):
    bids, asks = {}, {}
    for k in (1, 2, 3):
        bp = row[f"bid_price_{k}"]; bv = row[f"bid_volume_{k}"]
        ap = row[f"ask_price_{k}"]; av = row[f"ask_volume_{k}"]
        if pd.notna(bp): bids[int(bp)] = int(bv)
        if pd.notna(ap): asks[int(ap)] = int(av)
    return bids, asks


OSM_FV_STATIC = 10001
LIMIT = 50  # OSM pos limit


def simulate(day: int, fv_mode: str = "static") -> dict:
    """
    fv_mode:
      'static'  — iter23 stock: fv=10001
      'rolling' — dynamic: fv = rolling median mid (51-tick centered)
    """
    p, trades = load(day)
    p["ref"] = rolling_ref(p, window=51)
    cash = 0.0
    position = 0
    my_orders_next = []

    n = len(p)
    # inner-mid helper (iter23's _inner_mid: (bb+ba)/2 when spread reasonable)
    for i in range(n):
        row = p.iloc[i]
        bids, asks = step_book(row)
        bb, ba = bb_ba(row)

        # Determine fv gate
        if fv_mode == "static":
            fv_gate = OSM_FV_STATIC
        else:
            r = p["ref"].iloc[i]
            fv_gate = int(round(r)) if pd.notna(r) else OSM_FV_STATIC

        dynamic_fv = (bb + ba) / 2.0 if bb is not None and ba is not None else fv_gate

        # Execute resting orders from prev tick
        for (op, oq) in my_orders_next:
            if oq > 0:
                need = oq; filled = 0
                for ap_px in sorted(asks):
                    if ap_px > op or filled >= need: break
                    avail = asks[ap_px]
                    take = min(avail, need - filled)
                    if take > 0:
                        cash -= ap_px * take
                        position += take
                        filled += take
            else:
                need = -oq; filled = 0
                for bp_px in sorted(bids, reverse=True):
                    if bp_px < op or filled >= need: break
                    avail = bids[bp_px]
                    take = min(avail, need - filled)
                    if take > 0:
                        cash += bp_px * take
                        position -= take
                        filled += take
        my_orders_next = []

        # Take-ask: cross any ask < fv_gate if vol<=9 or real_edge>=2
        for apx in sorted(asks.keys()):
            if apx >= fv_gate: break
            vol = asks[apx]
            real_edge = dynamic_fv - apx
            if vol <= 9 or real_edge >= 2:
                cap = LIMIT - position
                if cap <= 0: break
                q = min(vol, cap)
                if q > 0:
                    cash -= apx * q
                    position += q
                    asks[apx] -= q

        # Take-bid: cross any bid > fv_gate if vol<=9 or real_edge>=2
        for bpx in sorted(bids.keys(), reverse=True):
            if bpx <= fv_gate: break
            vol = bids[bpx]
            real_edge = bpx - dynamic_fv
            if vol <= 9 or real_edge >= 2:
                cap = LIMIT + position
                if cap <= 0: break
                q = min(vol, cap)
                if q > 0:
                    cash += bpx * q
                    position -= q
                    bids[bpx] -= q

        # iter23-like quoting
        edge = 20
        buy_cap = max(0, LIMIT - position)
        sell_cap = max(0, LIMIT + position)
        if bb is not None and ba is not None:
            bid_pj = min(bb + 1, fv_gate - 1)
            ask_pj = max(ba - 1, fv_gate + 1)
            bid_edge = fv_gate - edge
            ask_edge = fv_gate + edge
            mi = 15
            if bid_pj <= bid_edge:
                if buy_cap > 0:
                    my_orders_next.append((bid_edge, buy_cap))
            else:
                bpj = min(mi, buy_cap)
                be = buy_cap - bpj
                if be > 0: my_orders_next.append((bid_edge, be))
                if bpj > 0: my_orders_next.append((bid_pj, bpj))
            if ask_pj >= ask_edge:
                if sell_cap > 0:
                    my_orders_next.append((ask_edge, -sell_cap))
            else:
                spj = min(mi, sell_cap)
                se = sell_cap - spj
                if se > 0: my_orders_next.append((ask_edge, -se))
                if spj > 0: my_orders_next.append((ask_pj, -spj))

    final_mid = (p["bid_price_1"].iloc[-1] + p["ask_price_1"].iloc[-1]) / 2
    mtm_mid = cash + position * final_mid
    mtm_fv = cash + position * OSM_FV_STATIC
    return dict(day=day, cash=cash, position=position, mtm_mid=mtm_mid, mtm_fv=mtm_fv, final_mid=final_mid)


def main() -> None:
    print("=" * 100)
    print("iter23-like OSM simulator: static fv=10001 vs rolling-mid dynamic fv")
    print("=" * 100)

    for label, mode in [("static fv=10001", "static"), ("rolling-mid dynamic fv", "rolling")]:
        total_mid = 0; total_fv = 0
        detail = []
        for day in (-1, 0, 1):
            r = simulate(day, fv_mode=mode)
            detail.append(r)
            total_mid += r["mtm_mid"]
            total_fv += r["mtm_fv"]
        print(f"\n{label}")
        for r in detail:
            print(f"  day {r['day']}: cash={r['cash']:+10.0f}  pos={r['position']:+4d}  "
                  f"MTM_mid={r['mtm_mid']:+10.0f}  MTM_fv={r['mtm_fv']:+10.0f}  final_mid={r['final_mid']:.1f}")
        print(f"  TOTAL 3-day MTM_mid={total_mid:+.0f}  MTM_fv={total_fv:+.0f}  avg/day_mid={total_mid/3:+.0f}")


if __name__ == "__main__":
    main()
