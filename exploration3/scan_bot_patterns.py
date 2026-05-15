"""Scan bot patterns for candidate rules — exploration 3.

Tests:
  H1: Wall volume distribution & autocorrelation
  H2: L3 (3rd level) appearance trigger — what precedes/follows?
  H3: Post-trade book reaction — does volume replenish?
  H4: Bot-3 inter-arrival periodicity
  H5: Wall vol dip predicts trade
  H6: Specific vol values (e.g., exactly 20 or exactly 30) have signals
"""
from __future__ import annotations
import pathlib
import numpy as np
import pandas as pd
from collections import Counter, defaultdict

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "ROUND_2"
PRODUCTS = {"OSM": "ASH_COATED_OSMIUM", "PEP": "INTARIAN_PEPPER_ROOT"}


def load_prices(day: int, product: str) -> pd.DataFrame:
    p = pd.read_csv(DATA / f"prices_round_2_day_{day}.csv", sep=";")
    p = p[p["product"] == PRODUCTS[product]].sort_values("timestamp").reset_index(drop=True)
    p["mid"] = (p["bid_price_1"] + p["ask_price_1"]) / 2.0
    return p


def load_trades(day: int, product: str) -> pd.DataFrame:
    t = pd.read_csv(DATA / f"trades_round_2_day_{day}.csv", sep=";")
    return t[t["symbol"] == PRODUCTS[product]].sort_values("timestamp").reset_index(drop=True)


def wall_vol_distribution():
    """H1: is wall vol U(20,30) or something else?"""
    print("\n" + "=" * 100)
    print("H1 — WALL VOLUME DISTRIBUTION")
    print("=" * 100)
    for product in ("OSM", "PEP"):
        print(f"\n### {product} ###")
        bid_wall_vols: list[int] = []
        ask_wall_vols: list[int] = []
        for day in (-1, 0, 1):
            p = load_prices(day, product)
            for i in range(len(p)):
                # wall = outer-most level
                bids = [(p[f"bid_price_{k}"].iloc[i], p[f"bid_volume_{k}"].iloc[i]) for k in (1,2,3)]
                bids = [(px, v) for (px, v) in bids if pd.notna(px)]
                if bids:
                    bp_min = min(bids, key=lambda x: x[0])
                    bid_wall_vols.append(int(bp_min[1]))
                asks = [(p[f"ask_price_{k}"].iloc[i], p[f"ask_volume_{k}"].iloc[i]) for k in (1,2,3)]
                asks = [(px, v) for (px, v) in asks if pd.notna(px)]
                if asks:
                    ap_max = max(asks, key=lambda x: x[0])
                    ask_wall_vols.append(int(ap_max[1]))
        # distribution
        for name, vols in (("bid wall", bid_wall_vols), ("ask wall", ask_wall_vols)):
            c = Counter(vols)
            top = sorted(c.items(), key=lambda x: -x[1])[:15]
            pct_coverage = sum(c[v] for v in range(20, 31)) / len(vols) * 100
            print(f"  {name}: n={len(vols)}, range={min(vols)}..{max(vols)}, top15={top}")
            print(f"         20-30 coverage: {pct_coverage:.1f}%")


def l3_triggers():
    """H2: what precedes L3 book appearance?"""
    print("\n" + "=" * 100)
    print("H2 — L3 APPEARANCE TRIGGERS")
    print("=" * 100)
    for product in ("OSM", "PEP"):
        print(f"\n### {product} ###")
        bid_l3_prev_trades = 0  # ticks with bid L3 that had a trade in prev tick
        bid_l3_total = 0
        ask_l3_prev_trades = 0
        ask_l3_total = 0
        bid_l3_next_trades = 0  # trades at tick where bid L3 present
        ask_l3_next_trades = 0
        for day in (-1, 0, 1):
            p = load_prices(day, product)
            trades = load_trades(day, product)
            trades_by_ts = set(trades["timestamp"].values)

            for i in range(len(p)):
                ts = p["timestamp"].iloc[i]
                prev_ts = p["timestamp"].iloc[i-1] if i > 0 else None
                next_ts = p["timestamp"].iloc[i+1] if i < len(p)-1 else None

                has_bid_l3 = pd.notna(p["bid_price_3"].iloc[i])
                has_ask_l3 = pd.notna(p["ask_price_3"].iloc[i])

                if has_bid_l3:
                    bid_l3_total += 1
                    if prev_ts is not None and prev_ts in trades_by_ts:
                        bid_l3_prev_trades += 1
                    if next_ts is not None and next_ts in trades_by_ts:
                        bid_l3_next_trades += 1
                if has_ask_l3:
                    ask_l3_total += 1
                    if prev_ts is not None and prev_ts in trades_by_ts:
                        ask_l3_prev_trades += 1
                    if next_ts is not None and next_ts in trades_by_ts:
                        ask_l3_next_trades += 1

        base_rate_prev = len(trades) / len(p) if len(p) else 0  # only last-day for reference
        print(f"  bid L3 total: {bid_l3_total}  prev-trade: {bid_l3_prev_trades} ({100*bid_l3_prev_trades/max(bid_l3_total,1):.1f}%)  "
              f"next-trade: {bid_l3_next_trades} ({100*bid_l3_next_trades/max(bid_l3_total,1):.1f}%)")
        print(f"  ask L3 total: {ask_l3_total}  prev-trade: {ask_l3_prev_trades} ({100*ask_l3_prev_trades/max(ask_l3_total,1):.1f}%)  "
              f"next-trade: {ask_l3_next_trades} ({100*ask_l3_next_trades/max(ask_l3_total,1):.1f}%)")
        print(f"  baseline trade rate (random tick): {100*base_rate_prev:.1f}%")


