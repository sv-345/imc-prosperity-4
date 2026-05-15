"""
Tick-by-tick bot-behavior visualizer for Round 2.

Renders bid/ask book levels as dots over time, overlays mid, wall-mid, reference FV,
and highlights aggressive-bot-3 events (bid crossing into F+ territory or ask into F-).

Usage:
  python3 visualize_bots.py [--day -1|0|1] [--product OSM|PEP|BOTH] [--start 0] [--end 1000000]

Output: exploration/viz_{product}_day{d}_{start}_{end}.html
"""

from __future__ import annotations
import argparse
import pathlib
import numpy as np
import pandas as pd
import plotly.graph_objects as go

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "ROUND_2"
OUT = ROOT / "exploration"
OUT.mkdir(exist_ok=True)

PRODUCTS = {"OSM": "ASH_COATED_OSMIUM", "PEP": "INTARIAN_PEPPER_ROOT"}


def fv_of(product: str, day: int, ts: np.ndarray) -> np.ndarray:
    if product == "OSM":
        return np.full_like(ts, 10001.0, dtype=float)
    day_start = {-1: 11000, 0: 12000, 1: 13000}[day]
    return day_start + 0.1 * (ts // 100)


def load(day: int, product_symbol: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    prices = pd.read_csv(DATA / f"prices_round_2_day_{day}.csv", sep=";")
    trades = pd.read_csv(DATA / f"trades_round_2_day_{day}.csv", sep=";")
    prices = prices[prices["product"] == product_symbol].copy()
    trades = trades[trades["symbol"] == product_symbol].copy()
    return prices, trades


def wall_mid(row: pd.Series) -> float | None:
    bids = [row[f"bid_price_{i}"] for i in (3, 2, 1)]
    asks = [row[f"ask_price_{i}"] for i in (3, 2, 1)]
    bid = next((b for b in bids if pd.notna(b)), None)
    ask = next((a for a in asks if pd.notna(a)), None)
    if bid is None or ask is None:
        return None
    return (bid + ask) / 2.0


def inner_mid(row: pd.Series) -> float | None:
    bid = row.get("bid_price_1")
    ask = row.get("ask_price_1")
    if pd.isna(bid) or pd.isna(ask):
        return None
    return (bid + ask) / 2.0


def classify_aggressive(prices: pd.DataFrame, floor_fv: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return boolean masks for (agg_bid, agg_ask).

    agg_bid: any bid level has price >= floor(FV) — bid crossing above fair.
    agg_ask: any ask level has price <= floor(FV) — ask crossing below fair.
    """
    n = len(prices)
    agg_bid = np.zeros(n, dtype=bool)
    agg_ask = np.zeros(n, dtype=bool)
    for i in (1, 2, 3):
        bp = prices[f"bid_price_{i}"].values
        ap = prices[f"ask_price_{i}"].values
        agg_bid |= (~pd.isna(bp)) & (bp >= floor_fv)
        agg_ask |= (~pd.isna(ap)) & (ap <= floor_fv)
    return agg_bid, agg_ask


def build_figure(product: str, day: int, start: int, end: int) -> go.Figure:
    symbol = PRODUCTS[product]
    prices, trades = load(day, symbol)
    prices = prices[(prices["timestamp"] >= start) & (prices["timestamp"] <= end)].copy()
    trades = trades[(trades["timestamp"] >= start) & (trades["timestamp"] <= end)].copy()
    if len(prices) == 0:
        raise RuntimeError("no rows in window")

    prices["wall_mid"] = prices.apply(wall_mid, axis=1)
    prices["inner_mid"] = prices.apply(inner_mid, axis=1)
    prices["ref_fv"] = fv_of(product, day, prices["timestamp"].values)
    prices["floor_fv"] = np.floor(prices["ref_fv"]).astype(int)
    floor_fv = prices["floor_fv"].values
    agg_bid_mask, agg_ask_mask = classify_aggressive(prices, floor_fv)
    prices["is_agg_bid"] = agg_bid_mask
    prices["is_agg_ask"] = agg_ask_mask

    fig = go.Figure()

    # Book levels
    bid_colors = ["#2ca02c", "#66c266", "#b3e0b3"]
    ask_colors = ["#d62728", "#e86163", "#f1b2b2"]
    for i, color in zip((1, 2, 3), bid_colors):
        mask = prices[f"bid_price_{i}"].notna()
        if not mask.any():
            continue
        custom = np.column_stack([
            prices.loc[mask, f"bid_volume_{i}"].astype(int).values,
            (prices.loc[mask, f"bid_price_{i}"].values - prices.loc[mask, "floor_fv"].values).astype(int),
        ])
        fig.add_trace(go.Scattergl(
            x=prices.loc[mask, "timestamp"],
            y=prices.loc[mask, f"bid_price_{i}"],
            mode="markers",
            name=f"bid L{i}",
            marker=dict(color=color, size=4, symbol="circle"),
            customdata=custom,
            hovertemplate=f"bid L{i}<br>ts=%{{x}}<br>px=%{{y}}<br>vol=%{{customdata[0]}}<br>offset=%{{customdata[1]}}<extra></extra>",
        ))

    for i, color in zip((1, 2, 3), ask_colors):
        mask = prices[f"ask_price_{i}"].notna()
        if not mask.any():
            continue
        custom = np.column_stack([
            prices.loc[mask, f"ask_volume_{i}"].astype(int).values,
            (prices.loc[mask, f"ask_price_{i}"].values - prices.loc[mask, "floor_fv"].values).astype(int),
        ])
        fig.add_trace(go.Scattergl(
            x=prices.loc[mask, "timestamp"],
            y=prices.loc[mask, f"ask_price_{i}"],
            mode="markers",
            name=f"ask L{i}",
            marker=dict(color=color, size=4, symbol="circle"),
            customdata=custom,
            hovertemplate=f"ask L{i}<br>ts=%{{x}}<br>px=%{{y}}<br>vol=%{{customdata[0]}}<br>offset=%{{customdata[1]}}<extra></extra>",
        ))

    # Mid & wall mid
    fig.add_trace(go.Scattergl(
        x=prices["timestamp"], y=prices["inner_mid"],
        mode="lines", name="inner mid",
        line=dict(color="black", width=1, dash="dash"),
    ))
    fig.add_trace(go.Scattergl(
        x=prices["timestamp"], y=prices["wall_mid"],
        mode="lines", name="wall mid",
        line=dict(color="gray", width=1, dash="dot"),
    ))
    fig.add_trace(go.Scattergl(
        x=prices["timestamp"], y=prices["ref_fv"],
        mode="lines", name="ref FV (model)",
        line=dict(color="blue", width=1.2, dash="longdash"),
    ))

    # Aggressive-event markers — large yellow circle on the aggressive quote
    # For agg_bid: put marker at bid_price_1 (if it's the one crossing) or at floor_fv+3 as anchor
    agg_bid_rows = prices[prices["is_agg_bid"]]
    if len(agg_bid_rows) > 0:
        # Find the max bid price on that row (the crossing one)
        def max_bid(r):
            bs = [r[f"bid_price_{k}"] for k in (1, 2, 3)]
            return max([b for b in bs if pd.notna(b)], default=None)
        y = agg_bid_rows.apply(max_bid, axis=1)
        fig.add_trace(go.Scattergl(
            x=agg_bid_rows["timestamp"], y=y,
            mode="markers", name="agg_bid event",
            marker=dict(color="gold", size=12, symbol="triangle-up",
                        line=dict(color="black", width=1)),
            hovertemplate="AGG BID<br>ts=%{x}<br>px=%{y}<extra></extra>",
        ))

    agg_ask_rows = prices[prices["is_agg_ask"]]
    if len(agg_ask_rows) > 0:
        def min_ask(r):
            ans = [r[f"ask_price_{k}"] for k in (1, 2, 3)]
            return min([a for a in ans if pd.notna(a)], default=None)
        y = agg_ask_rows.apply(min_ask, axis=1)
        fig.add_trace(go.Scattergl(
            x=agg_ask_rows["timestamp"], y=y,
            mode="markers", name="agg_ask event",
            marker=dict(color="magenta", size=12, symbol="triangle-down",
                        line=dict(color="black", width=1)),
            hovertemplate="AGG ASK<br>ts=%{x}<br>px=%{y}<extra></extra>",
        ))

    # Trades
    if not trades.empty:
        fig.add_trace(go.Scattergl(
            x=trades["timestamp"], y=trades["price"],
            mode="markers", name="trade",
            marker=dict(color="purple", size=np.clip(trades["quantity"], 3, 18).astype(int),
                        symbol="x", line=dict(width=1)),
            customdata=trades["quantity"],
            hovertemplate="trade<br>ts=%{x}<br>px=%{y}<br>qty=%{customdata}<extra></extra>",
        ))

    fig.update_layout(
        title=f"{product} ({symbol}) day {day} — ticks {start}..{end}  |  agg_bid={int(agg_bid_mask.sum())}  agg_ask={int(agg_ask_mask.sum())}",
        xaxis_title="timestamp",
        yaxis_title="price",
        hovermode="closest",
        template="plotly_white",
        height=720,
        legend=dict(orientation="v", x=1.02, y=1),
    )
    return fig


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--day", type=int, default=0, choices=[-1, 0, 1])
    ap.add_argument("--product", default="BOTH", choices=["OSM", "PEP", "BOTH"])
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--end", type=int, default=10_000_000)
    args = ap.parse_args()

    products = ["OSM", "PEP"] if args.product == "BOTH" else [args.product]
    for product in products:
        fig = build_figure(product, args.day, args.start, args.end)
        out = OUT / f"viz_{product}_day{args.day}_{args.start}_{args.end}.html"
        fig.write_html(out, include_plotlyjs="cdn")
        print(f"wrote {out}")


if __name__ == "__main__":
    main()
