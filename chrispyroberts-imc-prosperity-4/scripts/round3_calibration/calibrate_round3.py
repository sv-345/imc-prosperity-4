"""Round 3 calibration: fits fair-value, book-placement, taker-flow, and
voucher-implied-vol parameters for the R3 product set from 3 days of data.

Inputs : data/round3/prices_round_3_day_{0,1,2}.csv  (L1/L2 book snapshots)
         data/round3/trades_round_3_day_{0,1,2}.csv  (trade tape)
Output : docs/round3_params.json   (structured param block)
         docs/round3_calibration_summary.txt (human-readable report)

R3 adds:
- Two new delta-1 products (HYDROGEL_PACK, VELVETFRUIT_EXTRACT).
- 10 European call vouchers on VELVETFRUIT_EXTRACT (VEV_{4000,4500,5000,
  5100,5200,5300,5400,5500,6000,6500}).
- Per-strike implied vol, fit jointly across days under day-specific TTEs.

Methodology mirrors calibrate_round2.py. All numeric outputs flow directly
from empirical CSV measurements; no literal values are copied from prior
rounds.

Day-TTE mapping (per IMC wiki, confirmed):
- CSV day 0 = tutorial-round day, TTE = 8 days at start
- CSV day 1 = R1 day, TTE = 7 days at start
- CSV day 2 = R2 day, TTE = 6 days at start
- R3 live simulation starts at TTE = 5 days.

Run:
    python scripts/round3_calibration/calibrate_round3.py
"""

from __future__ import annotations

import json
import math
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "round3"
DOCS = ROOT / "docs"
DAYS = [0, 1, 2]

DELTA1_PRODUCTS = ["HYDROGEL_PACK", "VELVETFRUIT_EXTRACT"]
VEV_STRIKES = [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]
VEV_PRODUCTS = [f"VEV_{k}" for k in VEV_STRIKES]
ALL_PRODUCTS = DELTA1_PRODUCTS + VEV_PRODUCTS

# Strikes with real option dynamics (non-pinned, non-deep-ITM-degenerate).
# 4000, 4500 are deep ITM with essentially no time value -> IV ill-conditioned.
# 6000, 6500 are pinned at bid=0/ask=1 across all 3 days (zero variance).
ACTIVE_STRIKES = [5000, 5100, 5200, 5300, 5400, 5500]
PINNED_STRIKES = [6000, 6500]

# Day -> TTE in years (IMC wiki mapping).
DAY_TO_TTE = {0: 8.0 / 365.0, 1: 7.0 / 365.0, 2: 6.0 / 365.0}
LIVE_TTE_YEARS = 5.0 / 365.0


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------
def load_prices() -> pd.DataFrame:
    frames = []
    for d in DAYS:
        df = pd.read_csv(DATA / f"prices_round_3_day_{d}.csv", sep=";")
        df["day"] = d
        frames.append(df)
    out = pd.concat(frames, ignore_index=True)
    out = out[(out["mid_price"] > 0) & out["bid_price_1"].notna() & out["ask_price_1"].notna()]
    return out.reset_index(drop=True)


def load_trades() -> pd.DataFrame:
    frames = []
    for d in DAYS:
        df = pd.read_csv(DATA / f"trades_round_3_day_{d}.csv", sep=";")
        df["day"] = d
        frames.append(df)
    return pd.concat(frames, ignore_index=True)


# ---------------------------------------------------------------------------
# Step 1 - Black-Scholes primitives (pure python, no scipy)
# ---------------------------------------------------------------------------
def norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def bs_call(S: float, K: float, T: float, sigma: float) -> float:
    if T <= 0 or sigma <= 0:
        return max(S - K, 0.0)
    d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return S * norm_cdf(d1) - K * norm_cdf(d2)


