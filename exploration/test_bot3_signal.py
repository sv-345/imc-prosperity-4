"""Test: do aggressive bot-3 quotes predict next-tick mid direction?

For PEP:
- Aggressive bid bot-3 = bid at offset ≥ 0 (from floor(FV)). Crossing into ask territory.
- Aggressive ask bot-3 = ask at offset ≤ 0. Crossing into bid territory.
Hypothesis: aggressive bid → mid rises; aggressive ask → mid falls.

For OSM (F=10001 constant):
- Same definition. Bot-3 passive at |offset|≥1 on own side; aggressive at |offset|≥1 crossing.

We measure mid_{t+k} - mid_t for k in {1, 2, 5, 10} after each event.

Also: compute forward markout (FV-referenced) = mid_{t+k} - mid_{t-0}.
Control: baseline random tick forward mid change.
"""
from __future__ import annotations
import pathlib
import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "ROUND_2"
PRODUCTS = {"OSM": "ASH_COATED_OSMIUM", "PEP": "INTARIAN_PEPPER_ROOT"}


def fv_of(product: str, day: int, ts: np.ndarray) -> np.ndarray:
    if product == "OSM":
        return np.full_like(ts, 10001.0, dtype=float)
    day_start = {-1: 11000, 0: 12000, 1: 13000}[day]
    return day_start + 0.1 * (ts // 100)


def load_day(day: int, product: str) -> pd.DataFrame:
    p = pd.read_csv(DATA / f"prices_round_2_day_{day}.csv", sep=";")
    p = p[p["product"] == PRODUCTS[product]].sort_values("timestamp").reset_index(drop=True)
    p["fv"] = fv_of(product, day, p["timestamp"].values)
    p["floor_fv"] = np.floor(p["fv"]).astype(int)
    p["mid"] = (p["bid_price_1"] + p["ask_price_1"]) / 2.0
    return p


def detrended_mid(p: pd.DataFrame) -> pd.Series:
    """mid - fv, so PEP drift is removed."""
    return p["mid"] - p["fv"]


def find_aggressive_events(p: pd.DataFrame, product: str) -> dict[str, list[int]]:
    """Return list of indices where an aggressive bot-3 quote is present.

    Aggressive = a quote on the "wrong" side of the floor-FV line.
    For BID (buyer side): aggressive = bid price >= floor(FV) [+]
    For ASK (seller side): aggressive = ask price <= floor(FV) [-]

    Also record 'passive' bot-3 for comparison:
    bid passive = bid price between floor(FV)-5 and floor(FV)-1 but NOT at inner.
    ask passive = ask price between floor(FV)+1 and floor(FV)+5 but NOT at inner.
    """
    if product == "OSM":
        inner_bid_off, inner_ask_off = -8, 8
    else:
        inner_bid_off, inner_ask_off = -6, 7  # PEP

    agg_bid = []   # bid crossing into ask side (off >= 0)
    agg_ask = []   # ask crossing into bid side (off <= 0)
    pass_bid = []  # bid at -1..-5 offset, not inner
    pass_ask = []  # ask at +1..+5 offset, not inner

    n = len(p)
    for i in range(n):
        floor_f = p["floor_fv"].iloc[i]
        bid_offs = []
        ask_offs = []
        for k in (1, 2, 3):
            bp = p[f"bid_price_{k}"].iloc[i]
            if pd.notna(bp):
                bid_offs.append(int(bp - floor_f))
            ap = p[f"ask_price_{k}"].iloc[i]
            if pd.notna(ap):
                ask_offs.append(int(ap - floor_f))
        has_agg_bid = any(o >= 0 for o in bid_offs)
        has_agg_ask = any(o <= 0 for o in ask_offs)
        has_pass_bid = any(-5 <= o <= -1 and o != inner_bid_off for o in bid_offs)
        has_pass_ask = any(1 <= o <= 5 and o != inner_ask_off for o in ask_offs)
        if has_agg_bid: agg_bid.append(i)
        if has_agg_ask: agg_ask.append(i)
        if has_pass_bid: pass_bid.append(i)
        if has_pass_ask: pass_ask.append(i)
    return dict(agg_bid=agg_bid, agg_ask=agg_ask, pass_bid=pass_bid, pass_ask=pass_ask)


def measure_forward(p: pd.DataFrame, event_idxs: list[int], horizons: list[int] = (1, 2, 5, 10)) -> dict:
    """For each event index i, compute detrended_mid[i+k] - detrended_mid[i] for each k."""
    d = detrended_mid(p).values
    out = {}
    for k in horizons:
        diffs = []
        for i in event_idxs:
            if i + k < len(d) and not (np.isnan(d[i]) or np.isnan(d[i + k])):
                diffs.append(d[i + k] - d[i])
        if diffs:
            a = np.array(diffs)
            out[k] = dict(n=len(a), mean=float(a.mean()), median=float(np.median(a)),
                          std=float(a.std()), tstat=float(a.mean() / (a.std() / np.sqrt(len(a)) + 1e-9)))
        else:
            out[k] = dict(n=0)
    return out


def baseline(p: pd.DataFrame, horizons: list[int] = (1, 2, 5, 10), n_samples: int = 5000) -> dict:
    d = detrended_mid(p).values
    out = {}
    rng = np.random.default_rng(42)
    for k in horizons:
        valid = np.where(~np.isnan(d[:len(d) - k]) & ~np.isnan(d[k:]))[0]
        if len(valid) < 100:
            out[k] = dict(n=0)
            continue
        idxs = rng.choice(valid, size=min(n_samples, len(valid)), replace=False)
        diffs = d[idxs + k] - d[idxs]
        out[k] = dict(n=len(diffs), mean=float(diffs.mean()), median=float(np.median(diffs)),
                      std=float(diffs.std()), tstat=float(diffs.mean() / (diffs.std() / np.sqrt(len(diffs)) + 1e-9)))
    return out


def main() -> None:
    print("=" * 90)
    print("BOT-3 SIGNAL TEST — does aggressive quote predict next-tick detrended-mid move?")
    print("=" * 90)

    for product in ("OSM", "PEP"):
        print(f"\n### {product} ###")
        # Merge days into single table for pooled stats
        all_dfs = []
        all_events = {"agg_bid": [], "agg_ask": [], "pass_bid": [], "pass_ask": []}
        cum_offset = 0
        for day in (-1, 0, 1):
            p = load_day(day, product)
            ev = find_aggressive_events(p, product)
            # Shift indices for pooling
            for k, idxs in ev.items():
                all_events[k].extend([i + cum_offset for i in idxs])
            all_dfs.append(p)
            cum_offset += len(p)
        merged = pd.concat(all_dfs, ignore_index=True)
        # Detrend each day separately then concat — do this for clarity
        # (detrended_mid subtracts per-row fv, which is per-day correct)
        print(f"  total ticks: {len(merged)}")
        for name, idxs in all_events.items():
            print(f"  {name}: n={len(idxs)}  ({100*len(idxs)/len(merged):.2f}%)")

        # Per-day breakdown first
        print("  per-day event counts:")
        for day_i, df in zip((-1, 0, 1), all_dfs):
            ev = find_aggressive_events(df, product)
            print(f"    day {day_i}: agg_bid={len(ev['agg_bid'])}  agg_ask={len(ev['agg_ask'])}  "
                  f"pass_bid={len(ev['pass_bid'])}  pass_ask={len(ev['pass_ask'])}")

        # Forward markout — pooled
        print("\n  forward detrended-mid change (mean ± std, t-stat):")
        bl = baseline(merged)
        for name, idxs in all_events.items():
            fw = measure_forward(merged, idxs)
            print(f"  {name}:")
            for k in (1, 2, 5, 10):
                if fw[k]["n"] > 0:
                    b = bl[k]
                    print(f"    k={k:2d}: n={fw[k]['n']:5d} mean={fw[k]['mean']:+.3f} "
                          f"(bl={b['mean']:+.3f})  t={fw[k]['tstat']:+.2f}  (bl_t={b['tstat']:+.2f})")


if __name__ == "__main__":
    main()