def post_trade_book_reaction():
    """H3: after a trade hits ask/bid, what happens next tick?"""
    print("\n" + "=" * 100)
    print("H3 — POST-TRADE BOOK REACTION")
    print("=" * 100)
    for product in ("OSM", "PEP"):
        print(f"\n### {product} ###")
        ask_hit_events = []     # for each: (prev_ask1_vol, trade_qty, next_ask1_vol, next_ask1_px - prev_ask1_px)
        bid_hit_events = []
        for day in (-1, 0, 1):
            p = load_prices(day, product)
            trades = load_trades(day, product)
            # Map ts -> row index
            ts_to_i = {int(ts): i for i, ts in enumerate(p["timestamp"])}

            for _, tr in trades.iterrows():
                ts = int(tr["timestamp"])
                i = ts_to_i.get(ts)
                if i is None or i + 1 >= len(p): continue
                # check if trade at ask or bid
                ask1 = p["ask_price_1"].iloc[i]
                bid1 = p["bid_price_1"].iloc[i]
                if pd.notna(ask1) and abs(tr["price"] - ask1) < 0.01:
                    # trade at ask — buy-taker
                    prev_ask_vol = int(p["ask_volume_1"].iloc[i])
                    next_ask_px = p["ask_price_1"].iloc[i+1]
                    next_ask_vol = p["ask_volume_1"].iloc[i+1]
                    if pd.notna(next_ask_px):
                        ask_hit_events.append((prev_ask_vol, int(tr["quantity"]), int(next_ask_vol), int(next_ask_px - ask1)))
                elif pd.notna(bid1) and abs(tr["price"] - bid1) < 0.01:
                    prev_bid_vol = int(p["bid_volume_1"].iloc[i])
                    next_bid_px = p["bid_price_1"].iloc[i+1]
                    next_bid_vol = p["bid_volume_1"].iloc[i+1]
                    if pd.notna(next_bid_px):
                        bid_hit_events.append((prev_bid_vol, int(tr["quantity"]), int(next_bid_vol), int(next_bid_px - bid1)))

        for name, evs in (("ask-hit (buy-taker)", ask_hit_events), ("bid-hit (sell-taker)", bid_hit_events)):
            if not evs: continue
            n = len(evs)
            prev_v = np.array([e[0] for e in evs])
            trade_q = np.array([e[1] for e in evs])
            next_v = np.array([e[2] for e in evs])
            next_px_shift = np.array([e[3] for e in evs])
            expected_remain = prev_v - trade_q
            # does next-tick ask_1 restore volume (new bot replenishes)?
            restored = np.sum(next_v > expected_remain)
            moved_price = np.sum(next_px_shift != 0)
            print(f"  {name}: n={n}  "
                  f"next-px-moved: {moved_price} ({100*moved_price/n:.1f}%)  "
                  f"next-vol > expected_remain: {restored} ({100*restored/n:.1f}%)")
            print(f"    mean next-px-shift: {next_px_shift.mean():+.2f}  (buy-takers should push ask UP)")


