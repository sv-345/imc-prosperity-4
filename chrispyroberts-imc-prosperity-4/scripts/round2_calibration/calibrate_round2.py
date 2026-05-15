"""Round 2 calibration: fits fair-value, book-placement, and taker-flow parameters
for ASH_COATED_OSMIUM (OSM) and INTARIAN_PEPPER_ROOT (PEP) from 3 days of data.

Inputs : data/round2/prices_round_2_day_{-1,0,1}.csv  (L1/L2 book snapshots)
         data/round2/trades_round_2_day_{-1,0,1}.csv  (trade tape)
Output : docs/round2_params.json   (structured param block)
         docs/round2_calibration_summary.txt (human-readable report)

Methodology mirrors the Round-0 (tutorial) calibration inside rust_simulator/src/main.rs
and the Round-1 PHASE2 profile (ROUND_1/notes/PHASE2_DATA_PROFILE.md §2.1–2.9).
All numeric outputs flow directly from empirical CSV measurements; no literal
values are copied from prior rounds.

Run:
    python scripts/round2_calibration/calibrate_round2.py
"""

from __future__ import annotations

import json
import math
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "round2"
DOCS = ROOT / "docs"
DAYS = [-1, 0, 1]
PRODUCTS = ["ASH_COATED_OSMIUM", "INTARIAN_PEPPER_ROOT"]


def load_prices() -> pd.DataFrame:
    frames = []
    for d in DAYS:
        df = pd.read_csv(DATA / f"prices_round_2_day_{d}.csv", sep=";")
        df["day"] = d
        frames.append(df)
    out = pd.concat(frames, ignore_index=True)
    # Drop ticks where the entire book was empty (mid_price=0 is the sentinel).
    out = out[out["mid_price"] > 0].reset_index(drop=True)
    return out


def load_trades() -> pd.DataFrame:
    frames = []
    for d in DAYS:
        df = pd.read_csv(DATA / f"trades_round_2_day_{d}.csv", sep=";")
        df["day"] = d
        frames.append(df)
    return pd.concat(frames, ignore_index=True)


# ---------------------------------------------------------------------------
# Step 2 — fair-value process
# ---------------------------------------------------------------------------
def fit_osm_fv(prices: pd.DataFrame) -> dict:
    """OSM: stationary around a constant. Fit mean and per-tick diff sigma."""
    osm = prices[prices["product"] == "ASH_COATED_OSMIUM"].sort_values(["day", "timestamp"])
    mid = osm["mid_price"].to_numpy()
    diffs_within_day = []
    for d in DAYS:
        day_mid = osm[osm["day"] == d]["mid_price"].to_numpy()
        diffs_within_day.append(np.diff(day_mid))
    diffs = np.concatenate(diffs_within_day)
    mean_fv = float(np.mean(mid))
    sigma = float(np.std(diffs, ddof=1))
    acf1 = float(np.corrcoef(diffs[:-1], diffs[1:])[0, 1])
    # Per-day means to show stationarity
    per_day = {
        str(d): float(osm[osm["day"] == d]["mid_price"].mean()) for d in DAYS
    }
    return {
        "model": "constant",
        "fair_value": round(mean_fv),  # integer grid
        "per_day_mean": per_day,
        "tick_diff_sigma": sigma,
        "tick_diff_acf1": acf1,
        "n_ticks": int(len(mid)),
    }


def fit_pep_fv(prices: pd.DataFrame) -> dict:
    """PEP: deterministic linear drift per tick. Fit drift + residual sigma."""
    pep = prices[prices["product"] == "INTARIAN_PEPPER_ROOT"].sort_values(["day", "timestamp"])
    per_day_drift = {}
    residual_stds = []
    day_starts = {}
    for d in DAYS:
        sub = pep[pep["day"] == d]
        t = sub["timestamp"].to_numpy() / 100.0  # tick index 0..9999
        y = sub["mid_price"].to_numpy()
        # OLS slope
        slope, intercept = np.polyfit(t, y, 1)
        resid = y - (slope * t + intercept)
        per_day_drift[str(d)] = float(slope)
        residual_stds.append(float(np.std(resid, ddof=1)))
        day_starts[str(d)] = float(intercept)
    drift = float(np.mean(list(per_day_drift.values())))
    sigma = float(np.mean(residual_stds))
    return {
        "model": "linear_drift",
        "drift_per_tick": drift,
        "per_day_drift": per_day_drift,
        "per_day_start": day_starts,
        "residual_sigma": sigma,
        "n_ticks": int(len(pep)),
    }


