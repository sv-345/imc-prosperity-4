#!/usr/bin/env python3
"""Out-of-sample replay harness for Round 2 strategies.

Walks a Round 2 day tick by tick, calling ``Trader.run(state)`` with the same
``TradingState`` shape the Rust Monte Carlo simulator uses, and applies the
``prosperity3bt`` historical-replay fill rules (cross against the visible
book; resting orders stay; no synthetic bot takers — market-trades come from
the real ``trades_round_2_day_*.csv``). Emits a per-tick PnL JSON bundle that
``report.py`` consumes.

Usage
-----
    python3 scripts/validator/replay.py <trader.py> <day> [--out PATH]

``day`` is the Prosperity day index (-1, 0, or 1). ``trader.py`` must expose a
``Trader`` class with a ``run(state)`` method, exactly like the IMC server
requires.

The harness aliases ``datamodel`` to ``prosperity3bt.datamodel`` before
loading the trader, so both ``from datamodel import ...`` (server-style) and
``from prosperity3bt.datamodel import ...`` (local-style) work unchanged.

The replay logic itself is the upstream ``prosperity3bt.runner.run_backtest``
— we do not fork or monkey-patch it. The main agent depends on
``prosperity3bt`` staying untouched.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from importlib import import_module
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKTESTER_SRC = REPO_ROOT / "backtester"
DATA_ROOT = REPO_ROOT / "data"

# Put backtester first so ``prosperity3bt`` resolves to the repo's vendored copy
# rather than any globally-installed one.
if str(BACKTESTER_SRC) not in sys.path:
    sys.path.insert(0, str(BACKTESTER_SRC))

from prosperity3bt.file_reader import FileSystemReader  # noqa: E402
from prosperity3bt.models import TradeMatchingMode  # noqa: E402
from prosperity3bt.runner import run_backtest  # noqa: E402


def load_trader(trader_path: Path) -> Any:
    """Import a trader module by file path, handling both import styles.

    Server submissions use ``from datamodel import ...`` because the live
    sandbox exposes the module as top-level. Local files typically use
    ``from prosperity3bt.datamodel import ...``. We alias the former to the
    latter before import so both work.
    """
    import prosperity3bt.datamodel as _dm

    sys.modules.setdefault("datamodel", _dm)

    trader_path = trader_path.resolve()
    if not trader_path.is_file():
        raise FileNotFoundError(f"Trader file not found: {trader_path}")

    parent = str(trader_path.parent)
    if parent not in sys.path:
        sys.path.insert(0, parent)

    module = import_module(trader_path.stem)
    if not hasattr(module, "Trader"):
        raise AttributeError(f"{trader_path} does not expose a Trader class")
    return module


def extract_per_tick_pnl(result: Any) -> dict[str, Any]:
    """Compute robust per-tick and cumulative MTM PnL from the replay output.

    The activity log's ``profit_and_loss`` column is ``cash + position ×
    row.mid_price``, where ``row.mid_price`` comes straight from the CSV.
    Real Prosperity CSVs occasionally contain ticks with an empty book and
    ``mid_price=0.0`` (~0.15% of Round 2 ticks). Diffing the column against
    those rows produces per-tick MTM swings of hundreds of thousands of
    seashells — which is an artifact of the bad mid, not the strategy.

    We reconstruct cash and position ourselves from ``result.trades`` and
    mark to market using a forward-filled mid, so per-tick PnL reflects
    genuine economic change. Cumulative totals match the upstream column up
    to those empty-book-mid artifacts, which net out at day end.
    """
    # Per-product, per-timestamp sanitized mid (forward-fill zeros).
    mid_by_ts: dict[int, dict[str, float]] = defaultdict(dict)
    products_seen: set[str] = set()
    for row in result.activity_logs:
        cols = row.columns
        ts = int(cols[1])
        product = str(cols[2])
        mid = float(cols[-2])  # second-to-last column is mid_price
        mid_by_ts[ts][product] = mid
        products_seen.add(product)

    products = sorted(products_seen)
    timestamps = sorted(mid_by_ts.keys())

    last_good_mid: dict[str, float] = {p: 0.0 for p in products}
    sanitized_mid: dict[int, dict[str, float]] = {}
    for ts in timestamps:
        sanitized_mid[ts] = {}
        for p in products:
            raw = mid_by_ts[ts].get(p, 0.0)
            if raw != 0.0:
                last_good_mid[p] = raw
            sanitized_mid[ts][p] = last_good_mid[p]

    # Bucket SUBMISSION trades by tick and product.
    trades_by_ts: dict[int, list[Any]] = defaultdict(list)
    for trade_row in result.trades:
        t = trade_row.trade
        if t.buyer == "SUBMISSION" or t.seller == "SUBMISSION":
            trades_by_ts[t.timestamp].append(t)

    cash = {p: 0.0 for p in products}
    position = {p: 0 for p in products}
    prev_cum = {p: 0.0 for p in products}
    per_tick: list[dict[str, Any]] = []

    for ts in timestamps:
        # Apply this tick's own trades before marking to market.
        for t in trades_by_ts.get(ts, ()):
            if t.buyer == "SUBMISSION":
                cash[t.symbol] -= t.price * t.quantity
                position[t.symbol] = position.get(t.symbol, 0) + t.quantity
            if t.seller == "SUBMISSION":
                cash[t.symbol] += t.price * t.quantity
                position[t.symbol] = position.get(t.symbol, 0) - t.quantity

        row_out: dict[str, Any] = {"timestamp": ts}
        tick_total = 0.0
        for p in products:
            cum = cash[p] + position[p] * sanitized_mid[ts][p]
            delta = cum - prev_cum[p]
            row_out[p] = delta
            tick_total += delta
            prev_cum[p] = cum
        row_out["total"] = tick_total
        per_tick.append(row_out)

    totals = {p: prev_cum[p] for p in products}
    return {
        "timestamps": timestamps,
        "products": products,
        "per_tick": per_tick,
        "totals": {**totals, "total": sum(totals.values())},
        "final_positions": dict(position),
    }


def run(trader_path: Path, day: int, out: Path | None) -> dict[str, Any]:
    trader_module = load_trader(trader_path)
    trader = trader_module.Trader()

    file_reader = FileSystemReader(DATA_ROOT)
    result = run_backtest(
        trader=trader,
        file_reader=file_reader,
        round_num=2,
        day_num=day,
        print_output=False,
        trade_matching_mode=TradeMatchingMode.all,
        no_names=True,
        show_progress_bar=False,
    )

    pnl = extract_per_tick_pnl(result)
    bundle: dict[str, Any] = {
        "trader": trader_path.name,
        "trader_path": str(trader_path.resolve().relative_to(REPO_ROOT))
        if trader_path.resolve().is_relative_to(REPO_ROOT)
        else str(trader_path.resolve()),
        "round": 2,
        "day": day,
        "ticks": len(pnl["timestamps"]),
        "products": pnl["products"],
        "totals": pnl["totals"],
        "final_positions": pnl.get("final_positions", {}),
        "per_tick": pnl["per_tick"],
        "n_trades": len(result.trades),
        "n_own_trades": sum(
            1
            for t_row in result.trades
            if t_row.trade.buyer == "SUBMISSION" or t_row.trade.seller == "SUBMISSION"
        ),
    }

    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(bundle))
    return bundle


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Replay a Round 2 trader against a single day's historical CSVs.",
    )
    parser.add_argument("trader", type=Path, help="Path to a Python file exposing a Trader class.")
    parser.add_argument("day", type=int, help="Prosperity day index (-1, 0, or 1 for Round 2).")
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Where to write the replay JSON. Defaults to "
        "tmp/validator/<trader_stem>_day<N>.json under repo root.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    out = args.out
    if out is None:
        out = REPO_ROOT / "tmp" / "validator" / f"{args.trader.stem}_day{args.day}.json"

    bundle = run(args.trader, args.day, out)
    totals = bundle["totals"]
    print(
        f"{args.trader.name} day={args.day} ticks={bundle['ticks']} "
        f"total_pnl={totals['total']:+,.2f} "
        f"({', '.join(f'{p}={totals[p]:+,.0f}' for p in bundle['products'])}) "
        f"-> {out}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
