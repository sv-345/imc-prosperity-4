"""Overfit-gate sensitivity sweep for iter 6.

For each tuned parameter, perturb by ±20% (or ±1 for integer params where
±20% rounds to 0) and run --quick. Mean must stay ≥ 10,000 under every
perturbation. If any param has a cliff, we'd need to simplify or remove it.
Writes results to docs/round2_sensitivity.md.

Runs in ~2 minutes on the current laptop (9 sweeps × ~10s each).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TRADER_TEMPLATE = ROOT / "iter6_trader.py"
VENV_PY = ROOT / "backtester/.venv/bin/python3"
VENV_CLI = ROOT / "backtester/.venv/bin/prosperity4mcbt"

# Baseline values from iter6_trader.py.
PARAMS = {
    "OSM_EDGE": 1,
    "PEP_EDGE": 1,
    "OSM_SKEW_SCALE": 40,
    "PEP_SKEW_SCALE": 20,
}

# Perturbation list per param (absolute values, not deltas).
def perturb(name: str, base: int) -> list[int]:
    if name.endswith("_EDGE"):
        # Integers in {0, 1, 2, 3} — test one lower and one higher.
        return [max(0, base - 1), base + 1]
    # SKEW_SCALE: ±20% rounded to nearest integer.
    return [max(1, round(base * 0.8)), round(base * 1.2)]


def run_with_overrides(overrides: dict[str, int], tmpdir: Path) -> dict:
    """Copy the trader, apply overrides, run --quick, return summary dict."""
    tmpdir.mkdir(parents=True, exist_ok=True)
    trader_path = tmpdir / "trader.py"
    src = TRADER_TEMPLATE.read_text()
    for name, value in overrides.items():
        src = re.sub(rf"^{name}\s*=.*$", f"{name} = {value}", src, flags=re.MULTILINE)
    trader_path.write_text(src)
    dashboard = tmpdir / "dashboard.json"
    cmd = [
        str(VENV_CLI),
        str(trader_path),
        "--round", "2",
        "--quick",
        "--out", str(dashboard),
    ]
    env = {**os.environ}
    subprocess.run(cmd, cwd=ROOT, env=env, check=True, capture_output=True)
    data = json.loads(dashboard.read_text())
    total = data["overall"]["totalPnl"]
    products = data.get("products", {})
    osm = products.get("ASH_COATED_OSMIUM", {}).get("pnl", {})
    pep = products.get("INTARIAN_PEPPER_ROOT", {}).get("pnl", {})
    return {
        "mean": total["mean"],
        "std": total["std"],
        "p05": total["p05"],
        "osm_mean": osm.get("mean", 0.0),
        "osm_positiveRate": osm.get("positiveRate", 0.0),
        "pep_mean": pep.get("mean", 0.0),
        "pep_positiveRate": pep.get("positiveRate", 0.0),
    }


def fmt_row(label: str, r: dict) -> str:
    return (
        f"| {label} | {r['mean']:>10,.0f} | {r['std']:>8,.0f} | {r['p05']:>10,.0f} | "
        f"{r['osm_mean']:>8,.0f} | {r['osm_positiveRate']:.0%} | "
        f"{r['pep_mean']:>8,.0f} | {r['pep_positiveRate']:.0%} |"
    )


def main() -> None:
    lines = [
        "# Round 2 — Iter 6 sensitivity sweep\n",
        "| variant | total mean | std | p05 | OSM mean | OSM +% | PEP mean | PEP +% |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]

    workdir = ROOT / "tmp/sensitivity"
    # Baseline.
    baseline = run_with_overrides({}, workdir / "baseline")
    lines.append(fmt_row("baseline", baseline))

    failures: list[tuple[str, int, dict]] = []
    for name, base in PARAMS.items():
        for value in perturb(name, base):
            overrides = {name: value}
            result = run_with_overrides(overrides, workdir / f"{name}_{value}")
            lines.append(fmt_row(f"{name} = {value} (base {base})", result))
            if result["mean"] < 10_000:
                failures.append((name, value, result))

    summary = "\n".join(lines)
    out = ROOT / "docs/round2_sensitivity.md"
    out.write_text(summary + "\n")
    print(summary)
    if failures:
        print(f"\n[FAIL] {len(failures)} perturbations dropped below 10k:")
        for name, value, result in failures:
            print(f"  {name} = {value}: mean {result['mean']:,.0f}")


if __name__ == "__main__":
    main()
