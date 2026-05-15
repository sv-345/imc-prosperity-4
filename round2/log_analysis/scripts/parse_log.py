#!/usr/bin/env python3
"""Parse an IMC Prosperity server log (/tmp/prosperity_logs/<sub>/<run>.log)
and emit a JSON record of extracted metrics. See docs/round2_log_analysis/log_format.md
for the log format spec.

Usage:
    python3 parse_log.py <log_path>                  # JSON to stdout
    python3 parse_log.py <log_path> --out <path>     # JSON to file
    python3 parse_log.py --submission <sub_id>       # resolve log_path from sub_id

Every field is optional in the output: if a field can't be computed the
parser omits it rather than crashing. See `_parse_one` for field defs.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from statistics import mean
from typing import Any

LOGS_ROOT = "/tmp/prosperity_logs"
ADVERSE_MOVE_LOOKAHEAD_TICKS = 5          # N in the toxic-fill proxy
TICK_STEP = 100                            # server tick granularity
SANDBOX_LIMIT_RE = re.compile(
    r"Orders for product (\S+) exceeded limit of (\d+) set"
)
SANDBOX_ERROR_TOKENS = ("[ERROR]", '"errorType"', "Traceback")
# Strip volatile fields so duplicate errors dedup cleanly
REQUEST_ID_RE = re.compile(r'"requestId":\s*"[^"]+"')
MAX_ERRORS_RETAINED = 10                  # cap to avoid context bloat


def resolve_submission_log(submission_id: str) -> Path:
    """Given a submission_id (directory name), return the single .log file inside."""
    d = Path(LOGS_ROOT) / submission_id
    if not d.is_dir():
        raise FileNotFoundError(f"No directory at {d}")
    logs = sorted(d.glob("*.log"))
    if not logs:
        raise FileNotFoundError(f"No .log file in {d}")
    if len(logs) > 1:
        # Prefer the one matching the canonical run_id pattern (<digits>.log)
        numeric = [p for p in logs if p.stem.isdigit()]
        if numeric:
            return numeric[0]
    return logs[0]


def _safe_float(s: str) -> float | None:
    s = s.strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _safe_int(s: str) -> int | None:
    s = s.strip()
    if not s:
        return None
    try:
        return int(s)
    except ValueError:
        return None


@dataclass
class ActivitiesRow:
    day: int | None
    timestamp: int
    product: str
    mid_price: float | None
    pnl: float | None
    bid_1: float | None = None
    ask_1: float | None = None


def _parse_activities_log(text: str) -> list[ActivitiesRow]:
    rows: list[ActivitiesRow] = []
    if not text:
        return rows
    lines = [l for l in text.split("\n") if l.strip()]
    if len(lines) < 2:
        return rows
    header = [h.strip() for h in lines[0].split(";")]
    # Defensive: map column name → index
    try:
        idx = {name: i for i, name in enumerate(header)}
        ts_i = idx["timestamp"]
        prod_i = idx["product"]
        mid_i = idx["mid_price"]
        pnl_i = idx["profit_and_loss"]
        day_i = idx.get("day", -1)
        bid_i = idx.get("bid_price_1", -1)
        ask_i = idx.get("ask_price_1", -1)
    except KeyError:
        return rows
    for line in lines[1:]:
        parts = line.split(";")
        if len(parts) <= pnl_i:
            continue
        rows.append(
            ActivitiesRow(
                day=_safe_int(parts[day_i]) if day_i >= 0 else None,
                timestamp=_safe_int(parts[ts_i]) or 0,
                product=parts[prod_i],
                mid_price=_safe_float(parts[mid_i]),
                pnl=_safe_float(parts[pnl_i]),
                bid_1=_safe_float(parts[bid_i]) if bid_i >= 0 and bid_i < len(parts) else None,
                ask_1=_safe_float(parts[ask_i]) if ask_i >= 0 and ask_i < len(parts) else None,
            )
        )
    return rows


def _build_mid_lookup(rows: list[ActivitiesRow]) -> dict[str, dict[int, float]]:
    out: dict[str, dict[int, float]] = {}
    for r in rows:
        if r.mid_price is None:
            continue
        out.setdefault(r.product, {})[r.timestamp] = r.mid_price
    return out


def _last_pnl_per_product(rows: list[ActivitiesRow]) -> dict[str, float]:
    # Rows are in file order; scan forward and keep last-seen PnL per product
    last: dict[str, float] = {}
    for r in rows:
        if r.pnl is not None:
            last[r.product] = r.pnl
    return last


def _pnl_series(rows: list[ActivitiesRow]) -> dict[str, list[tuple[int, float]]]:
    out: dict[str, list[tuple[int, float]]] = {}
    for r in rows:
        if r.pnl is None:
            continue
        out.setdefault(r.product, []).append((r.timestamp, r.pnl))
    for v in out.values():
        v.sort(key=lambda x: x[0])
    return out


def _largest_single_tick_loss(series: list[tuple[int, float]]) -> float | None:
    """Most negative PnL delta between consecutive ticks. Returns a non-positive
    float, or None if fewer than 2 points."""
    if len(series) < 2:
        return None
    min_delta = 0.0
    for (_, a), (_, b) in zip(series, series[1:]):
        d = b - a
        if d < min_delta:
            min_delta = d
    return min_delta


def _side_of(trade: dict[str, Any]) -> str | None:
    if trade.get("buyer") == "SUBMISSION":
        return "buy"
    if trade.get("seller") == "SUBMISSION":
        return "sell"
    return None


def _adverse_move_after_fill(
    fills: list[dict[str, Any]],
    mids: dict[int, float],
    lookahead_ticks: int,
) -> tuple[float | None, int]:
    """Return (avg adverse move, count of fills used). Positive = toxic.
    Skips fills whose future mid is unknown (e.g., near end of session)."""
    moves: list[float] = []
    for t in fills:
        side = _side_of(t)
        if side is None:
            continue
        price = t.get("price")
        ts = t.get("timestamp")
        if price is None or ts is None:
            continue
        future_ts = ts + lookahead_ticks * TICK_STEP
        fut_mid = mids.get(future_ts)
        if fut_mid is None:
            continue
        if side == "buy":
            adverse = price - fut_mid       # positive = mid dropped after we bought
        else:
            adverse = fut_mid - price       # positive = mid rose after we sold
        moves.append(adverse)
    if not moves:
        return None, 0
    return mean(moves), len(moves)


def _parse_sandbox_logs(
    logs: list[dict[str, Any]],
    products: set[str],
) -> tuple[dict[str, int], list[dict[str, Any]]]:
    """Return (position_limit_hits_per_product, deduped_error_entries).

    Error entries are {"error": <normalized>, "count": <int>, "first_timestamp": <int>}.
    Dedup by normalized message (requestId stripped) so a per-tick error loop
    collapses to a single entry with a count.
    """
    hits: dict[str, int] = {p: 0 for p in products}
    error_counts: dict[str, int] = {}
    error_first_ts: dict[str, int] = {}
    for entry in logs:
        text = entry.get("sandboxLog", "") or ""
        if not text.strip():
            continue
        ts = entry.get("timestamp", -1)
        for line in text.split("\n"):
            s = line.strip()
            if not s:
                continue
            m = SANDBOX_LIMIT_RE.search(s)
            if m:
                product = m.group(1)
                hits[product] = hits.get(product, 0) + 1
                continue
            if any(tok in s for tok in SANDBOX_ERROR_TOKENS):
                norm = REQUEST_ID_RE.sub('"requestId": "..."', s)
                error_counts[norm] = error_counts.get(norm, 0) + 1
                if norm not in error_first_ts:
                    error_first_ts[norm] = ts
    # Sort by count desc, cap output
    sorted_errors = sorted(
        error_counts.items(), key=lambda x: (-x[1], x[0])
    )[:MAX_ERRORS_RETAINED]
    entries = [
        {"error": k, "count": v, "first_timestamp": error_first_ts[k]}
        for k, v in sorted_errors
    ]
    return hits, entries


def _parse_one(path: Path) -> dict[str, Any]:
    out: dict[str, Any] = {
        "submission_id": path.parent.name,
        "run_id": path.stem,
        "log_path": str(path),
    }
    # File mtime = upload time (best available proxy)
    try:
        out["timestamp"] = int(path.stat().st_mtime)
    except OSError:
        pass

    try:
        with open(path, "r") as f:
            raw = json.load(f)
    except Exception as e:
        out["any_errors"] = [f"parse_failure: {e!r}"]
        return out

    if isinstance(raw, dict):
        out["internal_submission_uuid"] = raw.get("submissionId")

    activities_text = raw.get("activitiesLog", "") if isinstance(raw, dict) else ""
    rows = _parse_activities_log(activities_text)
    trade_history = raw.get("tradeHistory", []) if isinstance(raw, dict) else []
    tick_logs = raw.get("logs", []) if isinstance(raw, dict) else []

    # Ticks from unique timestamps. Fallback to logs array length.
    ts_set = {r.timestamp for r in rows}
    total_ticks = len(ts_set) if ts_set else (len(tick_logs) if isinstance(tick_logs, list) else 0)
    if total_ticks:
        out["total_ticks"] = total_ticks

    # Discover products from the CSV (not hard-coded)
    products = sorted({r.product for r in rows})
    if products:
        out["products"] = products

    # Per-product PnL from last row
    last_pnl = _last_pnl_per_product(rows)
    if last_pnl:
        total_pnl = sum(last_pnl.values())
        out["total_pnl"] = total_pnl
        if total_ticks:
            out["per_tick_pnl"] = total_pnl / total_ticks

    # Mid-price lookup for adverse-move computation
    mids_by_product = _build_mid_lookup(rows)
    pnl_series = _pnl_series(rows)

    # Fills: partition trade history by product and by SUBMISSION participation
    fills_by_product: dict[str, list[dict[str, Any]]] = {}
    for t in trade_history if isinstance(trade_history, list) else []:
        if not isinstance(t, dict):
            continue
        if _side_of(t) is None:
            continue
        fills_by_product.setdefault(t.get("symbol", ""), []).append(t)

    # Sandbox log scan for position limit hits + errors
    sb_hits, errors = _parse_sandbox_logs(tick_logs if isinstance(tick_logs, list) else [], set(products))
    if errors:
        out["any_errors"] = errors

    per_product: dict[str, dict[str, Any]] = {}
    total_fills = 0
    for p in products:
        d: dict[str, Any] = {}
        if p in last_pnl:
            d["pnl"] = last_pnl[p]
            if total_ticks:
                d["per_tick_pnl"] = last_pnl[p] / total_ticks
        pf = fills_by_product.get(p, [])
        if pf:
            d["num_fills"] = len(pf)
            total_fills += len(pf)
            sizes = [t["quantity"] for t in pf if "quantity" in t]
            if sizes:
                d["avg_fill_size"] = mean(sizes)
            # Side split — useful for inventory-runaway detection
            buys = sum(1 for t in pf if _side_of(t) == "buy")
            sells = len(pf) - buys
            d["num_buys"] = buys
            d["num_sells"] = sells
            buy_qty = sum(t["quantity"] for t in pf if _side_of(t) == "buy" and "quantity" in t)
            sell_qty = sum(t["quantity"] for t in pf if _side_of(t) == "sell" and "quantity" in t)
            d["buy_qty"] = buy_qty
            d["sell_qty"] = sell_qty
            d["net_qty"] = buy_qty - sell_qty
        # Position limit hits
        d["position_limit_hits"] = sb_hits.get(p, 0)
        # Largest single-tick loss from PnL delta
        pl_min = _largest_single_tick_loss(pnl_series.get(p, []))
        if pl_min is not None:
            d["largest_single_tick_loss"] = pl_min
        # Adverse move after fill
        adv, adv_n = _adverse_move_after_fill(
            pf, mids_by_product.get(p, {}), ADVERSE_MOVE_LOOKAHEAD_TICKS
        )
        if adv is not None:
            d["largest_adverse_move_after_fill"] = adv
            d["adverse_move_lookahead_ticks"] = ADVERSE_MOVE_LOOKAHEAD_TICKS
            d["adverse_move_fills_used"] = adv_n
        per_product[p] = d

    if per_product:
        out["per_product"] = per_product

    if total_ticks:
        out["fill_rate"] = total_fills / total_ticks
    out["total_fills"] = total_fills

    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("log_path", nargs="?", help="Path to .log file")
    g.add_argument("--submission", help="Server submission_id (directory name)")
    ap.add_argument("--out", help="Write JSON to this file instead of stdout")
    ap.add_argument("--pretty", action="store_true", help="Pretty-print JSON")
    args = ap.parse_args()

    if args.submission:
        path = resolve_submission_log(args.submission)
    else:
        path = Path(args.log_path)
        if not path.exists():
            print(f"ERROR: {path} does not exist", file=sys.stderr)
            return 2

    record = _parse_one(path)
    text = json.dumps(record, indent=2 if args.pretty else None, sort_keys=True)
    if args.out:
        os.makedirs(os.path.dirname(args.out), exist_ok=True)
        with open(args.out, "w") as f:
            f.write(text)
            f.write("\n")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
