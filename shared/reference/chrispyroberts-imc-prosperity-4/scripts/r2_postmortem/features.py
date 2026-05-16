"""Feature analysis on R2 server activity logs.

For each of the 4 v82-family submission logs, compute per-tick features
and regress on next-tick / 10-tick / 50-tick mid move.

Features tested:
  - book imbalance: (bid_vol - ask_vol) / (bid_vol + ask_vol)
  - volume at touch (L1 volumes)
  - inner-mid deviation from calibrated fair
  - ΔMid over last N ticks (momentum)
  - Spread width
  - Bot-3 presence indicator
"""

from __future__ import annotations

import csv
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path

LOGS = {
    "296317": "/tmp/prosperity_logs/296317/305226.log",
    "296379": "/tmp/prosperity_logs/296379/305289.log",
    "296878": "/tmp/prosperity_logs/296878/305790.log",
    "297226": "/tmp/prosperity_logs/297226/306138.log",
}
OUT = Path("<repo>/chrispyroberts-imc-prosperity-4/docs/round2_postmortem/features.md")


def parse_log(path: str):
    log = json.load(open(path))
    rows = []
    for ln in log["activitiesLog"].strip().split("\n")[1:]:
        c = ln.split(";")
        if len(c) < 17:
            continue
        try:
            ts = int(c[1])
            prod = c[2]
            bp1 = int(c[3]) if c[3] else None
            bv1 = int(c[4]) if c[4] else 0
            bp2 = int(c[5]) if c[5] else None
            bv2 = int(c[6]) if c[6] else 0
            bp3 = int(c[7]) if c[7] else None
            bv3 = int(c[8]) if c[8] else 0
            ap1 = int(c[9]) if c[9] else None
            av1 = int(c[10]) if c[10] else 0
            ap2 = int(c[11]) if c[11] else None
            av2 = int(c[12]) if c[12] else 0
            ap3 = int(c[13]) if c[13] else None
            av3 = int(c[14]) if c[14] else 0
            mid = float(c[15])
            if mid <= 0 or bp1 is None or ap1 is None:
                continue
            rows.append({
                "ts": ts, "prod": prod, "bp1": bp1, "bv1": bv1,
                "bp2": bp2, "bv2": bv2, "bp3": bp3, "bv3": bv3,
                "ap1": ap1, "av1": av1, "ap2": ap2, "av2": av2,
                "ap3": ap3, "av3": av3, "mid": mid,
                "spread": ap1 - bp1,
                "total_bid_vol": bv1 + bv2 + bv3,
                "total_ask_vol": av1 + av2 + av3,
            })
        except ValueError:
            continue
    return rows


def simple_regress(xs: list[float], ys: list[float]) -> tuple[float, float, float]:
    """Return (slope, intercept, r2)."""
    n = len(xs)
    if n < 10:
        return 0.0, 0.0, 0.0
    mean_x = statistics.fmean(xs)
    mean_y = statistics.fmean(ys)
    var_x = sum((x - mean_x) ** 2 for x in xs)
    var_y = sum((y - mean_y) ** 2 for y in ys)
    cov = sum((xs[i] - mean_x) * (ys[i] - mean_y) for i in range(n))
    if var_x == 0 or var_y == 0:
        return 0.0, 0.0, 0.0
    slope = cov / var_x
    intercept = mean_y - slope * mean_x
    r2 = (cov * cov) / (var_x * var_y)
    return slope, intercept, r2


