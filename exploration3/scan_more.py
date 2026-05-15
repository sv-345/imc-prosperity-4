"""More pattern scans.

H7: Inner quote volume imbalance
H8: Wall vol transitions (change between consecutive ticks)
H9: Session-time patterns (by quartile)
H10: Trade-triggered patterns — after BOT-BOT trade, what happens?
H11: L1 side absence — when only one side has L1, what follows?
H12: Bot-3 appearance conditional on prior wall-vol change
"""
from __future__ import annotations
import pathlib, numpy as np, pandas as pd
from collections import Counter, defaultdict

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "ROUND_2"
PRODUCTS = {"OSM": "ASH_COATED_OSMIUM", "PEP": "INTARIAN_PEPPER_ROOT"}


def load_prices(day, product):
    p = pd.read_csv(DATA / f"prices_round_2_day_{day}.csv", sep=";")
    p = p[p["product"] == PRODUCTS[product]].sort_values("timestamp").reset_index(drop=True)
    p["mid"] = (p["bid_price_1"] + p["ask_price_1"]) / 2.0
    if product == "PEP":
        day_start = {-1: 11000, 0: 12000, 1: 13000}[day]
        p["dmid"] = p["mid"] - (day_start + 0.1 * (p["timestamp"] // 100))
    else:
        p["dmid"] = p["mid"]
    return p


def load_trades(day, product):
    t = pd.read_csv(DATA / f"trades_round_2_day_{day}.csv", sep=";")
    return t[t["symbol"] == PRODUCTS[product]].sort_values("timestamp").reset_index(drop=True)


def inner_vol_imbalance():
    """H7: inner-most bid vs ask volume (L1)."""
    print("\n" + "=" * 100)
    print("H7 — INNER QUOTE (L1) VOL IMBALANCE")
    print("=" * 100)
    for product in ("OSM", "PEP"):
        print(f"\n### {product} ###")
        imb_moves = defaultdict(list)
        for day in (-1, 0, 1):
            p = load_prices(day, product)
            for i in range(len(p) - 1):
                bv = p["bid_volume_1"].iloc[i]
                av = p["ask_volume_1"].iloc[i]
                if pd.notna(bv) and pd.notna(av):
                    imb = int(bv - av)
                    nm = p["dmid"].iloc[i+1] - p["dmid"].iloc[i]
                    if not np.isnan(nm):
                        imb_moves[imb].append(nm)
        # aggregate
        for imb in sorted(imb_moves):
            mvs = np.array(imb_moves[imb])
            if len(mvs) < 50: continue
            mean = mvs.mean(); t = mean / (mvs.std() / np.sqrt(len(mvs)) + 1e-9)
            print(f"  imb={imb:+3d}: n={len(mvs):5d}  mean={mean:+.3f}  t={t:+.2f}")


def wall_vol_transitions():
    """H8: wall vol change between consecutive ticks."""
    print("\n" + "=" * 100)
    print("H8 — WALL VOL TRANSITION (ΔBID_WALL_VOL, ΔASK_WALL_VOL)")
    print("=" * 100)
    for product in ("OSM", "PEP"):
        print(f"\n### {product} ###")
        delta_moves = defaultdict(list)
        for day in (-1, 0, 1):
            p = load_prices(day, product)
            prev_bw = prev_aw = None
            for i in range(len(p) - 1):
                bids = [(p[f"bid_price_{k}"].iloc[i], p[f"bid_volume_{k}"].iloc[i]) for k in (1,2,3)]
                bids = [(px, v) for (px, v) in bids if pd.notna(px)]
                asks = [(p[f"ask_price_{k}"].iloc[i], p[f"ask_volume_{k}"].iloc[i]) for k in (1,2,3)]
                asks = [(px, v) for (px, v) in asks if pd.notna(px)]
                if not bids or not asks: continue
                bw = int(min(bids, key=lambda x: x[0])[1])
                aw = int(max(asks, key=lambda x: x[0])[1])
                if prev_bw is not None:
                    d_bw = bw - prev_bw
                    d_aw = aw - prev_aw
                    nm = p["dmid"].iloc[i+1] - p["dmid"].iloc[i]
                    if not np.isnan(nm):
                        delta_moves[(d_bw, d_aw)].append(nm)
                prev_bw = bw; prev_aw = aw
        # aggregate
        total_combos = sorted(((k, len(v)) for k, v in delta_moves.items()), key=lambda x: -x[1])
        # Look at net asymmetry: d_bw - d_aw
        asym_moves = defaultdict(list)
        for (dbw, daw), mvs in delta_moves.items():
            asym_moves[dbw - daw].extend(mvs)
        for a in sorted(asym_moves):
            mvs = np.array(asym_moves[a])
            if len(mvs) < 100: continue
            mean = mvs.mean(); t = mean / (mvs.std() / np.sqrt(len(mvs)) + 1e-9)
            print(f"  Δbw−Δaw={a:+3d}: n={len(mvs):5d}  mean={mean:+.3f}  t={t:+.2f}")


def session_time_patterns():
    """H9: are signals concentrated in specific session-time quintiles?"""
    print("\n" + "=" * 100)
    print("H9 — WALL-IMB SIGNAL BY SESSION QUINTILE (does it hold in Q1 too? or only mid-day?)")
    print("=" * 100)
    for product in ("OSM", "PEP"):
        print(f"\n### {product} ###")
        for q in range(5):
            imb_moves = []
            for day in (-1, 0, 1):
                p = load_prices(day, product)
                n = len(p)
                lo = q * n // 5
                hi = (q + 1) * n // 5
                for i in range(lo, hi - 1):
                    bids = [(p[f"bid_price_{k}"].iloc[i], p[f"bid_volume_{k}"].iloc[i]) for k in (1,2,3)]
                    bids = [(px, v) for (px, v) in bids if pd.notna(px)]
                    asks = [(p[f"ask_price_{k}"].iloc[i], p[f"ask_volume_{k}"].iloc[i]) for k in (1,2,3)]
                    asks = [(px, v) for (px, v) in asks if pd.notna(px)]
                    if not bids or not asks: continue
                    bw = int(min(bids, key=lambda x: x[0])[1])
                    aw = int(max(asks, key=lambda x: x[0])[1])
                    imb = bw - aw
                    if abs(imb) >= 8:
                        nm = p["dmid"].iloc[i+1] - p["dmid"].iloc[i]
                        if not np.isnan(nm):
                            imb_moves.append((imb, nm))
            if len(imb_moves) < 100: continue
            # compute signed-predictive: multiply nm by sign(imb), should be >0 if signal holds
            signed = np.array([np.sign(im) * nm for (im, nm) in imb_moves])
            mean = signed.mean(); tstat = mean / (signed.std() / np.sqrt(len(signed)) + 1e-9)
            print(f"  Q{q+1}: n_imb>=8={len(imb_moves):4d}  mean(sign(imb)*dmid_next)={mean:+.3f}  t={tstat:+.2f}")


def post_bot_bot_trade():
    """H10: After a bot-bot trade (non-SUBMISSION), does the book refresh differently?"""
    print("\n" + "=" * 100)
    print("H10 — POST-TRADE BOOK REFRESH (direction of mid move after trade)")
    print("=" * 100)
    for product in ("OSM", "PEP"):
        print(f"\n### {product} ###")
        for day in (-1, 0, 1):
            p = load_prices(day, product)
            trades = load_trades(day, product)
            ts_to_i = {int(t): i for i, t in enumerate(p["timestamp"])}
            buy_after, sell_after = [], []
            for _, tr in trades.iterrows():
                ts = int(tr["timestamp"]); i = ts_to_i.get(ts)
                if i is None or i + 1 >= len(p): continue
                ask1, bid1 = p["ask_price_1"].iloc[i], p["bid_price_1"].iloc[i]
                next_mid = p["dmid"].iloc[i+1]
                this_mid = p["dmid"].iloc[i]
                if np.isnan(next_mid) or np.isnan(this_mid): continue
                delta = next_mid - this_mid
                if pd.notna(ask1) and abs(tr["price"] - ask1) < 0.01:
                    buy_after.append(delta)
                elif pd.notna(bid1) and abs(tr["price"] - bid1) < 0.01:
                    sell_after.append(delta)
            if buy_after and sell_after:
                ba = np.array(buy_after); sa = np.array(sell_after)
                print(f"  day {day}: after BUY-taker n={len(ba):3d} next-dmid mean={ba.mean():+.3f} t={ba.mean()/(ba.std()/np.sqrt(len(ba))+1e-9):+.2f}  |  "
                      f"after SELL-taker n={len(sa):3d} mean={sa.mean():+.3f} t={sa.mean()/(sa.std()/np.sqrt(len(sa))+1e-9):+.2f}")


def one_sided_book():
    """H11: when only bid or only ask has L1, what comes next?"""
    print("\n" + "=" * 100)
    print("H11 — ONE-SIDED BOOK (only bid or only ask has L1)")
    print("=" * 100)
    for product in ("OSM", "PEP"):
        print(f"\n### {product} ###")
        only_bid = []; only_ask = []; both_present = []
        for day in (-1, 0, 1):
            p = load_prices(day, product)
            for i in range(len(p) - 1):
                has_bid = pd.notna(p["bid_price_1"].iloc[i])
                has_ask = pd.notna(p["ask_price_1"].iloc[i])
                next_mid = p["dmid"].iloc[i+1]
                this_mid = p["dmid"].iloc[i]
                if np.isnan(next_mid): continue
                delta = next_mid - this_mid if not np.isnan(this_mid) else None
                if has_bid and not has_ask and delta is not None:
                    only_bid.append(delta)
                elif has_ask and not has_bid and delta is not None:
                    only_ask.append(delta)
                elif has_bid and has_ask and delta is not None:
                    both_present.append(delta)
        print(f"  only-bid n={len(only_bid):4d}  mean-next-dmid={np.mean(only_bid) if only_bid else 'n/a'}")
        print(f"  only-ask n={len(only_ask):4d}  mean-next-dmid={np.mean(only_ask) if only_ask else 'n/a'}")
        print(f"  both     n={len(both_present):5d}  mean-next-dmid={np.mean(both_present):.3f}")


def main():
    inner_vol_imbalance()
    wall_vol_transitions()
    session_time_patterns()
    post_bot_bot_trade()
    one_sided_book()


if __name__ == "__main__":
    main()