def implied_vol(C: float, S: float, K: float, T: float, tol: float = 1e-7, max_iter: int = 200) -> float:
    intrinsic = max(S - K, 0.0)
    if C < intrinsic - 1e-9:
        return float("nan")
    lo, hi = 1e-6, 5.0
    for _ in range(max_iter):
        mid = 0.5 * (lo + hi)
        if bs_call(S, K, T, mid) > C:
            hi = mid
        else:
            lo = mid
        if hi - lo < tol:
            break
    return 0.5 * (lo + hi)


# ---------------------------------------------------------------------------
# Step 2 - fair-value process (delta-1 products)
# ---------------------------------------------------------------------------
def fit_delta1_fv(prices: pd.DataFrame, product: str) -> dict:
    """Stationary around a constant mean; reports per-day mean + first-diff
    sigma and autocorrelation (all three needed for sim AR(1)/mean-reversion)."""
    sub = prices[prices["product"] == product].sort_values(["day", "timestamp"])
    mid_all = sub["mid_price"].to_numpy()
    diffs_by_day = []
    per_day_mean = {}
    for d in DAYS:
        day_sub = sub[sub["day"] == d]
        mid = day_sub["mid_price"].to_numpy()
        diffs_by_day.append(np.diff(mid))
        per_day_mean[str(d)] = float(np.mean(mid))
    diffs = np.concatenate(diffs_by_day)
    sigma = float(np.std(diffs, ddof=1))
    acf1 = float(np.corrcoef(diffs[:-1], diffs[1:])[0, 1]) if len(diffs) > 2 else 0.0
    mean_fv = float(np.mean(mid_all))
    return {
        "model": "mean_reverting",  # AR(1) on first differences
        "fair_value": round(mean_fv),
        "per_day_mean": per_day_mean,
        "tick_diff_sigma": sigma,
        "tick_diff_acf1": acf1,
        "n_ticks": int(len(mid_all)),
    }


# ---------------------------------------------------------------------------
# Step 3 - voucher implied vol (per-strike, joint across days)
# ---------------------------------------------------------------------------
def fit_voucher_iv(prices: pd.DataFrame) -> dict:
    """For each active strike, fit a single sigma that best matches observed
    mean option mid across days (each day uses its own TTE).
    """
    vext = (
        prices[prices["product"] == "VELVETFRUIT_EXTRACT"][["day", "timestamp", "mid_price"]]
        .rename(columns={"mid_price": "underlying"})
    )
    out = {
        "model": "single_sigma_per_strike",
        "day_to_tte_years": {str(k): v for k, v in DAY_TO_TTE.items()},
        "live_tte_years": LIVE_TTE_YEARS,
        "by_strike": {},
    }

    # Active strikes
    for K in ACTIVE_STRIKES:
        sub = prices[prices["product"] == f"VEV_{K}"]
        merged = sub.merge(vext, on=["day", "timestamp"], how="inner")
        per_day_iv = {}
        for d in DAYS:
            day = merged[merged["day"] == d]
            if len(day) == 0:
                continue
            S = float(day["underlying"].mean())
            C = float(day["mid_price"].mean())
            T = DAY_TO_TTE[d]
            iv = implied_vol(C, S, K, T)
            per_day_iv[str(d)] = iv
        ivs = list(per_day_iv.values())
        mean_iv = float(np.mean(ivs))
        std_iv = float(np.std(ivs, ddof=1)) if len(ivs) > 1 else 0.0
        # Per-tick IV residual sigma: proxy for how much the bot's sigma
        # wobbles around the mean within a day.
        per_tick_resid = []
        for d in DAYS:
            day = merged[merged["day"] == d]
            T = DAY_TO_TTE[d]
            for _, row in day.sample(n=min(500, len(day)), random_state=0).iterrows():
                S_t = float(row["underlying"])
                C_t = float(row["mid_price"])
                iv = implied_vol(C_t, S_t, K, T)
                if not math.isnan(iv):
                    per_tick_resid.append(iv - mean_iv)
        resid_sigma = float(np.std(per_tick_resid, ddof=1)) if len(per_tick_resid) > 1 else 0.0
        out["by_strike"][str(K)] = {
            "iv_mean": mean_iv,
            "iv_per_day": per_day_iv,
            "iv_std_across_days": std_iv,
            "tick_iv_resid_sigma": resid_sigma,
            "n_ticks": int(len(merged)),
            "spec": "active",
        }
    # Pinned strikes
    for K in PINNED_STRIKES:
        sub = prices[prices["product"] == f"VEV_{K}"]
        merged = sub.merge(vext, on=["day", "timestamp"], how="inner")
        bid_unique = set(int(b) for b in sub["bid_price_1"].dropna())
        ask_unique = set(int(a) for a in sub["ask_price_1"].dropna())
        bid_vol_mean = float(sub["bid_volume_1"].mean())
        ask_vol_mean = float(sub["ask_volume_1"].mean())
        out["by_strike"][str(K)] = {
            "spec": "pinned",
            "bid_price_observed": sorted(bid_unique),
            "ask_price_observed": sorted(ask_unique),
            "bid_volume_mean": bid_vol_mean,
            "ask_volume_mean": ask_vol_mean,
            "n_ticks": int(len(sub)),
        }
    return out