def analyze(rows_by_prod: dict):
    """For each product, compute features and regress on future mid move."""
    results = {}
    for prod, rows in rows_by_prod.items():
        rows.sort(key=lambda r: r["ts"])
        n = len(rows)
        # Build feature series
        ts_idx = {r["ts"]: i for i, r in enumerate(rows)}
        # Future mid lookups
        def future_mid(i, delta_ticks):
            target_ts = rows[i]["ts"] + delta_ticks * 100
            for j in range(i + 1, min(i + delta_ticks + 5, n)):
                if rows[j]["ts"] >= target_ts:
                    return rows[j]["mid"]
            return None

        # Features
        imbalance = []
        imb_total = []
        spread = []
        bot3_bid = []
        bot3_ask = []
        # Momentum features
        dmid_1 = []
        dmid_5 = []
        dmid_10 = []
        # Targets
        fwd_1 = []
        fwd_10 = []
        fwd_50 = []

        for i, r in enumerate(rows):
            # Top-of-book imbalance
            tbv = r["bv1"]
            tav = r["av1"]
            tot = tbv + tav
            imb = (tbv - tav) / tot if tot else 0.0
            imbalance.append(imb)
            # Total-depth imbalance
            bt = r["total_bid_vol"]
            at = r["total_ask_vol"]
            tt = bt + at
            imb_total.append((bt - at) / tt if tt else 0.0)
            spread.append(r["spread"])
            # Bot-3 flag: bid at top-of-book with unusually small vol (2-8) → bot-3
            bot3_bid.append(1 if 2 <= r["bv1"] <= 8 else 0)
            bot3_ask.append(1 if 2 <= r["av1"] <= 8 else 0)
            # Momentum: ΔMid over last 1, 5, 10 ticks
            prev_1 = rows[i - 1]["mid"] if i >= 1 else r["mid"]
            prev_5 = rows[i - 5]["mid"] if i >= 5 else r["mid"]
            prev_10 = rows[i - 10]["mid"] if i >= 10 else r["mid"]
            dmid_1.append(r["mid"] - prev_1)
            dmid_5.append(r["mid"] - prev_5)
            dmid_10.append(r["mid"] - prev_10)
            # Forward mid moves
            f1 = future_mid(i, 1)
            f10 = future_mid(i, 10)
            f50 = future_mid(i, 50)
            fwd_1.append((f1 - r["mid"]) if f1 is not None else None)
            fwd_10.append((f10 - r["mid"]) if f10 is not None else None)
            fwd_50.append((f50 - r["mid"]) if f50 is not None else None)

        # Filter nans for each regression
        def regr(x, y):
            xy = [(xi, yi) for xi, yi in zip(x, y) if yi is not None]
            if len(xy) < 30:
                return 0.0, 0.0, 0.0, 0
            xs = [a for a, _ in xy]
            ys = [b for _, b in xy]
            s, i0, r2 = simple_regress(xs, ys)
            return s, i0, r2, len(xy)

        res = {}
        for fname, feat in [
            ("top_imbalance", imbalance),
            ("total_imbalance", imb_total),
            ("spread", spread),
            ("bot3_bid", bot3_bid),
            ("bot3_ask", bot3_ask),
            ("mom_1", dmid_1),
            ("mom_5", dmid_5),
            ("mom_10", dmid_10),
        ]:
            for tname, tgt in [("fwd_1", fwd_1), ("fwd_10", fwd_10), ("fwd_50", fwd_50)]:
                key = f"{fname}->{tname}"
                s, i0, r2, n = regr(feat, tgt)
                res[key] = {"slope": s, "r2": r2, "n": n}

        # ACF of mid returns
        ret = dmid_1
        valid_ret = [r for r in ret if r == r]
        if len(valid_ret) > 10:
            lag1 = [(valid_ret[i], valid_ret[i-1]) for i in range(1, len(valid_ret))]
            xs = [x for _, x in lag1]
            ys = [y for y, _ in lag1]
            s, _, r2 = simple_regress(xs, ys)
            res["acf1_ret"] = {"slope": s, "r2": r2, "n": len(lag1)}

        # Stats on mid
        mids = [r["mid"] for r in rows]
        res["mid_mean"] = statistics.fmean(mids)
        res["mid_std"] = statistics.stdev(mids) if len(mids) > 1 else 0
        res["mid_first"] = mids[0]
        res["mid_last"] = mids[-1]
        res["n_ticks"] = n

        results[prod] = res
    return results


def main():
    lines = ["# Round 2 — Feature analysis on server data\n"]
    lines.append("Regression of per-tick features on forward mid moves. Data: 4 v82-family submission activity logs. Per-product per-submission.\n")
    lines.append("`slope` is the OLS coefficient. `R²` is the explained variance. Small R² values are expected — we're asking whether a single feature has any predictive power.\n")

    all_results = {}
    for sub, path in LOGS.items():
        rows = parse_log(path)
        by_prod = defaultdict(list)
        for r in rows:
            by_prod[r["prod"]].append(r)
        all_results[sub] = analyze(by_prod)

    # Print per-product averaged-across-submissions tables
    for prod in ["ASH_COATED_OSMIUM", "INTARIAN_PEPPER_ROOT"]:
        lines.append(f"\n## {prod}\n")
        lines.append(f"Mid mean/std/first/last (averaged across subs):")
        avg_stats = {k: statistics.fmean(all_results[sub][prod][k] for sub in LOGS) for k in ["mid_mean", "mid_std", "mid_first", "mid_last", "n_ticks"]}
        lines.append(f"- mean={avg_stats['mid_mean']:.2f}  std={avg_stats['mid_std']:.2f}  first={avg_stats['mid_first']:.2f}  last={avg_stats['mid_last']:.2f}  n={avg_stats['n_ticks']:.0f}")

        lines.append(f"\n### Feature → forward-mid-move regressions\n")
        lines.append("| feature | target | avg slope | avg R² | best R² (sub) |")
        lines.append("|---|---|---:|---:|---:|")
        feats = ["top_imbalance", "total_imbalance", "spread", "bot3_bid", "bot3_ask", "mom_1", "mom_5", "mom_10"]
        for f in feats:
            for t in ["fwd_1", "fwd_10", "fwd_50"]:
                key = f"{f}->{t}"
                slopes = [all_results[sub][prod][key]["slope"] for sub in LOGS]
                r2s = [all_results[sub][prod][key]["r2"] for sub in LOGS]
                avg_s = statistics.fmean(slopes)
                avg_r2 = statistics.fmean(r2s)
                best_r2 = max(r2s)
                lines.append(f"| {f} | {t} | {avg_s:+.5f} | {avg_r2:.4f} | {best_r2:.4f} |")

        lines.append("\n### Autocorrelation (lag 1) of 1-tick mid returns\n")
        acf_data = [all_results[sub][prod]["acf1_ret"] for sub in LOGS]
        slopes = [a["slope"] for a in acf_data]
        r2s = [a["r2"] for a in acf_data]
        lines.append(f"- avg ACF(1) slope = **{statistics.fmean(slopes):+.4f}**, avg R² = {statistics.fmean(r2s):.4f}")
        lines.append(f"- per-sub slopes: {[f'{s:+.3f}' for s in slopes]}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines) + "\n")
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