def bot3_inter_arrival():
    """H4: is bot-3 appearance deterministic or Poisson?"""
    print("\n" + "=" * 100)
    print("H4 — BOT-3 INTER-ARRIVAL")
    print("=" * 100)
    for product in ("OSM", "PEP"):
        print(f"\n### {product} ###")
        for day in (-1, 0, 1):
            p = load_prices(day, product)
            # rolling-median mid to classify aggressive events
            ref = p["mid"].rolling(51, center=True, min_periods=5).median().values
            floor_ref = np.floor(ref)
            events = []
            for i in range(len(p)):
                if pd.isna(ref[i]): continue
                ff = floor_ref[i]
                for k in (1,2,3):
                    bp = p[f"bid_price_{k}"].iloc[i]
                    ap = p[f"ask_price_{k}"].iloc[i]
                    if pd.notna(bp) and bp > ref[i]:
                        events.append(i)
                        break
                    if pd.notna(ap) and ap < ref[i]:
                        events.append(i)
                        break
            events = sorted(set(events))
            if len(events) < 10: continue
            diffs = np.diff(events)
            c = Counter(diffs.tolist())
            top = sorted(c.items(), key=lambda x: -x[1])[:10]
            # Is distribution geometric (Poisson inter-arrivals) or not?
            # Mean is expected. If geometric, var ~ mean^2. If fixed-period, var ~ 0.
            mean_d = diffs.mean(); std_d = diffs.std()
            print(f"  day {day}: n_events={len(events)}  mean_gap={mean_d:.1f}  std_gap={std_d:.1f}  cv={std_d/mean_d:.2f}  top_gaps={top[:5]}")


def volume_specific_signals():
    """H6: specific wall vol values (e.g., 30 exactly, 20 exactly) predict anything?"""
    print("\n" + "=" * 100)
    print("H6 — SPECIFIC WALL-VOLUME TICKS & NEXT-TICK MID MOVE")
    print("=" * 100)
    for product in ("OSM", "PEP"):
        print(f"\n### {product} ###")
        ap_vs_midmove: dict[tuple, list[float]] = defaultdict(list)  # (bid_wall_vol, ask_wall_vol) -> next-mid deltas
        for day in (-1, 0, 1):
            p = load_prices(day, product)
            # compute detrended mid (for PEP, remove drift)
            if product == "PEP":
                day_start = {-1: 11000, 0: 12000, 1: 13000}[day]
                p["fv"] = day_start + 0.1 * (p["timestamp"] // 100)
                p["dmid"] = p["mid"] - p["fv"]
            else:
                p["dmid"] = p["mid"]

            # extract wall vols
            for i in range(len(p) - 1):
                bids = [(p[f"bid_price_{k}"].iloc[i], p[f"bid_volume_{k}"].iloc[i]) for k in (1,2,3)]
                bids = [(px, v) for (px, v) in bids if pd.notna(px)]
                asks = [(p[f"ask_price_{k}"].iloc[i], p[f"ask_volume_{k}"].iloc[i]) for k in (1,2,3)]
                asks = [(px, v) for (px, v) in asks if pd.notna(px)]
                if not bids or not asks: continue
                bw = int(min(bids, key=lambda x: x[0])[1])
                aw = int(max(asks, key=lambda x: x[0])[1])
                next_move = p["dmid"].iloc[i+1] - p["dmid"].iloc[i]
                if not np.isnan(next_move):
                    ap_vs_midmove[(bw, aw)].append(float(next_move))

        # Aggregate: for common (bw, aw) combos, compute mean next-move
        combo_counts = {k: len(v) for k, v in ap_vs_midmove.items()}
        common = sorted(combo_counts.items(), key=lambda x: -x[1])[:10]
        print(f"  top 10 (bid_wall_vol, ask_wall_vol) combos:")
        for (bw, aw), n in common:
            moves = np.array(ap_vs_midmove[(bw, aw)])
            mean_m = moves.mean(); tstat = mean_m / (moves.std() / np.sqrt(len(moves)) + 1e-9)
            print(f"    ({bw:2d},{aw:2d}): n={n:4d}  mean_next_dmid={mean_m:+.3f}  t={tstat:+.2f}")

        # Also: overall imbalance signal
        ibw_map = defaultdict(list)  # bw - aw -> next-move
        for (bw, aw), moves in ap_vs_midmove.items():
            imb = bw - aw
            ibw_map[imb].extend(moves)
        print(f"\n  wall-vol imbalance (bid_vol - ask_vol) vs next-tick detrended-mid:")
        for imb in sorted(ibw_map.keys()):
            moves = np.array(ibw_map[imb])
            if len(moves) < 50: continue
            mean_m = moves.mean(); tstat = mean_m / (moves.std() / np.sqrt(len(moves)) + 1e-9)
            print(f"    imb={imb:+3d}: n={len(moves):5d}  mean={mean_m:+.3f}  t={tstat:+.2f}")


def main() -> None:
    wall_vol_distribution()
    l3_triggers()
    post_trade_book_reaction()
    bot3_inter_arrival()
    volume_specific_signals()


if __name__ == "__main__":
    main()
