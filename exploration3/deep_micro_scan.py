"""Deep microstructure scan — find anything odd about bot activity.

Not looking for tradable alpha (session 3 found that's unreliable).
Looking for weird patterns: periodicities, outliers, deterministic
sequences, rule violations vs the calibration docs.

Outputs sectioned text report.
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
    return p


def load_trades(day, product):
    t = pd.read_csv(DATA / f"trades_round_2_day_{day}.csv", sep=";")
    return t[t["symbol"] == PRODUCTS[product]].sort_values("timestamp").reset_index(drop=True)


def classify_trade(p, tr):
    ts = int(tr["timestamp"])
    row = p[p["timestamp"] == ts]
    if row.empty: return None
    bid1, ask1 = row["bid_price_1"].iloc[0], row["ask_price_1"].iloc[0]
    if pd.notna(ask1) and abs(tr["price"] - ask1) < 0.01: return "BUY"
    if pd.notna(bid1) and abs(tr["price"] - bid1) < 0.01: return "SELL"
    # trade price between: could be hidden L1 or through-book
    if pd.notna(bid1) and pd.notna(ask1):
        if tr["price"] > (bid1 + ask1) / 2: return "BUY_MID"
        else: return "SELL_MID"
    return "UNK"


def trade_timing_periodicity():
    print("\n" + "=" * 100)
    print("TRADE TIMING PERIODICITY — ts % N distributions")
    print("=" * 100)
    for product in ("OSM", "PEP"):
        print(f"\n### {product} ###")
        all_ts = []
        for day in (-1, 0, 1):
            t = load_trades(day, product)
            all_ts.extend(int(x) for x in t["timestamp"])
        all_ts = np.array(all_ts)
        # In IMC ticks are every 100, so ts % 100 should all be 0
        for mod in (100, 200, 500, 1000, 2000, 5000):
            residues = all_ts % mod
            unique = np.unique(residues)
            c = Counter(residues.tolist())
            top3 = sorted(c.items(), key=lambda x: -x[1])[:5]
            expected_uniform = len(all_ts) / (mod // 100)  # assuming ticks at 100 spacing
            if len(unique) <= 10:
                print(f"  ts%{mod}: unique={len(unique)}  top5={top3}")


def trade_size_direction():
    print("\n" + "=" * 100)
    print("TRADE SIZE BY DIRECTION")
    print("=" * 100)
    for product in ("OSM", "PEP"):
        print(f"\n### {product} ###")
        buy_sizes = []; sell_sizes = []
        for day in (-1, 0, 1):
            p = load_prices(day, product)
            trades = load_trades(day, product)
            for _, tr in trades.iterrows():
                cls = classify_trade(p, tr)
                if cls == "BUY": buy_sizes.append(int(tr["quantity"]))
                elif cls == "SELL": sell_sizes.append(int(tr["quantity"]))
        if buy_sizes:
            bc = Counter(buy_sizes)
            sc = Counter(sell_sizes)
            print(f"  BUY trades n={len(buy_sizes)}: sizes {sorted(bc.items())}")
            print(f"  SELL trades n={len(sell_sizes)}: sizes {sorted(sc.items())}")
            print(f"  BUY  avg={np.mean(buy_sizes):.2f} median={np.median(buy_sizes):.1f}")
            print(f"  SELL avg={np.mean(sell_sizes):.2f} median={np.median(sell_sizes):.1f}")


def multi_trade_ticks():
    print("\n" + "=" * 100)
    print("MULTI-TRADE TICKS — does one tick have 2+ trades?")
    print("=" * 100)
    for product in ("OSM", "PEP"):
        print(f"\n### {product} ###")
        for day in (-1, 0, 1):
            trades = load_trades(day, product)
            ts_counts = Counter(trades["timestamp"].values.tolist())
            multi = [c for c in ts_counts.values() if c > 1]
            if multi:
                print(f"  day {day}: multi-trade ticks={len(multi)}, max_trades_in_tick={max(multi)}, total_trades={sum(ts_counts.values())}")
                # What are the multi-trade ticks like?
                multi_ts = [ts for ts, c in ts_counts.items() if c >= 2]
                sample = sorted(multi_ts)[:3]
                for ts in sample:
                    trs = trades[trades["timestamp"] == ts]
                    print(f"    ts={ts}:")
                    for _, tr in trs.iterrows():
                        print(f"      px={tr['price']}  qty={tr['quantity']}")
            else:
                print(f"  day {day}: no multi-trade ticks")


def trade_sequence_markov():
    print("\n" + "=" * 100)
    print("TRADE DIRECTION MARKOV — consecutive-trade transitions")
    print("=" * 100)
    for product in ("OSM", "PEP"):
        print(f"\n### {product} ###")
        transitions = Counter()  # (prev, cur) -> count
        totals_prev = Counter()
        for day in (-1, 0, 1):
            p = load_prices(day, product)
            trades = load_trades(day, product)
            seq = []
            for _, tr in trades.iterrows():
                cls = classify_trade(p, tr)
                if cls in ("BUY", "SELL"):
                    seq.append(cls[0])  # 'B' or 'S'
            for i in range(1, len(seq)):
                transitions[(seq[i-1], seq[i])] += 1
                totals_prev[seq[i-1]] += 1
        if totals_prev:
            print("  transition probabilities (rows sum to 1):")
            for prev in "BS":
                for cur in "BS":
                    n = transitions.get((prev, cur), 0)
                    tot = totals_prev.get(prev, 1)
                    print(f"    P({cur} | prev={prev}) = {n/tot:.3f}  (n={n}/{tot})")
            # Expected under independence (base rate of each direction)
            tot_B = sum(n for (p_,c), n in transitions.items() if c == "B")
            tot_S = sum(n for (p_,c), n in transitions.items() if c == "S")
            grand = tot_B + tot_S
            print(f"  base rates: P(B)={tot_B/grand:.3f}  P(S)={tot_S/grand:.3f}")


def trade_gap_distribution():
    print("\n" + "=" * 100)
    print("TRADE GAP — ticks between consecutive trades")
    print("=" * 100)
    for product in ("OSM", "PEP"):
        print(f"\n### {product} ###")
        all_gaps = []
        for day in (-1, 0, 1):
            trades = load_trades(day, product)
            ts = trades["timestamp"].values.astype(int)
            gaps = np.diff(ts) // 100  # in ticks
            all_gaps.extend(gaps.tolist())
        all_gaps = np.array(all_gaps)
        # Distribution
        mean = all_gaps.mean(); std = all_gaps.std(); cv = std/mean
        c = Counter(all_gaps.tolist())
        top = sorted(c.items(), key=lambda x: -x[1])[:10]
        print(f"  mean_gap={mean:.2f}  std={std:.2f}  cv={cv:.2f}")
        print(f"  top 10 gaps: {top}")
        # If geometric, P(gap=1) = highest. If periodic, gap=period dominates.
        # Check specifically: are 0-gap trades (same tick, multi-trade) common?
        same_tick = (all_gaps == 0).sum()
        print(f"  same-tick trades (gap=0): {same_tick}")


def price_tick_distribution():
    print("\n" + "=" * 100)
    print("PRICE TICK DISTRIBUTION — mid movements between consecutive snapshots")
    print("=" * 100)
    for product in ("OSM", "PEP"):
        print(f"\n### {product} ###")
        for day in (-1, 0, 1):
            p = load_prices(day, product)
            mid_diffs = p["mid"].diff().dropna()
            c = Counter(mid_diffs.round(1).tolist())
            top = sorted(c.items(), key=lambda x: -x[1])[:10]
            print(f"  day {day}: top-10 mid-diffs: {top}")


def hidden_trade_prices():
    """Trades NOT at bid_1 or ask_1 — evidence of hidden quotes."""
    print("\n" + "=" * 100)
    print("HIDDEN-TRADE PRICES — trades not at visible L1 (evidence of 80% quote subsampling)")
    print("=" * 100)
    for product in ("OSM", "PEP"):
        print(f"\n### {product} ###")
        total = 0; hidden = 0
        hidden_details = []
        for day in (-1, 0, 1):
            p = load_prices(day, product)
            trades = load_trades(day, product)
            for _, tr in trades.iterrows():
                cls = classify_trade(p, tr)
                total += 1
                if cls in ("BUY_MID", "SELL_MID"):
                    hidden += 1
                    ts = int(tr["timestamp"])
                    row = p[p["timestamp"] == ts]
                    if not row.empty:
                        b1, a1 = row["bid_price_1"].iloc[0], row["ask_price_1"].iloc[0]
                        hidden_details.append((ts, float(tr["price"]), float(b1) if pd.notna(b1) else None, float(a1) if pd.notna(a1) else None, int(tr["quantity"])))
        pct = 100 * hidden / max(total, 1)
        print(f"  total trades: {total}  at-mid (neither L1): {hidden} ({pct:.1f}%)")
        if hidden_details[:5]:
            print(f"  first 5 hidden-price trades (ts, trade_px, bid1, ask1, qty):")
            for d in hidden_details[:5]:
                print(f"    {d}")


def wall_price_moves():
    """How often does wall price (outermost level) move, and in what direction?"""
    print("\n" + "=" * 100)
    print("WALL PRICE MOVES — outermost-level price changes")
    print("=" * 100)
    for product in ("OSM", "PEP"):
        print(f"\n### {product} ###")
        for day in (-1, 0, 1):
            p = load_prices(day, product)
            bw = []; aw = []
            for i in range(len(p)):
                bids = [(p[f"bid_price_{k}"].iloc[i], p[f"bid_volume_{k}"].iloc[i]) for k in (1,2,3)]
                bids = [(px, v) for (px, v) in bids if pd.notna(px)]
                asks = [(p[f"ask_price_{k}"].iloc[i], p[f"ask_volume_{k}"].iloc[i]) for k in (1,2,3)]
                asks = [(px, v) for (px, v) in asks if pd.notna(px)]
                bw.append(min(bids, key=lambda x: x[0])[0] if bids else np.nan)
                aw.append(max(asks, key=lambda x: x[0])[0] if asks else np.nan)
            bw = np.array(bw); aw = np.array(aw)
            bw_moves = np.diff(bw); aw_moves = np.diff(aw)
            bw_moves_nz = bw_moves[~np.isnan(bw_moves) & (bw_moves != 0)]
            aw_moves_nz = aw_moves[~np.isnan(aw_moves) & (aw_moves != 0)]
            print(f"  day {day}: bid-wall moves (non-zero): {len(bw_moves_nz)}, ask-wall moves: {len(aw_moves_nz)}  "
                  f"mean_bw_move={bw_moves_nz.mean() if len(bw_moves_nz) else 'n/a':.2f}  "
                  f"mean_aw_move={aw_moves_nz.mean() if len(aw_moves_nz) else 'n/a':.2f}")


def volume_outliers():
    """When wall vol is <20 (OSM) or <15 (PEP) — docs say uniform lower bound. These are outliers. What triggers them?"""
    print("\n" + "=" * 100)
    print("VOLUME-OUTLIER WALLS — walls below docs' lower bound")
    print("=" * 100)
    for product in ("OSM", "PEP"):
        lo = 20 if product == "OSM" else 15
        print(f"\n### {product} (threshold vol < {lo}) ###")
        for day in (-1, 0, 1):
            p = load_prices(day, product)
            outlier_ticks_bid = 0; outlier_ticks_ask = 0
            outlier_preceded_by_trade_bid = 0; outlier_preceded_by_trade_ask = 0
            trades = load_trades(day, product)
            trade_ts = set(trades["timestamp"].values.tolist())
            for i in range(len(p)):
                bids = [(p[f"bid_price_{k}"].iloc[i], p[f"bid_volume_{k}"].iloc[i]) for k in (1,2,3)]
                bids = [(px, v) for (px, v) in bids if pd.notna(px)]
                asks = [(p[f"ask_price_{k}"].iloc[i], p[f"ask_volume_{k}"].iloc[i]) for k in (1,2,3)]
                asks = [(px, v) for (px, v) in asks if pd.notna(px)]
                if bids:
                    bw_vol = min(bids, key=lambda x: x[0])[1]
                    if bw_vol < lo:
                        outlier_ticks_bid += 1
                        if i > 0 and int(p["timestamp"].iloc[i-1]) in trade_ts:
                            outlier_preceded_by_trade_bid += 1
                if asks:
                    aw_vol = max(asks, key=lambda x: x[0])[1]
                    if aw_vol < lo:
                        outlier_ticks_ask += 1
                        if i > 0 and int(p["timestamp"].iloc[i-1]) in trade_ts:
                            outlier_preceded_by_trade_ask += 1
            print(f"  day {day}: outlier bid-walls={outlier_ticks_bid}  preceded by trade in prev tick: {outlier_preceded_by_trade_bid}")
            print(f"          outlier ask-walls={outlier_ticks_ask}  preceded by trade in prev tick: {outlier_preceded_by_trade_ask}")


def main():
    trade_timing_periodicity()
    trade_size_direction()
    multi_trade_ticks()
    trade_sequence_markov()
    trade_gap_distribution()
    price_tick_distribution()
    hidden_trade_prices()
    wall_price_moves()
    volume_outliers()


if __name__ == "__main__":
    main()