# ---------------------------------------------------------------------------
# Step 4 - book placement bots (all active products, including vouchers)
# ---------------------------------------------------------------------------
def fit_book_bots(prices: pd.DataFrame, product: str, fair_fn) -> dict:
    """Mirror the R2 fit_book_bots: measures wall and inner offsets from the
    tick fair, volumes per offset, and bot-3 structure. fair_fn(row) returns
    the float fair for that row; offsets are measured vs floor(fair).
    """
    df = prices[prices["product"] == product].copy()
    df["fair"] = df.apply(fair_fn, axis=1)

    bid_offsets: list[int] = []
    bid_vols: list[int] = []
    ask_offsets: list[int] = []
    ask_vols: list[int] = []
    for _, row in df.iterrows():
        fv = row["fair"]
        if pd.isna(fv):
            continue
        fl = math.floor(fv)
        for k in (1, 2, 3):
            bp, bv = row.get(f"bid_price_{k}"), row.get(f"bid_volume_{k}")
            if pd.notna(bp) and pd.notna(bv) and bv > 0:
                bid_offsets.append(int(bp - fl))
                bid_vols.append(int(bv))
            ap, av = row.get(f"ask_price_{k}"), row.get(f"ask_volume_{k}")
            if pd.notna(ap) and pd.notna(av) and av > 0:
                ask_offsets.append(int(ap - fl))
                ask_vols.append(int(av))

    bid_ct = Counter(bid_offsets)
    ask_ct = Counter(ask_offsets)

    def extract_wall_inner(ct: Counter, side_sign: int) -> tuple[int, int, int, int, bool]:
        """Given a per-offset count dict on one side (all positive or all
        negative offsets expected), return:
            (outer_off, outer_ct, inner_off, inner_ct, half_tie_split)

        Strategy:
        1. Collect all offsets with |offset| >= 1 on the correct side.
        2. Merge adjacent pairs (k, k+1) that are likely a half-tie split of
           the same logical wall: if counts[k] + counts[k+1] beats the
           single-offset top mode. Report the *further-from-zero* as the
           representative offset.
        3. After merging, the top-2 modes are inner (closer to 0) and outer.
        4. If the 2nd mode has fewer than 20% of the top mode, treat as
           single-level (inner = outer).
        """
        items = [(o, c) for o, c in ct.items() if o * side_sign > 0]
        if not items:
            return (0, 0, 0, 0, False)
        # Build merged counts: the logical wall offset W may appear as two
        # integer offsets because mid can be half-integer and floor()
        # rounding lands the same wall at W or W+1 (for asks) / W or W-1 (for
        # bids). Merge such pairs.
        merged: dict[int, tuple[int, bool]] = {}  # off -> (count, was_split)
        sorted_offsets = sorted([o for o, _ in items], key=lambda x: x * side_sign)  # ascending magnitude
        seen: set[int] = set()
        for o in sorted_offsets:
            if o in seen:
                continue
            neighbor = o + side_sign  # the further-from-zero neighbor
            c_o = ct[o]
            c_n = ct.get(neighbor, 0)
            # Merge if neighbor exists and combined count exceeds either
            # single-offset count by a meaningful margin.
            if c_n > 0 and (c_o + c_n) > max(c_o, c_n) * 1.3:
                # Representative offset = the one further from zero.
                rep = neighbor if abs(neighbor) > abs(o) else o
                merged[rep] = (c_o + c_n, True)
                seen.add(o)
                seen.add(neighbor)
            else:
                merged[o] = (c_o, False)
                seen.add(o)

        # Rank by count desc
        ranked = sorted(merged.items(), key=lambda kv: -kv[1][0])
        top_off, (top_ct, top_split) = ranked[0]
        if len(ranked) < 2:
            return (top_off, top_ct, top_off, top_ct, top_split)
        second_off, (second_ct, second_split) = ranked[1]
        # If secondary weak, treat as single-level
        if second_ct < top_ct * 0.20:
            return (top_off, top_ct, top_off, top_ct, top_split)
        # Inner = closer to zero; Outer = further from zero
        if abs(top_off) > abs(second_off):
            outer_off, outer_ct, outer_split = top_off, top_ct, top_split
            inner_off, inner_ct = second_off, second_ct
        else:
            outer_off, outer_ct, outer_split = second_off, second_ct, second_split
            inner_off, inner_ct = top_off, top_ct
        return (outer_off, outer_ct, inner_off, inner_ct, outer_split)

    bid_wall_off, bid_wall_ct, bid_inner_off, bid_inner_ct, bid_wall_half_tie = extract_wall_inner(bid_ct, -1)
    ask_wall_off, ask_wall_ct, ask_inner_off, ask_inner_ct, ask_wall_half_tie = extract_wall_inner(ask_ct, +1)

    def vol_range(offsets, vols, target: int) -> dict:
        matched = [v for o, v in zip(offsets, vols) if o == target]
        if not matched:
            return {"min": 0, "max": 0, "mean": 0.0, "n": 0}
        return {
            "min": int(min(matched)),
            "max": int(max(matched)),
            "mean": float(np.mean(matched)),
            "n": len(matched),
        }

    # Bot-3: inside quotes at |offset| < |inner_offset|, per-tick presence rate.
    inner_abs = max(abs(bid_inner_off), abs(ask_inner_off), 1)
    bid_bot3_mask = []
    ask_bot3_mask = []
    bot3_bid_vols: list[int] = []
    bot3_ask_vols: list[int] = []
    for _, row in df.iterrows():
        fv = row["fair"]
        if pd.isna(fv):
            bid_bot3_mask.append(False)
            ask_bot3_mask.append(False)
            continue
        fl = math.floor(fv)
        has_bid = False
        has_ask = False
        for k in (1, 2, 3):
            bp, bv = row.get(f"bid_price_{k}"), row.get(f"bid_volume_{k}")
            if pd.notna(bp) and pd.notna(bv) and bv > 0:
                off = int(bp - fl)
                if abs(off) < inner_abs:
                    has_bid = True
                    bot3_bid_vols.append(int(bv))
            ap, av = row.get(f"ask_price_{k}"), row.get(f"ask_volume_{k}")
            if pd.notna(ap) and pd.notna(av) and av > 0:
                off = int(ap - fl)
                if abs(off) < inner_abs:
                    has_ask = True
                    bot3_ask_vols.append(int(av))
        bid_bot3_mask.append(has_bid)
        ask_bot3_mask.append(has_ask)

    n_ticks = len(df)
    bot3_bid_rate = float(sum(bid_bot3_mask) / n_ticks) if n_ticks else 0.0
    bot3_ask_rate = float(sum(ask_bot3_mask) / n_ticks) if n_ticks else 0.0
    bot3_vols = bot3_bid_vols + bot3_ask_vols
    bot3_vol = {
        "min": int(min(bot3_vols)) if bot3_vols else 0,
        "max": int(max(bot3_vols)) if bot3_vols else 0,
        "mean": float(np.mean(bot3_vols)) if bot3_vols else 0.0,
    }
    bot3_bid_off = Counter({k: v for k, v in bid_ct.items() if abs(k) < inner_abs})
    bot3_ask_off = Counter({k: v for k, v in ask_ct.items() if abs(k) < inner_abs})
    passive_bids = sum(v for k, v in bot3_bid_off.items() if k < 0)
    aggressive_bids = sum(v for k, v in bot3_bid_off.items() if k > 0)
    passive_asks = sum(v for k, v in bot3_ask_off.items() if k > 0)
    aggressive_asks = sum(v for k, v in bot3_ask_off.items() if k < 0)
    total_p = passive_bids + passive_asks
    total_a = aggressive_bids + aggressive_asks
    passive_frac = total_p / (total_p + total_a) if (total_p + total_a) > 0 else 0.0

    # For half-tie-split walls, vol_range at the representative offset only
    # sees half the mass. Report the merged count by also looking at the
    # adjacent offset (one step toward zero).
    def vol_range_wall(offsets, vols, wall_off: int, half_tie: bool) -> dict:
        matched = [v for o, v in zip(offsets, vols) if o == wall_off]
        if half_tie:
            neighbor = wall_off + (1 if wall_off < 0 else -1)
            matched.extend(v for o, v in zip(offsets, vols) if o == neighbor)
        if not matched:
            return {"min": 0, "max": 0, "mean": 0.0, "n": 0}
        return {
            "min": int(min(matched)),
            "max": int(max(matched)),
            "mean": float(np.mean(matched)),
            "n": len(matched),
        }

    return {
        "n_ticks": int(n_ticks),
        "bid_wall_offset": bid_wall_off,
        "ask_wall_offset": ask_wall_off,
        "bid_inner_offset": bid_inner_off,
        "ask_inner_offset": ask_inner_off,
        "bid_wall_half_tie_split": bid_wall_half_tie,
        "ask_wall_half_tie_split": ask_wall_half_tie,
        "wall_vol_bid": vol_range_wall(bid_offsets, bid_vols, bid_wall_off, bid_wall_half_tie),
        "wall_vol_ask": vol_range_wall(ask_offsets, ask_vols, ask_wall_off, ask_wall_half_tie),
        "inner_vol_bid": vol_range(bid_offsets, bid_vols, bid_inner_off),
        "inner_vol_ask": vol_range(ask_offsets, ask_vols, ask_inner_off),
        "bot3_bid_rate": bot3_bid_rate,
        "bot3_ask_rate": bot3_ask_rate,
        "bot3_vol": bot3_vol,
        "bot3_passive_frac": passive_frac,
        "bot3_bid_offset_hist": dict(bot3_bid_off.most_common(10)),
        "bot3_ask_offset_hist": dict(bot3_ask_off.most_common(10)),
        "wall_presence": {
            "bid_count": int(bid_wall_ct),
            "ask_count": int(ask_wall_ct),
            "bid_presence_rate": bid_wall_ct / n_ticks if n_ticks else 0.0,
            "ask_presence_rate": ask_wall_ct / n_ticks if n_ticks else 0.0,
        },
        "inner_presence": {
            "bid_count": int(bid_inner_ct),
            "ask_count": int(ask_inner_ct),
            "bid_presence_rate": bid_inner_ct / n_ticks if n_ticks else 0.0,
            "ask_presence_rate": ask_inner_ct / n_ticks if n_ticks else 0.0,
        },
    }