# ---------------------------------------------------------------------------
# Step 3 — book placement bots
# ---------------------------------------------------------------------------
def fit_book_bots(prices: pd.DataFrame, product: str, fair_fn) -> dict:
    """Measure wall and inner offsets from fair, volumes, and bot-3 structure.

    fair_fn(row) returns the fair value at that tick.
    """
    df = prices[prices["product"] == product].copy()
    df["fair"] = df.apply(fair_fn, axis=1)

    # Collect all bid/ask levels (up to 3 per side) with offsets
    bid_offsets: list[int] = []
    bid_vols: list[int] = []
    ask_offsets: list[int] = []
    ask_vols: list[int] = []

    for _, row in df.iterrows():
        fv = row["fair"]
        for k in (1, 2, 3):
            bp, bv = row.get(f"bid_price_{k}"), row.get(f"bid_volume_{k}")
            if pd.notna(bp) and pd.notna(bv) and bv > 0:
                bid_offsets.append(int(bp - math.floor(fv)))
                bid_vols.append(int(bv))
            ap, av = row.get(f"ask_price_{k}"), row.get(f"ask_volume_{k}")
            if pd.notna(ap) and pd.notna(av) and av > 0:
                ask_offsets.append(int(ap - math.floor(fv)))
                ask_vols.append(int(av))

    bid_ct = Counter(bid_offsets)
    ask_ct = Counter(ask_offsets)

    def mode_band(ct: Counter, lo: int, hi: int) -> tuple[int, int]:
        """Return the most common offset in [lo, hi] and its count."""
        candidates = {k: v for k, v in ct.items() if lo <= k <= hi}
        if not candidates:
            return (0, 0)
        k = max(candidates, key=candidates.get)
        return (k, candidates[k])

    # Walls: furthest level from fair (typically offset ≤ -9 for bids, ≥ +9 for asks)
    bid_wall_off, bid_wall_ct = mode_band(bid_ct, -20, -9)
    ask_wall_off, ask_wall_ct = mode_band(ask_ct, 9, 20)
    # Inners: middle band (±5..±8)
    bid_inner_off, bid_inner_ct = mode_band(bid_ct, -8, -5)
    ask_inner_off, ask_inner_ct = mode_band(ask_ct, 5, 8)

    def vol_range(offsets: list[int], vols: list[int], target: int) -> dict:
        matched = [v for o, v in zip(offsets, vols) if o == target]
        if not matched:
            return {"min": 0, "max": 0, "mean": 0.0, "n": 0}
        return {
            "min": int(min(matched)),
            "max": int(max(matched)),
            "mean": float(np.mean(matched)),
            "n": len(matched),
        }

    # Bot-3: inside quotes at |offset| < |inner_offset|, by side.
    # Presence rate is computed per TICK (i.e. fraction of ticks with at least
    # one bot-3-shaped level present), not per level — multiple bot-3 levels
    # per tick are rare but do happen when e.g. a crossing quote and a passive
    # quote coexist.
    inner_abs = max(abs(bid_inner_off), abs(ask_inner_off), 5)

    bid_bot3_mask_per_tick: list[bool] = []
    ask_bot3_mask_per_tick: list[bool] = []
    bot3_bid_vols: list[int] = []
    bot3_ask_vols: list[int] = []

    for _, row in df.iterrows():
        fv = row["fair"]
        fl = math.floor(fv)
        has_bid_bot3 = False
        has_ask_bot3 = False
        for k in (1, 2, 3):
            bp, bv = row.get(f"bid_price_{k}"), row.get(f"bid_volume_{k}")
            if pd.notna(bp) and pd.notna(bv) and bv > 0:
                off = int(bp - fl)
                if abs(off) < inner_abs:
                    has_bid_bot3 = True
                    bot3_bid_vols.append(int(bv))
            ap, av = row.get(f"ask_price_{k}"), row.get(f"ask_volume_{k}")
            if pd.notna(ap) and pd.notna(av) and av > 0:
                off = int(ap - fl)
                if abs(off) < inner_abs:
                    has_ask_bot3 = True
                    bot3_ask_vols.append(int(av))
        bid_bot3_mask_per_tick.append(has_bid_bot3)
        ask_bot3_mask_per_tick.append(has_ask_bot3)

    bot3_bid_off = Counter({k: v for k, v in bid_ct.items() if abs(k) < inner_abs})
    bot3_ask_off = Counter({k: v for k, v in ask_ct.items() if abs(k) < inner_abs})
    n_ticks = len(df)
    bot3_bid_rate = sum(bid_bot3_mask_per_tick) / n_ticks if n_ticks else 0.0
    bot3_ask_rate = sum(ask_bot3_mask_per_tick) / n_ticks if n_ticks else 0.0
    bot3_vols = bot3_bid_vols + bot3_ask_vols
    bot3_vol_min = int(min(bot3_vols)) if bot3_vols else 0
    bot3_vol_max = int(max(bot3_vols)) if bot3_vols else 0
    bot3_vol_mean = float(np.mean(bot3_vols)) if bot3_vols else 0.0

    # Passive/aggressive split for bot-3
    # passive bid = negative offset, passive ask = positive offset
    passive_bids = sum(v for k, v in bot3_bid_off.items() if k < 0)
    aggressive_bids = sum(v for k, v in bot3_bid_off.items() if k > 0)
    passive_asks = sum(v for k, v in bot3_ask_off.items() if k > 0)
    aggressive_asks = sum(v for k, v in bot3_ask_off.items() if k < 0)
    total_passive = passive_bids + passive_asks
    total_aggr = aggressive_bids + aggressive_asks
    passive_frac = (
        total_passive / (total_passive + total_aggr)
        if (total_passive + total_aggr) > 0
        else 0.0
    )

    return {
        "n_ticks": int(n_ticks),
        "bid_wall_offset": bid_wall_off,
        "ask_wall_offset": ask_wall_off,
        "bid_inner_offset": bid_inner_off,
        "ask_inner_offset": ask_inner_off,
        "wall_vol_bid": vol_range(bid_offsets, bid_vols, bid_wall_off),
        "wall_vol_ask": vol_range(ask_offsets, ask_vols, ask_wall_off),
        "inner_vol_bid": vol_range(bid_offsets, bid_vols, bid_inner_off),
        "inner_vol_ask": vol_range(ask_offsets, ask_vols, ask_inner_off),
        "bot3_bid_rate": bot3_bid_rate,
        "bot3_ask_rate": bot3_ask_rate,
        "bot3_vol": {"min": bot3_vol_min, "max": bot3_vol_max, "mean": bot3_vol_mean},
        "bot3_passive_frac": passive_frac,
        "bot3_bid_offset_hist": dict(bot3_bid_off.most_common(10)),
        "bot3_ask_offset_hist": dict(bot3_ask_off.most_common(10)),
        "wall_presence": {
            "bid_count": bid_wall_ct,
            "ask_count": ask_wall_ct,
            "bid_presence_rate": bid_wall_ct / n_ticks if n_ticks else 0.0,
            "ask_presence_rate": ask_wall_ct / n_ticks if n_ticks else 0.0,
        },
        "inner_presence": {
            "bid_count": bid_inner_ct,
            "ask_count": ask_inner_ct,
            "bid_presence_rate": bid_inner_ct / n_ticks if n_ticks else 0.0,
            "ask_presence_rate": ask_inner_ct / n_ticks if n_ticks else 0.0,
        },
    }


