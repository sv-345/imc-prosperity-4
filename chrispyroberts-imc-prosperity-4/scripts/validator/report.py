#!/usr/bin/env python3
"""Render a multi-day out-of-sample validation report.

Reads one or more replay JSONs produced by ``replay.py``, aggregates per-day
and per-product statistics, and writes a markdown file to
``docs/round2_validation/<trader_stem>.md``. All replay JSONs must refer to
the same trader; runs covering different traders produce separate reports.

The verdict compares per-tick PnL rate on each supplied day against the same
rate on day 0 (the in-sample day). If any other day's per-tick rate differs
from day 0 by more than ``--overfit-threshold`` (default 30%) or is of the
opposite sign, the report flags an overfit signal.

Usage
-----
    python3 scripts/validator/report.py tmp/validator/iter6_trader_day-1.json \\
        tmp/validator/iter6_trader_day0.json \\
        tmp/validator/iter6_trader_day1.json
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
REPORT_DIR = REPO_ROOT / "docs" / "round2_validation"
OVERFIT_THRESHOLD_DEFAULT = 0.30


def load_bundle(path: Path) -> dict[str, Any]:
    bundle = json.loads(path.read_text())
    required = {"trader", "day", "ticks", "products", "totals", "per_tick"}
    missing = required - bundle.keys()
    if missing:
        raise ValueError(f"{path}: missing keys {sorted(missing)} — regenerate with replay.py")
    return bundle


def percentile(sorted_values: list[float], p: float) -> float:
    if not sorted_values:
        return float("nan")
    if p <= 0:
        return sorted_values[0]
    if p >= 100:
        return sorted_values[-1]
    # Linear interpolation between the two nearest ranks.
    k = (len(sorted_values) - 1) * (p / 100.0)
    lo = int(k)
    hi = min(lo + 1, len(sorted_values) - 1)
    frac = k - lo
    return sorted_values[lo] * (1 - frac) + sorted_values[hi] * frac


def day_stats(bundle: dict[str, Any]) -> dict[str, Any]:
    ticks = bundle["ticks"]
    per_tick = bundle["per_tick"]
    products = bundle["products"]

    total_series = [float(row["total"]) for row in per_tick]
    product_series = {p: [float(row.get(p, 0.0)) for row in per_tick] for p in products}

    total_sorted = sorted(total_series)
    product_totals = {p: float(bundle["totals"].get(p, 0.0)) for p in products}
    grand_total = float(bundle["totals"]["total"])

    largest_loss_idx = min(range(len(total_series)), key=lambda i: total_series[i]) if total_series else -1
    largest_loss = total_series[largest_loss_idx] if total_series else 0.0
    largest_loss_ts = per_tick[largest_loss_idx]["timestamp"] if total_series else None

    pos = sum(1 for v in total_series if v > 0)
    neg = sum(1 for v in total_series if v < 0)
    zero = sum(1 for v in total_series if v == 0)

    return {
        "day": bundle["day"],
        "ticks": ticks,
        "total_pnl": grand_total,
        "per_tick_rate": grand_total / ticks if ticks else 0.0,
        "product_pnl": product_totals,
        "product_per_tick_rate": {p: product_totals[p] / ticks if ticks else 0.0 for p in products},
        "p05": percentile(total_sorted, 5),
        "p50": percentile(total_sorted, 50),
        "p95": percentile(total_sorted, 95),
        "mean": statistics.fmean(total_series) if total_series else 0.0,
        "stdev": statistics.pstdev(total_series) if len(total_series) > 1 else 0.0,
        "largest_loss": largest_loss,
        "largest_loss_ts": largest_loss_ts,
        "pos_ticks": pos,
        "neg_ticks": neg,
        "zero_ticks": zero,
        "n_trades": bundle.get("n_trades", 0),
        "product_stdev": {
            p: statistics.pstdev(s) if len(s) > 1 else 0.0 for p, s in product_series.items()
        },
    }


def fmt_signed(x: float) -> str:
    return f"{x:+,.2f}"


def fmt_int(x: float) -> str:
    return f"{x:+,.0f}"


def verdict_line(baseline: dict[str, Any] | None, day: dict[str, Any], threshold: float) -> str:
    if baseline is None or baseline["day"] == day["day"]:
        return "baseline"
    base_rate = baseline["per_tick_rate"]
    day_rate = day["per_tick_rate"]
    if base_rate == 0:
        delta_pct = float("inf") if day_rate != 0 else 0.0
    else:
        delta_pct = (day_rate - base_rate) / abs(base_rate)
    sign_flip = (base_rate > 0 and day_rate < 0) or (base_rate < 0 and day_rate > 0)
    flag = abs(delta_pct) > threshold or sign_flip
    tag = "FLAG" if flag else "ok"
    sign_note = " (sign flip)" if sign_flip else ""
    return f"Δrate = {delta_pct:+.1%} vs day 0 → {tag}{sign_note}"


def render(bundles: list[dict[str, Any]], threshold: float) -> str:
    trader_name = bundles[0]["trader"]
    all_products = sorted({p for b in bundles for p in b["products"]})
    bundles_sorted = sorted(bundles, key=lambda b: b["day"])
    days = [day_stats(b) for b in bundles_sorted]
    by_day = {d["day"]: d for d in days}
    baseline = by_day.get(0)

    lines: list[str] = []
    lines.append(f"# Validation report — `{trader_name}`")
    lines.append("")
    trader_path = bundles[0].get("trader_path", trader_name)
    lines.append(f"Trader file: `{trader_path}`")
    lines.append("")
    lines.append("Generated by `scripts/validator/report.py`. Replay mechanics: ")
    lines.append(
        "`prosperity3bt.runner.run_backtest` with `TradeMatchingMode.all` "
        "against the Round 2 historical CSVs in `data/round2/`. Day 0 is the "
        "in-sample day (MC calibration + server scoring); days -1 and +1 are "
        "out-of-sample."
    )
    lines.append("")

    # ---------- per-day totals ----------
    lines.append("## Per-day totals")
    lines.append("")
    header = "| day | ticks | total PnL | $/tick | OSM | PEP | P05 | P50 | P95 | largest tick loss | +ticks | −ticks | verdict |"
    sep = "|----:|------:|----------:|-------:|-----:|-----:|-----:|-----:|-----:|-----------:|-------:|-------:|:--------|"
    lines.append(header)
    lines.append(sep)
    for d in days:
        osm = d["product_pnl"].get("ASH_COATED_OSMIUM", 0.0)
        pep = d["product_pnl"].get("INTARIAN_PEPPER_ROOT", 0.0)
        largest = d["largest_loss"]
        largest_ts = d["largest_loss_ts"]
        verdict = verdict_line(baseline, d, threshold)
        lines.append(
            f"| {d['day']} | {d['ticks']} | {fmt_signed(d['total_pnl'])} | "
            f"{d['per_tick_rate']:+.3f} | {fmt_int(osm)} | {fmt_int(pep)} | "
            f"{fmt_signed(d['p05'])} | {fmt_signed(d['p50'])} | {fmt_signed(d['p95'])} | "
            f"{fmt_signed(largest)} @ ts={largest_ts} | "
            f"{d['pos_ticks']} | {d['neg_ticks']} | {verdict} |"
        )
    lines.append("")

    # ---------- per-product per-day breakdown ----------
    lines.append("## Per-product breakdown")
    lines.append("")
    lines.append("| day | product | total PnL | $/tick | σ per tick |")
    lines.append("|----:|:--------|----------:|-------:|-----------:|")
    for d in days:
        for p in all_products:
            total = d["product_pnl"].get(p, 0.0)
            rate = d["product_per_tick_rate"].get(p, 0.0)
            sd = d["product_stdev"].get(p, 0.0)
            lines.append(f"| {d['day']} | {p} | {fmt_signed(total)} | {rate:+.3f} | {sd:,.2f} |")
    lines.append("")

    # ---------- per-tick distribution ----------
    lines.append("## Per-tick PnL distribution (total across products)")
    lines.append("")
    lines.append("| day | mean | σ | P05 | P50 | P95 | largest loss | max gain |")
    lines.append("|----:|-----:|----:|-----:|-----:|-----:|-----:|-----:|")
    for d, bundle in zip(days, bundles_sorted):
        series = [row["total"] for row in bundle["per_tick"]]
        max_gain = max(series) if series else 0.0
        lines.append(
            f"| {d['day']} | {fmt_signed(d['mean'])} | {d['stdev']:,.2f} | "
            f"{fmt_signed(d['p05'])} | {fmt_signed(d['p50'])} | {fmt_signed(d['p95'])} | "
            f"{fmt_signed(d['largest_loss'])} | {fmt_signed(max_gain)} |"
        )
    lines.append("")

    # ---------- verdict ----------
    lines.append("## Overfit verdict")
    lines.append("")
    if baseline is None:
        lines.append(
            "No day-0 replay supplied; cannot compute day-vs-day variation. "
            "Re-run with day 0 included."
        )
    else:
        base_rate = baseline["per_tick_rate"]
        flagged_days: list[tuple[int, float]] = []
        for d in days:
            if d["day"] == 0:
                continue
            if base_rate == 0:
                delta_pct = float("inf") if d["per_tick_rate"] != 0 else 0.0
            else:
                delta_pct = (d["per_tick_rate"] - base_rate) / abs(base_rate)
            sign_flip = (base_rate > 0 and d["per_tick_rate"] < 0) or (
                base_rate < 0 and d["per_tick_rate"] > 0
            )
            if abs(delta_pct) > threshold or sign_flip:
                flagged_days.append((d["day"], delta_pct))
        lines.append(
            f"Overfit threshold: per-tick rate on any OOS day may not deviate from day 0 "
            f"by more than ±{int(threshold * 100)}%, and must not flip sign."
        )
        lines.append("")
        if not flagged_days:
            lines.append("**PASS** — no OOS day exceeds the threshold. Day-to-day variation looks like noise, not overfit.")
        else:
            parts = ", ".join(f"day {d} (Δ={pct:+.1%})" for d, pct in flagged_days)
            lines.append(f"**FLAG** — OOS deviation exceeds threshold on: {parts}.")
            lines.append("")
            lines.append(
                "Read the per-product table above: a single product's rate flipping or "
                "collapsing across days points at a parameter that's tuned to the day-0 book "
                "sequence rather than the underlying market structure."
            )
    lines.append("")
    lines.append("---")
    lines.append(
        "Reproduce: "
        "`python3 scripts/validator/replay.py <trader>.py <day>` for each day, "
        "then `python3 scripts/validator/report.py tmp/validator/<trader>_day*.json`."
    )
    lines.append("")
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render a markdown validation report from one or more replay JSONs.",
    )
    parser.add_argument("bundles", type=Path, nargs="+", help="replay JSONs to aggregate")
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output markdown path. Defaults to docs/round2_validation/<trader_stem>.md.",
    )
    parser.add_argument(
        "--overfit-threshold",
        type=float,
        default=OVERFIT_THRESHOLD_DEFAULT,
        help="Fractional deviation beyond which an OOS day is flagged (default 0.30).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    bundles = [load_bundle(p) for p in args.bundles]
    traders = {b["trader"] for b in bundles}
    if len(traders) != 1:
        print(
            f"Error: replay JSONs cover multiple traders: {sorted(traders)}. "
            "Run report.py once per trader.",
            file=sys.stderr,
        )
        return 2

    trader_name = bundles[0]["trader"]
    out = args.out
    if out is None:
        stem = Path(trader_name).stem
        out = REPORT_DIR / f"{stem}.md"

    report = render(bundles, args.overfit_threshold)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report)
    print(f"Wrote {out} ({len(bundles)} day(s), trader={trader_name})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