# ---------------------------------------------------------------------------
# Step 5 - taker flow (per product)
# ---------------------------------------------------------------------------
def fit_taker(trades: pd.DataFrame, prices: pd.DataFrame, product: str) -> dict:
    t = trades[trades["symbol"] == product].copy()
    n_ticks_by_day = {}
    for d in DAYS:
        day = prices[(prices["day"] == d) & (prices["product"] == product)]
        n_ticks_by_day[d] = int(day["timestamp"].nunique())
    total_ticks = sum(n_ticks_by_day.values())
    if total_ticks == 0:
        return {
            "n_trades": 0,
            "n_ticks": 0,
            "taker_rate_per_tick": 0.0,
            "multi_trade_tick_frac": 0.0,
            "qty_support": [0, 0],
            "qty_hist": {},
            "qty_mean": 0.0,
            "side_buy_frac": 0.5,
        }
    trade_ticks = t.groupby(["day", "timestamp"]).size().rename("n").reset_index()
    active_ticks = len(trade_ticks)
    rate = active_ticks / total_ticks
    multi = int((trade_ticks["n"] > 1).sum())
    multi_frac = multi / active_ticks if active_ticks else 0.0

    qty = t["quantity"].to_numpy()
    qty_min = int(qty.min()) if len(qty) else 0
    qty_max = int(qty.max()) if len(qty) else 0
    qty_mean = float(qty.mean()) if len(qty) else 0.0
    qty_hist = dict(Counter(qty.tolist()).most_common())

    # Aggressor: price > mid_at_tick => BUY, < => SELL
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

    return {
        "n_trades": int(len(t)),
        "n_ticks": int(total_ticks),
        "taker_rate_per_tick": rate,
        "multi_trade_tick_frac": multi_frac,
        "qty_support": [qty_min, qty_max],
        "qty_hist": {int(k): int(v) for k, v in qty_hist.items()},
        "qty_mean": qty_mean,
        "side_buy_frac": side_buy_frac,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    prices = load_prices()
    trades = load_trades()
    print(f"loaded {len(prices):,} price rows, {len(trades):,} trade rows")

    # --- FV for delta-1 products
    hydrogel_fv = fit_delta1_fv(prices, "HYDROGEL_PACK")
    velvet_fv = fit_delta1_fv(prices, "VELVETFRUIT_EXTRACT")
    print(f"HYDROGEL FV: mean={hydrogel_fv['fair_value']}, sigma={hydrogel_fv['tick_diff_sigma']:.3f}, acf1={hydrogel_fv['tick_diff_acf1']:.3f}")
    print(f"VELVET FV:   mean={velvet_fv['fair_value']}, sigma={velvet_fv['tick_diff_sigma']:.3f}, acf1={velvet_fv['tick_diff_acf1']:.3f}")

    # --- Per-strike IV
    print("Fitting voucher IVs...")
    voucher_params = fit_voucher_iv(prices)
    for K in ACTIVE_STRIKES:
        v = voucher_params["by_strike"][str(K)]
        print(f"  VEV_{K}: IV mean={v['iv_mean']:.4f}, std_across_days={v['iv_std_across_days']:.5f}, n={v['n_ticks']}")

    # --- Book bots (delta-1)
    # HYDROGEL and VELVETFRUIT are mean-reverting, NOT constant — within-day
    # mid wanders (std ~30 for HYDROGEL, ~15 for VELVETFRUIT). If we anchored
    # offsets to the global per-day mean we'd get spurious wide distributions.
    # Use the observed mid as per-tick fair. Small bias from bot3 presence is
    # absorbed by the mode-of-offset measurement.
    def hydrogel_fair(row):
        return float(row["mid_price"])

    def velvet_fair(row):
        return float(row["mid_price"])

    hydrogel_book = fit_book_bots(prices, "HYDROGEL_PACK", hydrogel_fair)
    velvet_book = fit_book_bots(prices, "VELVETFRUIT_EXTRACT", velvet_fair)
    print(f"HYDROGEL book: walls {hydrogel_book['bid_wall_offset']}/+{hydrogel_book['ask_wall_offset']}, inners {hydrogel_book['bid_inner_offset']}/+{hydrogel_book['ask_inner_offset']}")
    print(f"VELVET book:   walls {velvet_book['bid_wall_offset']}/+{velvet_book['ask_wall_offset']}, inners {velvet_book['bid_inner_offset']}/+{velvet_book['ask_inner_offset']}")

    # --- Book bots (active vouchers). Fair via BSM(S_tick, K, T_day, strike_IV).
    # Cache VELVETFRUIT mid per (day, timestamp) for voucher fair lookup.
    vext = (
        prices[prices["product"] == "VELVETFRUIT_EXTRACT"]
        .set_index(["day", "timestamp"])["mid_price"]
        .to_dict()
    )

    def make_vev_fair_fn(K: int, iv: float):
        def fair(row):
            S = vext.get((int(row["day"]), int(row["timestamp"])))
            if S is None:
                return float("nan")
            T = DAY_TO_TTE[int(row["day"])]
            return bs_call(S, K, T, iv)
        return fair

    vev_books: dict = {}
    for K in ACTIVE_STRIKES:
        iv = voucher_params["by_strike"][str(K)]["iv_mean"]
        vev_books[K] = fit_book_bots(prices, f"VEV_{K}", make_vev_fair_fn(K, iv))
        b = vev_books[K]
        print(f"  VEV_{K}: walls {b['bid_wall_offset']}/+{b['ask_wall_offset']}, inners {b['bid_inner_offset']}/+{b['ask_inner_offset']}")

    # --- Takers (all products, including vouchers)
    takers: dict = {}
    for product in ALL_PRODUCTS:
        takers[product] = fit_taker(trades, prices, product)

    # --- Assemble JSON
    params = {
        "round": 3,
        "products": ALL_PRODUCTS,
        "days": DAYS,
        "day_to_tte_years": {str(k): v for k, v in DAY_TO_TTE.items()},
        "live_tte_years": LIVE_TTE_YEARS,
        "HYDROGEL": {
            "fv": hydrogel_fv,
            "book": hydrogel_book,
            "taker": takers["HYDROGEL_PACK"],
            "position_limit": 200,
        },
        "VELVET": {
            "fv": velvet_fv,
            "book": velvet_book,
            "taker": takers["VELVETFRUIT_EXTRACT"],
            "position_limit": 200,
        },
        "VEV": {
            "strikes": VEV_STRIKES,
            "active_strikes": ACTIVE_STRIKES,
            "pinned_strikes": PINNED_STRIKES,
            "iv_by_strike": voucher_params,
            "book_by_strike": {str(K): vev_books[K] for K in ACTIVE_STRIKES},
            "taker_by_strike": {str(K): takers[f"VEV_{K}"] for K in VEV_STRIKES},
            "position_limit": 300,
        },
    }

    DOCS.mkdir(parents=True, exist_ok=True)
    out_json = DOCS / "round3_params.json"
    out_json.write_text(json.dumps(params, indent=2))
    print(f"\nwrote {out_json}")

    # --- Summary
    lines = ["# Round 3 Calibration Summary\n"]
    lines.append(f"Day-TTE mapping: {DAY_TO_TTE}")
    lines.append(f"Live TTE at R3 start: {LIVE_TTE_YEARS:.5f} yr (= 5 days)\n")

    def describe_delta1(name: str, fv: dict, book: dict, taker: dict):
        lines.append(f"## {name}\n")
        lines.append(f"FV model: mean-reverting around {fv['fair_value']}")
        lines.append(f"  per-day mean: {fv['per_day_mean']}")
        lines.append(f"  tick-diff sigma: {fv['tick_diff_sigma']:.4f}  ACF1(Δmid): {fv['tick_diff_acf1']:.4f}")
        lines.append(f"Walls: bid@{book['bid_wall_offset']}, ask@+{book['ask_wall_offset']}  spread={book['ask_wall_offset']-book['bid_wall_offset']}")
        lines.append(f"  wall vol bid: {book['wall_vol_bid']}")
        lines.append(f"  wall vol ask: {book['wall_vol_ask']}")
        lines.append(f"Inners: bid@{book['bid_inner_offset']}, ask@+{book['ask_inner_offset']}")
        lines.append(f"  inner vol bid: {book['inner_vol_bid']}")
        lines.append(f"  inner vol ask: {book['inner_vol_ask']}")
        lines.append(f"Bot-3: bid_rate={book['bot3_bid_rate']:.4f}  ask_rate={book['bot3_ask_rate']:.4f}  passive_frac={book['bot3_passive_frac']:.3f}")
        lines.append(f"  bid offset hist: {book['bot3_bid_offset_hist']}")
        lines.append(f"  ask offset hist: {book['bot3_ask_offset_hist']}")
        lines.append(f"Taker: rate={taker['taker_rate_per_tick']:.4f}  qty={taker['qty_support']}  mean_qty={taker['qty_mean']:.2f}  side_buy={taker['side_buy_frac']:.3f}")
        lines.append(f"  qty histogram (top 10): {dict(list(taker['qty_hist'].items())[:10])}\n")

    describe_delta1("HYDROGEL_PACK", hydrogel_fv, hydrogel_book, takers["HYDROGEL_PACK"])
    describe_delta1("VELVETFRUIT_EXTRACT", velvet_fv, velvet_book, takers["VELVETFRUIT_EXTRACT"])

    lines.append("## VEV (call vouchers on VELVETFRUIT_EXTRACT)\n")
    lines.append(f"Strikes: {VEV_STRIKES}")
    lines.append(f"Active (fit): {ACTIVE_STRIKES}")
    lines.append(f"Pinned (min-tick): {PINNED_STRIKES}\n")
    lines.append("### Per-strike IV (days averaged with correct per-day TTE)")
    lines.append(f"{'Strike':>6} {'IV_d0':>7} {'IV_d1':>7} {'IV_d2':>7} {'IV_mean':>8} {'std':>7}")
    for K in ACTIVE_STRIKES:
        v = voucher_params["by_strike"][str(K)]
        ivs = v["iv_per_day"]
        lines.append(f"{K:>6} {ivs.get('0', 0):>7.4f} {ivs.get('1', 0):>7.4f} {ivs.get('2', 0):>7.4f} {v['iv_mean']:>8.4f} {v['iv_std_across_days']:>7.5f}")

    lines.append("\n### Per-strike book + taker (active)")
    for K in ACTIVE_STRIKES:
        b = vev_books[K]
        t = takers[f"VEV_{K}"]
        lines.append(f"VEV_{K}: walls {b['bid_wall_offset']}/+{b['ask_wall_offset']}  inners {b['bid_inner_offset']}/+{b['ask_inner_offset']}")
        lines.append(f"  wall_vol b/a: {b['wall_vol_bid']['mean']:.1f}/{b['wall_vol_ask']['mean']:.1f}  inner_vol b/a: {b['inner_vol_bid']['mean']:.1f}/{b['inner_vol_ask']['mean']:.1f}")
        lines.append(f"  bot3 rates b/a: {b['bot3_bid_rate']:.3f}/{b['bot3_ask_rate']:.3f}  passive_frac: {b['bot3_passive_frac']:.3f}")
        lines.append(f"  taker: rate={t['taker_rate_per_tick']:.4f}  qty_support={t['qty_support']}  side_buy={t['side_buy_frac']:.3f}")

    lines.append("\n### Pinned-strike observations")
    for K in PINNED_STRIKES:
        v = voucher_params["by_strike"][str(K)]
        t = takers[f"VEV_{K}"]
        lines.append(f"VEV_{K}: bid_price_observed={v['bid_price_observed']}  ask_price_observed={v['ask_price_observed']}")
        lines.append(f"  bid_vol_mean={v['bid_volume_mean']:.1f}  ask_vol_mean={v['ask_volume_mean']:.1f}")
        lines.append(f"  taker: n_trades={t['n_trades']} (over {t['n_ticks']} ticks)")

    out_txt = DOCS / "round3_calibration_summary.txt"
    out_txt.write_text("\n".join(lines))
    print(f"wrote {out_txt}")


if __name__ == "__main__":
    main()
