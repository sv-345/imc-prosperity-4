"""B1 ablation driver — runs MC across variants and aggregates results.

Produces per-variant CSV + summary stats + paired CIs vs V0 baseline.

Usage:
    python3 b1_harness.py --stage run       # launch MC for every variant
    python3 b1_harness.py --stage analyze   # parse run_summary.csvs, write b1_variant_ablation.md inputs
    python3 b1_harness.py --stage all       # run + analyze

Each variant has its own subdir in b1_tmp/<variant_id>/ containing dashboard.json
and run_summary.csv. We copy run_summary.csv into b1_mc_results/<variant_id>.csv
as the durable artifact.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import random
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Tuple

HERE = Path(__file__).resolve().parent
ROOT = Path("<repo>")
MCBT_DIR = ROOT / "chrispyroberts-imc-prosperity-4" / "backtester"
VARIANTS_DIR = HERE / "b1_variants"
RESULTS_DIR = HERE / "b1_mc_results"
TMP_DIR = HERE / "b1_tmp"

# Shared MC invocation parameters
MC_SESSIONS = 100
MC_SEED = 20260401
MC_ROUND = 2


# The variants we run. Ordered so V0 baseline is first.
# File names under b1_variants/:
#   V0_iter23_baseline.py
#   V1_full_kalman.py
#   V2_osm_only_kalman.py
#   V3_confidence_band.py
#   V4_hybrid_gated.py
VARIANTS = [
    "V0_iter23_baseline",
    "V1_full_kalman",
    "V2_osm_only_kalman",
    "V3_confidence_band",
    "V4_hybrid_gated",
]


def mc_cmd(variant: str, out_dir: Path) -> List[str]:
    strategy = VARIANTS_DIR / f"{variant}.py"
    dashboard_path = out_dir / "dashboard.json"
    cmd = [
        "uv",
        "run",
        "python3",
        "-m",
        "prosperity4mcbt",
        "--round",
        str(MC_ROUND),
        "--seed",
        str(MC_SEED),
        "--sessions",
        str(MC_SESSIONS),
        "--sample-sessions",
        "10",
        "--out",
        str(dashboard_path),
        str(strategy),
    ]
    return cmd


def run_variant(variant: str) -> Tuple[float, str]:
    out_dir = TMP_DIR / variant
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = mc_cmd(variant, out_dir)
    t0 = time.time()
    proc = subprocess.run(
        cmd,
        cwd=str(MCBT_DIR),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    elapsed = time.time() - t0
    if proc.returncode != 0:
        print(f"[{variant}] MC failed ({elapsed:.0f}s):", file=sys.stderr)
        sys.stderr.write(proc.stdout[-4000:])
        sys.stderr.write("\n")
        raise SystemExit(1)
    # Copy run_summary.csv to durable location
    src = out_dir / "run_summary.csv"
    dst = RESULTS_DIR / f"{variant}.csv"
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(src.read_bytes())
    # Preserve a small snippet of MC stdout for debug
    (out_dir / "stdout.log").write_text(proc.stdout)
    return elapsed, str(dst)


def load_pnl(variant: str) -> Dict[int, Dict[int, Dict[str, float]]]:
    """Return {session_id: {day: {"total":, "osm":, "pep":}}}. One session_id per row."""
    csv_path = RESULTS_DIR / f"{variant}.csv"
    out: Dict[int, Dict[int, Dict[str, float]]] = {}
    with csv_path.open() as f:
        reader = csv.DictReader(f)
        for row in reader:
            sid = int(row["session_id"])
            day = int(row["day"])
            total = float(row["total_pnl"])
            prod = json.loads(row["product_stats_json"]) if row.get("product_stats_json") else {}
            osm = float(prod.get("ASH_COATED_OSMIUM", {}).get("pnl", 0))
            pep = float(prod.get("INTARIAN_PEPPER_ROOT", {}).get("pnl", 0))
            out[sid] = {day: {"total": total, "osm": osm, "pep": pep}}
    return out


def load_simple(variant: str) -> List[Dict[str, float]]:
    """Return a list of {session_id, day, total_pnl, osm_pnl, pep_pnl} in session order."""
    csv_path = RESULTS_DIR / f"{variant}.csv"
    out = []
    with csv_path.open() as f:
        reader = csv.DictReader(f)
        for row in reader:
            prod = json.loads(row["product_stats_json"]) if row.get("product_stats_json") else {}
            osm = float(prod.get("ASH_COATED_OSMIUM", {}).get("pnl", 0))
            pep = float(prod.get("INTARIAN_PEPPER_ROOT", {}).get("pnl", 0))
            out.append(
                {
                    "session_id": int(row["session_id"]),
                    "day": int(row["day"]),
                    "total": float(row["total_pnl"]),
                    "osm": osm,
                    "pep": pep,
                }
            )
    out.sort(key=lambda r: r["session_id"])
    return out


def bootstrap_paired_diff(
    baseline: List[float], variant: List[float], n_boot: int = 10000, seed: int = 42
) -> Tuple[float, float, float]:
    """Paired bootstrap of mean(variant - baseline). Return (mean_diff, ci_lo, ci_hi)."""
    assert len(baseline) == len(variant)
    diffs = [v - b for v, b in zip(variant, baseline)]
    n = len(diffs)
    mean = sum(diffs) / n
    rng = random.Random(seed)
    idx = list(range(n))
    means = []
    for _ in range(n_boot):
        sample = [diffs[rng.choice(idx)] for _ in range(n)]
        means.append(sum(sample) / n)
    means.sort()
    lo = means[int(0.025 * n_boot)]
    hi = means[int(0.975 * n_boot)]
    return mean, lo, hi


def analytical_paired_ci(
    baseline: List[float], variant: List[float], alpha: float = 0.05
) -> Tuple[float, float, float, float]:
    """t-based CI on paired diffs. Return (mean_diff, ci_lo, ci_hi, se)."""
    diffs = [v - b for v, b in zip(variant, baseline)]
    n = len(diffs)
    mean = sum(diffs) / n
    sd = statistics.stdev(diffs) if n > 1 else 0.0
    se = sd / math.sqrt(n) if n > 0 else 0.0
    # t critical ~1.984 for n=100, df=99, two-sided 95%
    t_crit = 1.9842
    return mean, mean - t_crit * se, mean + t_crit * se, se


def per_day_stats(rows: List[Dict[str, float]]) -> Dict[int, Dict[str, float]]:
    by_day: Dict[int, List[float]] = {-1: [], 0: [], 1: []}
    for r in rows:
        by_day[r["day"]].append(r["total"])
    out = {}
    for d, vs in by_day.items():
        if not vs:
            out[d] = {"n": 0, "mean": 0.0, "std": 0.0}
            continue
        mu = sum(vs) / len(vs)
        sd = statistics.stdev(vs) if len(vs) > 1 else 0.0
        out[d] = {"n": len(vs), "mean": mu, "std": sd}
    return out


def per_day_paired_diff(
    baseline_rows: List[Dict[str, float]],
    variant_rows: List[Dict[str, float]],
    key: str = "total",
) -> Dict[int, Dict[str, float]]:
    by_day_b: Dict[int, List[float]] = {-1: [], 0: [], 1: []}
    by_day_v: Dict[int, List[float]] = {-1: [], 0: [], 1: []}
    for b, v in zip(baseline_rows, variant_rows):
        assert b["session_id"] == v["session_id"] and b["day"] == v["day"]
        by_day_b[b["day"]].append(b[key])
        by_day_v[v["day"]].append(v[key])
    out = {}
    for d in (-1, 0, 1):
        if not by_day_b[d]:
            out[d] = {"n": 0, "mean_diff": 0.0, "ci_lo": 0.0, "ci_hi": 0.0}
            continue
        m, lo, hi, se = analytical_paired_ci(by_day_b[d], by_day_v[d])
        out[d] = {"n": len(by_day_b[d]), "mean_diff": m, "ci_lo": lo, "ci_hi": hi, "se": se}
    return out


def analyze(variant_list: List[str]) -> None:
    baseline_rows = load_simple(variant_list[0])
    print(f"\n=== Baseline (V0) ===")
    bstats = per_day_stats(baseline_rows)
    total_mean = sum(r["total"] for r in baseline_rows) / len(baseline_rows)
    print(f"  n={len(baseline_rows)}  mean_total={total_mean:,.2f}")
    for d in (-1, 0, 1):
        s = bstats[d]
        print(f"  day {d:+d}: n={s['n']}  mean={s['mean']:,.2f}  std={s['std']:,.2f}")

    rows = []
    for v in variant_list[1:]:
        vrows = load_simple(v)
        assert len(vrows) == len(baseline_rows)
        # Overall paired diff
        m_boot, lo_boot, hi_boot = bootstrap_paired_diff(
            [r["total"] for r in baseline_rows], [r["total"] for r in vrows]
        )
        m_anal, lo_anal, hi_anal, se = analytical_paired_ci(
            [r["total"] for r in baseline_rows], [r["total"] for r in vrows]
        )
        # Per-k-tick uplift
        m_per_k = m_anal / 10.0  # 10k-tick → 1k-tick
        lo_per_k = lo_anal / 10.0
        hi_per_k = hi_anal / 10.0
        # Per-day
        per_day = per_day_paired_diff(baseline_rows, vrows, "total")
        # OSM/PEP breakdown
        m_osm, lo_osm, hi_osm, se_osm = analytical_paired_ci(
            [r["osm"] for r in baseline_rows], [r["osm"] for r in vrows]
        )
        m_pep, lo_pep, hi_pep, se_pep = analytical_paired_ci(
            [r["pep"] for r in baseline_rows], [r["pep"] for r in vrows]
        )
        print(f"\n=== Variant {v} ===")
        print(
            f"  total: mean_diff_boot={m_boot:+,.2f}  CI_boot=[{lo_boot:+,.2f},{hi_boot:+,.2f}]  "
            f"mean_diff_anal={m_anal:+,.2f}  CI_anal=[{lo_anal:+,.2f},{hi_anal:+,.2f}]  se={se:.2f}"
        )
        print(
            f"  total per 1k-tick: mean={m_per_k:+.2f}  CI=[{lo_per_k:+.2f},{hi_per_k:+.2f}]  (threshold +150)"
        )
        print(
            f"  osm: mean_diff={m_osm:+,.2f}  CI=[{lo_osm:+,.2f},{hi_osm:+,.2f}]"
        )
        print(
            f"  pep: mean_diff={m_pep:+,.2f}  CI=[{lo_pep:+,.2f},{hi_pep:+,.2f}]"
        )
        for d in (-1, 0, 1):
            pd = per_day[d]
            print(
                f"  day {d:+d}: n={pd['n']}  mean_diff={pd['mean_diff']:+,.2f}  "
                f"CI=[{pd['ci_lo']:+,.2f},{pd['ci_hi']:+,.2f}]"
            )
        rows.append(
            {
                "variant": v,
                "mean_diff_total": m_anal,
                "ci_lo_total": lo_anal,
                "ci_hi_total": hi_anal,
                "se_total": se,
                "mean_diff_boot": m_boot,
                "ci_lo_boot": lo_boot,
                "ci_hi_boot": hi_boot,
                "mean_diff_per_k": m_per_k,
                "ci_lo_per_k": lo_per_k,
                "ci_hi_per_k": hi_per_k,
                "mean_diff_osm": m_osm,
                "ci_lo_osm": lo_osm,
                "ci_hi_osm": hi_osm,
                "mean_diff_pep": m_pep,
                "ci_lo_pep": lo_pep,
                "ci_hi_pep": hi_pep,
                "day_minus1_n": per_day[-1]["n"],
                "day_minus1_diff": per_day[-1]["mean_diff"],
                "day_minus1_ci_lo": per_day[-1]["ci_lo"],
                "day_minus1_ci_hi": per_day[-1]["ci_hi"],
                "day_0_n": per_day[0]["n"],
                "day_0_diff": per_day[0]["mean_diff"],
                "day_0_ci_lo": per_day[0]["ci_lo"],
                "day_0_ci_hi": per_day[0]["ci_hi"],
                "day_1_n": per_day[1]["n"],
                "day_1_diff": per_day[1]["mean_diff"],
                "day_1_ci_lo": per_day[1]["ci_lo"],
                "day_1_ci_hi": per_day[1]["ci_hi"],
            }
        )

    # Write per-variant summary CSV
    summary_path = RESULTS_DIR / "_summary.csv"
    if rows:
        with summary_path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            for r in rows:
                w.writerow(r)
        print(f"\nWrote summary to {summary_path}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=["run", "analyze", "all"], default="all")
    ap.add_argument("--variants", nargs="*", default=None)
    args = ap.parse_args()
    variant_list = args.variants if args.variants else VARIANTS
    if args.stage in ("run", "all"):
        for v in variant_list:
            path = VARIANTS_DIR / f"{v}.py"
            if not path.exists():
                print(f"SKIP {v} — file missing at {path}", file=sys.stderr)
                continue
            print(f"\n>>> Running {v} ...")
            t, dst = run_variant(v)
            print(f"    done in {t:.0f}s, results at {dst}")
    if args.stage in ("analyze", "all"):
        analyze(variant_list)


if __name__ == "__main__":
    main()