# ---------------------------------------------------------------------------
# Step 4 — taker arrivals
# ---------------------------------------------------------------------------
def fit_taker(trades: pd.DataFrame, prices: pd.DataFrame, product: str) -> dict:
    t = trades[trades["symbol"] == product].copy()
    # Filter to bot-vs-bot trades (no SUBMISSION counterparty yet since this is market data)
    n_ticks_by_day = {
        d: int((prices["day"] == d).sum() / prices["product"].nunique())
        for d in DAYS
    }
    total_ticks = sum(n_ticks_by_day.values())
    # ticks with at least one trade per day
    trade_ticks = t.groupby(["day", "timestamp"]).size().rename("n").reset_index()
    active_ticks = len(trade_ticks)
    rate = active_ticks / total_ticks if total_ticks else 0.0

    multi = (trade_ticks["n"] > 1).sum()
    multi_frac = multi / active_ticks if active_ticks else 0.0

    qty = t["quantity"].to_numpy()
    qty_min = int(qty.min()) if len(qty) else 0
    qty_max = int(qty.max()) if len(qty) else 0
    qty_mean = float(qty.mean()) if len(qty) else 0.0

    # Side inference: if price closer to floor(fv) below → sell (bid hit); above → buy (ask hit)
    # We need fair at each trade tick.
    price_lookup = (
        prices[prices["product"] == product]
        .set_index(["day", "timestamp"])[["mid_price"]]
        .to_dict(orient="index")
    )
    buys = sells = 0
    for _, row in t.iterrows():
        key = (row["day"], row["timestamp"])
        mid = price_lookup.get(key, {}).get("mid_price")
        if mid is None:
            continue
        if row["price"] > mid:
            buys += 1
        elif row["price"] < mid:
            sells += 1
    side_buy_frac = buys / (buys + sells) if (buys + sells) else 0.5

    # Level inference: compare trade price to wall/inner of the tick
    # Inner-level if |price - floor(fv)| matches inner offset; wall-level if matches wall.
    return {
        "n_trades": int(len(t)),
        "n_ticks": int(total_ticks),
        "taker_rate_per_tick": rate,
        "multi_trade_tick_frac": multi_frac,
        "qty_support": [qty_min, qty_max],
        "qty_mean": qty_mean,
        "side_buy_frac": side_buy_frac,
    }


