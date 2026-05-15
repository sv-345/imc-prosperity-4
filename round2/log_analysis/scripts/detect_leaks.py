#!/usr/bin/env python3
"""Detect leak patterns in a parsed Prosperity log and emit a ranked summary.

Patterns checked (see docs/round2_log_analysis/log_format.md for log format):
1. Inventory runaway — fills strongly one-sided, net_qty large at session end,
   or running max |position| near the limit.
2. Position limit hits — sandbox rejections; strategy is size-constrained.
3. Toxic-fill rate — adverse mid-move after our fills is positive (we got
   filled right before price moved against us).
4. Quoted-off-market — long runs with no fills; opportunity cost.

Each leak gets an estimated $ impact and the top 3 are written to
docs/round2_log_analysis/leaks/<submission_id>.md.

Usage:
    python3 detect_leaks.py <submission_id>
    python3 detect_leaks.py <submission_id> --stdout     # don't write file
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent
DOCS_DIR = REPO_ROOT / "docs" / "round2_log_analysis"
LEAKS_DIR = DOCS_DIR / "leaks"

sys.path.insert(0, str(SCRIPT_DIR))
from parse_log import (  # noqa: E402
    _parse_activities_log,
    _build_mid_lookup,
    _side_of,
    resolve_submission_log,
)
from compare_submissions import get_parsed  # noqa: E402

# Observed product position limit in sandbox messages ("limit of 80 set")
DEFAULT_POSITION_LIMIT = 80
TICK_STEP = 100
# Thresholds for flagging (tuned so only real leaks surface, not noise)
ONE_SIDED_RATIO_FLAG = 0.75     # >=75% of fills on one side
NET_QTY_FLAG = 50               # |final net| >= 50 units (>60% of limit)
MAX_POS_FRAC_FLAG = 0.90        # running |position| touched >=90% of limit
POS_LIMIT_HITS_FLAG = 10        # total breach messages
TOXIC_MOVE_FLAG = 0.5           # avg adverse move in price units ($)
LONG_RUN_TICKS_FLAG = 200       # 200 ticks = 20k server-time with no fills
MIN_IMPACT_TO_REPORT = 50.0     # drop leaks estimated < $50 to cut noise


@dataclass
class Leak:
    kind: str                   # short machine-readable key
    product: str                # or "ALL"
    headline: str               # one-line human summary
    estimated_dollar_impact: float
    evidence: dict[str, Any]


def _running_positions(
    trade_history: list[dict[str, Any]],
    products: list[str],
) -> dict[str, tuple[int, int, int]]:
    """Return {product: (max_long, max_short_abs, final_net)} from a running
    position tally that only counts SUBMISSION fills."""
    pos: dict[str, int] = {p: 0 for p in products}
    max_long: dict[str, int] = {p: 0 for p in products}
    max_short: dict[str, int] = {p: 0 for p in products}
    for t in sorted(
        [t for t in trade_history if _side_of(t) is not None],
        key=lambda t: t.get("timestamp", 0),
    ):
        p = t.get("symbol", "")
        if p not in pos:
            continue
        q = int(t.get("quantity", 0) or 0)
        if _side_of(t) == "buy":
            pos[p] += q
        else:
            pos[p] -= q
        if pos[p] > max_long[p]:
            max_long[p] = pos[p]
        if -pos[p] > max_short[p]:
            max_short[p] = -pos[p]
    return {p: (max_long[p], max_short[p], pos[p]) for p in products}


def _longest_fill_gap_ticks(
    trade_history: list[dict[str, Any]],
    total_ticks: int,
    product: str,
) -> tuple[int, int]:
    """Longest gap (in server ticks at step 100) between consecutive SUBMISSION
    fills on this product. Also returns the start timestamp of that gap."""
    our_ts = sorted(
        t["timestamp"]
        for t in trade_history
        if _side_of(t) is not None and t.get("symbol") == product and "timestamp" in t
    )
    if not our_ts:
        return total_ticks, 0
    # Consider gap before first and after last as well
    prev = 0
    worst = 0
    worst_start = 0
    for ts in our_ts:
        gap = (ts - prev) // TICK_STEP
        if gap > worst:
            worst = gap
            worst_start = prev
        prev = ts
    end = total_ticks * TICK_STEP
    tail_gap = (end - prev) // TICK_STEP
    if tail_gap > worst:
        worst = tail_gap
        worst_start = prev
    return worst, worst_start


def _estimate_inventory_runaway_cost(
    product: str,
    net_qty: int,
    max_abs_pos: int,
    mid_at_end: float | None,
    mid_start: float | None,
) -> float:
    """Rough $ impact of ending with net_qty units of carry.

    We value it as |net_qty| × (half the max observed mid move over the
    session) — a conservative proxy for one-way adverse move against that
    inventory. If mids missing, fall back to |net_qty| × 5 (five ticks).
    """
    if mid_at_end is not None and mid_start is not None:
        move = abs(mid_at_end - mid_start)
    else:
        move = 5.0
    return abs(net_qty) * max(1.0, move / 2.0)


def _estimate_position_limit_cost(
    hits: int,
    avg_pnl_per_fill: float | None,
) -> float:
    """Each hit = one side's orders rejected in one tick. Assume ~10% of
    rejected ticks would have become a fill worth avg_pnl_per_fill."""
    pnl = avg_pnl_per_fill if (avg_pnl_per_fill and avg_pnl_per_fill > 0) else 1.0
    return hits * 0.1 * pnl


def _estimate_toxic_cost(
    adverse_per_fill: float,
    num_fills: int,
    avg_size: float | None,
) -> float:
    size = avg_size if avg_size else 5.0
    # adverse is in price units ≈ ticks. $/fill ≈ adverse × size.
    return max(0.0, adverse_per_fill) * num_fills * size


def _estimate_idle_cost(
    gap_ticks: int,
    per_tick_pnl_product: float | None,
) -> float:
    rate = per_tick_pnl_product if (per_tick_pnl_product and per_tick_pnl_product > 0) else 0.0
    return gap_ticks * rate


def detect_leaks(parsed: dict[str, Any], log_path: Path) -> list[Leak]:
    leaks: list[Leak] = []
    products = parsed.get("products", [])
    total_ticks = parsed.get("total_ticks", 1000) or 1000

    # Reload raw log to get trade history & mids (not duplicated in parsed)
    try:
        raw = json.loads(log_path.read_text())
    except Exception:
        raw = {}
    trade_history = raw.get("tradeHistory", []) or []
    rows = _parse_activities_log(raw.get("activitiesLog", ""))
    mids = _build_mid_lookup(rows)

    pos_stats = _running_positions(trade_history, products)

    per_product = parsed.get("per_product", {}) or {}
    for product in products:
        pp = per_product.get(product, {}) or {}
        num_fills = pp.get("num_fills", 0) or 0
        avg_size = pp.get("avg_fill_size")
        buy_q = pp.get("buy_qty", 0) or 0
        sell_q = pp.get("sell_qty", 0) or 0
        net_qty = pp.get("net_qty", 0) or 0
        max_long, max_short, final_net = pos_stats.get(product, (0, 0, 0))
        max_abs_pos = max(max_long, max_short)
        per_tick_pnl = pp.get("per_tick_pnl")
        pnl = pp.get("pnl") or 0.0
        avg_pnl_per_fill = (pnl / num_fills) if num_fills else None

        # 1. Inventory runaway
        total_q = buy_q + sell_q
        one_side_ratio = 0.0
        if total_q:
            one_side_ratio = max(buy_q, sell_q) / total_q
        mid_start = None
        mid_end = None
        m = mids.get(product, {})
        if m:
            ts_sorted = sorted(m.keys())
            mid_start = m[ts_sorted[0]]
            mid_end = m[ts_sorted[-1]]

        flag_inv = (
            one_side_ratio >= ONE_SIDED_RATIO_FLAG and num_fills >= 10
        ) or abs(net_qty) >= NET_QTY_FLAG or max_abs_pos >= int(
            DEFAULT_POSITION_LIMIT * MAX_POS_FRAC_FLAG
        )
        if flag_inv:
            cost = _estimate_inventory_runaway_cost(
                product, net_qty, max_abs_pos, mid_end, mid_start
            )
            leaks.append(
                Leak(
                    kind="inventory_runaway",
                    product=product,
                    headline=(
                        f"{product}: one-sided fills "
                        f"({buy_q}B / {sell_q}S = {one_side_ratio:.0%} on one side), "
                        f"max |position| reached {max_abs_pos} (limit {DEFAULT_POSITION_LIMIT}), "
                        f"final net = {final_net}"
                    ),
                    estimated_dollar_impact=cost,
                    evidence={
                        "buy_qty": buy_q,
                        "sell_qty": sell_q,
                        "one_side_ratio": round(one_side_ratio, 3),
                        "max_long": max_long,
                        "max_short": max_short,
                        "final_net": final_net,
                        "position_limit_assumed": DEFAULT_POSITION_LIMIT,
                    },
                )
            )

        # 2. Position limit hits
        hits = pp.get("position_limit_hits", 0) or 0
        if hits >= POS_LIMIT_HITS_FLAG:
            cost = _estimate_position_limit_cost(hits, avg_pnl_per_fill)
            leaks.append(
                Leak(
                    kind="position_limit_hits",
                    product=product,
                    headline=(
                        f"{product}: {hits} ticks where orders exceeded the "
                        f"{DEFAULT_POSITION_LIMIT}-unit position limit "
                        f"(strategy is size-constrained on {hits/total_ticks:.0%} of ticks)"
                    ),
                    estimated_dollar_impact=cost,
                    evidence={
                        "hits": hits,
                        "hits_pct_of_ticks": round(hits / total_ticks, 3),
                        "avg_pnl_per_fill_reference": avg_pnl_per_fill,
                    },
                )
            )

        # 3. Toxic fills
        adv = pp.get("largest_adverse_move_after_fill")
        if adv is not None and adv >= TOXIC_MOVE_FLAG and num_fills >= 10:
            cost = _estimate_toxic_cost(adv, num_fills, avg_size)
            leaks.append(
                Leak(
                    kind="toxic_fills",
                    product=product,
                    headline=(
                        f"{product}: avg mid moves {adv:+.2f} ticks against us in the "
                        f"{pp.get('adverse_move_lookahead_ticks', 5)} ticks after each fill "
                        f"({num_fills} fills sampled) — adverse selection"
                    ),
                    estimated_dollar_impact=cost,
                    evidence={
                        "adverse_move_per_fill": adv,
                        "num_fills": num_fills,
                        "lookahead_ticks": pp.get("adverse_move_lookahead_ticks", 5),
                    },
                )
            )

        # 4. Long idle run
        gap, gap_start = _longest_fill_gap_ticks(trade_history, total_ticks, product)
        if gap >= LONG_RUN_TICKS_FLAG:
            cost = _estimate_idle_cost(gap, per_tick_pnl)
            leaks.append(
                Leak(
                    kind="long_idle_run",
                    product=product,
                    headline=(
                        f"{product}: {gap}-tick ({gap*TICK_STEP} server-time) run with no fills starting t={gap_start} — "
                        f"likely quoting off-market"
                    ),
                    estimated_dollar_impact=cost,
                    evidence={"gap_ticks": gap, "gap_start_timestamp": gap_start},
                )
            )

    # Session-level: runtime errors
    errors = parsed.get("any_errors") or []
    if errors:
        total_error_ticks = sum(e.get("count", 1) for e in errors)
        # Estimate cost as ticks where strategy crashed × expected per-tick PnL on a healthy submission
        healthy_pt = parsed.get("per_tick_pnl") or 0
        # If errors knocked out a fraction of ticks, we lost proportional PnL
        cost = total_error_ticks * max(0.0, 3.0 - healthy_pt)  # 3 $/tick baseline
        leaks.append(
            Leak(
                kind="runtime_errors",
                product="ALL",
                headline=(
                    f"Runtime errors on {total_error_ticks} ticks "
                    f"({len(errors)} unique error types) — strategy crashed within tick handler"
                ),
                estimated_dollar_impact=cost,
                evidence={
                    "total_error_ticks": total_error_ticks,
                    "unique_error_types": len(errors),
                    "first_error_timestamp": errors[0].get("first_timestamp"),
                },
            )
        )

    leaks = [l for l in leaks if l.estimated_dollar_impact >= MIN_IMPACT_TO_REPORT]
    leaks.sort(key=lambda l: l.estimated_dollar_impact, reverse=True)
    return leaks


def render_leaks_md(parsed: dict[str, Any], leaks: list[Leak]) -> str:
    sub = parsed.get("submission_id", "?")
    run = parsed.get("run_id", "?")
    total_pnl = parsed.get("total_pnl", 0) or 0
    per_tick = parsed.get("per_tick_pnl", 0) or 0
    total_fills = parsed.get("total_fills", 0) or 0
    fill_rate = parsed.get("fill_rate", 0) or 0
    lines = [
        f"# Leak report — submission {sub} (run {run})",
        "",
        f"- **Total PnL:** ${total_pnl:,.2f} ({per_tick:.3f} $/tick)",
        f"- **Fills:** {total_fills} ({fill_rate:.1%} fill rate)",
        f"- **Total leaks flagged:** {len(leaks)}",
        "",
    ]
    if not leaks:
        lines.append("_No leaks flagged above current thresholds._")
        lines.append("")
        lines.append(
            "Thresholds: one-sided fills ≥{:.0%}, |net_qty| ≥{}, max |pos| ≥{} "
            "of limit, position-limit hits ≥{}, adverse move ≥{:.2f}, idle run ≥{} ticks.".format(
                ONE_SIDED_RATIO_FLAG,
                NET_QTY_FLAG,
                MAX_POS_FRAC_FLAG,
                POS_LIMIT_HITS_FLAG,
                TOXIC_MOVE_FLAG,
                LONG_RUN_TICKS_FLAG,
            )
        )
        return "\n".join(lines) + "\n"

    top3 = leaks[:3]
    lines.append("## Top 3 leaks by estimated $ impact")
    lines.append("")
    lines.append("| Rank | Kind | Product | Est. $ lost | Headline |")
    lines.append("|---|---|---|---|---|")
    for i, l in enumerate(top3, 1):
        lines.append(
            f"| {i} | `{l.kind}` | {l.product} | ${l.estimated_dollar_impact:,.2f} | {l.headline} |"
        )
    lines.append("")
    for i, l in enumerate(top3, 1):
        lines.append(f"### {i}. {l.kind} — {l.product}")
        lines.append("")
        lines.append(f"_{l.headline}_")
        lines.append("")
        lines.append(f"**Estimated $ impact:** ${l.estimated_dollar_impact:,.2f}")
        lines.append("")
        lines.append("Evidence:")
        lines.append("")
        lines.append("```json")
        lines.append(json.dumps(l.evidence, indent=2, sort_keys=True))
        lines.append("```")
        lines.append("")
    if len(leaks) > 3:
        lines.append(f"## Other leaks ({len(leaks)-3})")
        lines.append("")
        for l in leaks[3:]:
            lines.append(
                f"- **{l.kind}** ({l.product}) — "
                f"est. ${l.estimated_dollar_impact:,.2f}: {l.headline}"
            )
        lines.append("")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("submission_id", help="Server submission_id (directory name)")
    ap.add_argument("--stdout", action="store_true", help="print md to stdout only")
    ap.add_argument("--refresh", action="store_true", help="re-parse the log")
    args = ap.parse_args()

    parsed = get_parsed(args.submission_id, refresh=args.refresh)
    if parsed is None:
        print(f"ERROR: no log for submission {args.submission_id}", file=sys.stderr)
        return 2
    log_path = resolve_submission_log(args.submission_id)
    leaks = detect_leaks(parsed, log_path)
    md = render_leaks_md(parsed, leaks)
    if args.stdout:
        print(md)
    else:
        LEAKS_DIR.mkdir(parents=True, exist_ok=True)
        out = LEAKS_DIR / f"{args.submission_id}.md"
        out.write_text(md)
        print(f"wrote {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
