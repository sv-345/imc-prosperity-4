#!/usr/bin/env python3
"""One-shot validator: replay a trader on all Round 2 days and render the report.

Equivalent to running ``replay.py`` three times (days -1, 0, +1) and then
``report.py`` on the resulting JSONs. Intended as the single command the main
agent uses when iterating on strategies.

Usage
-----
    python3 scripts/validator/validate.py iter6_trader.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

import replay  # type: ignore  # noqa: E402
import report  # type: ignore  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Replay a trader on Round 2 days -1, 0, +1 and render a report.",
    )
    parser.add_argument("trader", type=Path, help="Path to trader .py exposing a Trader class")
    parser.add_argument(
        "--days",
        type=int,
        nargs="+",
        default=[-1, 0, 1],
        help="Days to replay (default: -1 0 1)",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="Directory for replay JSONs (default: tmp/validator/)",
    )
    parser.add_argument(
        "--overfit-threshold",
        type=float,
        default=report.OVERFIT_THRESHOLD_DEFAULT,
        help="Fractional deviation above which an OOS day is flagged (default 0.30)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    out_dir = args.out_dir or (REPO_ROOT / "tmp" / "validator")
    out_dir.mkdir(parents=True, exist_ok=True)

    bundles_paths: list[Path] = []
    for day in args.days:
        out_path = out_dir / f"{args.trader.stem}_day{day}.json"
        bundle = replay.run(args.trader, day, out_path)
        totals = bundle["totals"]
        print(
            f"day={day:>2}  ticks={bundle['ticks']}  "
            f"total={totals['total']:+,.2f}  "
            f"({', '.join(f'{p}={totals[p]:+,.0f}' for p in bundle['products'])})"
        )
        bundles_paths.append(out_path)

    loaded = [report.load_bundle(p) for p in bundles_paths]
    report_md = report.render(loaded, args.overfit_threshold)
    report_out = report.REPORT_DIR / f"{args.trader.stem}.md"
    report_out.parent.mkdir(parents=True, exist_ok=True)
    report_out.write_text(report_md)
    print(f"\nReport: {report_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