def taker_level_split(trades: pd.DataFrame, prices: pd.DataFrame, product: str,
                      wall_off: int, inner_off: int) -> dict:
    """Classify each trade as hitting wall / inner / bot3 based on price vs floor(fv)."""
    t = trades[trades["symbol"] == product].copy()
    price_df = prices[prices["product"] == product][["day", "timestamp", "mid_price"]]
    merged = t.merge(price_df, on=["day", "timestamp"], how="left").dropna(subset=["mid_price"])
    merged["floor_fv"] = np.floor(merged["mid_price"])
    merged["offset"] = merged["price"] - merged["floor_fv"]

    # Offset > 0 means trade on the ask side; < 0 means bid side
    wall_hits = inner_hits = bot3_hits = other = 0
    for off in merged["offset"]:
        # Wall match
        if abs(off - abs(wall_off)) < 0.6 or abs(off + abs(wall_off)) < 0.6:
            wall_hits += 1
        elif abs(off - abs(inner_off)) < 0.6 or abs(off + abs(inner_off)) < 0.6:
            inner_hits += 1
        elif abs(off) < abs(inner_off):
            bot3_hits += 1
        else:
            other += 1
    total = wall_hits + inner_hits + bot3_hits + other
    if total == 0:
        return {"inner": 0.0, "wall": 0.0, "bot3_price": 0.0, "other": 0.0}
    return {
        "inner": inner_hits / total,
        "wall": wall_hits / total,
        "bot3_price": bot3_hits / total,
        "other": other / total,
        "n": total,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    prices = load_prices()
    trades = load_trades()

    # --- Step 2 ---
    osm_fv = fit_osm_fv(prices)
    pep_fv = fit_pep_fv(prices)

    # --- Step 3 ---
    def osm_fair(row):
        return osm_fv["fair_value"]

    def pep_fair(row):
        # per-tick fair: day_start + drift_per_tick * tick_index
        tick_idx = row["timestamp"] / 100.0
        return pep_fv["per_day_start"][str(int(row["day"]))] + pep_fv["drift_per_tick"] * tick_idx

    osm_book = fit_book_bots(prices, "ASH_COATED_OSMIUM", osm_fair)
    pep_book = fit_book_bots(prices, "INTARIAN_PEPPER_ROOT", pep_fair)

    # --- Step 4 ---
    osm_taker = fit_taker(trades, prices, "ASH_COATED_OSMIUM")
    pep_taker = fit_taker(trades, prices, "INTARIAN_PEPPER_ROOT")
    osm_taker["level_split"] = taker_level_split(
        trades, prices, "ASH_COATED_OSMIUM",
        osm_book["ask_wall_offset"], osm_book["ask_inner_offset"],
    )
    pep_taker["level_split"] = taker_level_split(
        trades, prices, "INTARIAN_PEPPER_ROOT",
        pep_book["ask_wall_offset"], pep_book["ask_inner_offset"],
    )

    params = {
        "round": 2,
        "products": PRODUCTS,
        "days": DAYS,
        "OSM": {"fv": osm_fv, "book": osm_book, "taker": osm_taker},
        "PEP": {"fv": pep_fv, "book": pep_book, "taker": pep_taker},
    }

    DOCS.mkdir(parents=True, exist_ok=True)
    (DOCS / "round2_params.json").write_text(json.dumps(params, indent=2))

    # Human summary
    lines = ["# Round 2 Calibration Summary\n"]
    lines.append("## OSM (ASH_COATED_OSMIUM)\n")
    lines.append(f"FV model: constant = {osm_fv['fair_value']}  (per-day: {osm_fv['per_day_mean']})")
    lines.append(f"Tick-diff sigma: {osm_fv['tick_diff_sigma']:.4f}  ACF1: {osm_fv['tick_diff_acf1']:.4f}")
    lines.append(f"Walls: bid@{osm_book['bid_wall_offset']}, ask@+{osm_book['ask_wall_offset']}  "
                 f"(spread={osm_book['ask_wall_offset']-osm_book['bid_wall_offset']})")
    lines.append(f"Wall vol bid: {osm_book['wall_vol_bid']}")
    lines.append(f"Inners: bid@{osm_book['bid_inner_offset']}, ask@+{osm_book['ask_inner_offset']}")
    lines.append(f"Inner vol bid: {osm_book['inner_vol_bid']}")
    lines.append(f"Bot-3 rate: bid={osm_book['bot3_bid_rate']:.4f}  ask={osm_book['bot3_ask_rate']:.4f}  "
                 f"passive_frac={osm_book['bot3_passive_frac']:.3f}")
    lines.append(f"Taker: rate={osm_taker['taker_rate_per_tick']:.4f}  "
                 f"qty={osm_taker['qty_support']}  side_buy={osm_taker['side_buy_frac']:.3f}")
    lines.append(f"Taker level split: {osm_taker['level_split']}")
    lines.append("")
    lines.append("## PEP (INTARIAN_PEPPER_ROOT)\n")
    lines.append(f"FV model: linear drift  drift/tick={pep_fv['drift_per_tick']:.4f}  "
                 f"resid_sigma={pep_fv['residual_sigma']:.4f}")
    lines.append(f"Per-day start: {pep_fv['per_day_start']}")
    lines.append(f"Per-day drift: {pep_fv['per_day_drift']}")
    lines.append(f"Walls: bid@{pep_book['bid_wall_offset']}, ask@+{pep_book['ask_wall_offset']}  "
                 f"(spread={pep_book['ask_wall_offset']-pep_book['bid_wall_offset']})")
    lines.append(f"Wall vol bid: {pep_book['wall_vol_bid']}")
    lines.append(f"Inners: bid@{pep_book['bid_inner_offset']}, ask@+{pep_book['ask_inner_offset']}")
    lines.append(f"Inner vol bid: {pep_book['inner_vol_bid']}")
    lines.append(f"Bot-3 rate: bid={pep_book['bot3_bid_rate']:.4f}  ask={pep_book['bot3_ask_rate']:.4f}  "
                 f"passive_frac={pep_book['bot3_passive_frac']:.3f}")
    lines.append(f"Taker: rate={pep_taker['taker_rate_per_tick']:.4f}  "
                 f"qty={pep_taker['qty_support']}  side_buy={pep_taker['side_buy_frac']:.3f}")
    lines.append(f"Taker level split: {pep_taker['level_split']}")

    summary = "\n".join(lines)
    (DOCS / "round2_calibration_summary.txt").write_text(summary)
    print(summary)


if __name__ == "__main__":
    main()
