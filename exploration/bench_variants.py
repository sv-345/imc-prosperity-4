"""Test variants of the OSM gate. We create temp files with different
gate configurations and benchmark each.
"""
from __future__ import annotations
import subprocess
import pathlib
import re
import tempfile
import shutil
import json

ROOT = pathlib.Path(__file__).resolve().parent.parent
R2 = ROOT / "ROUND_2"
DATA = ROOT / "chrispyroberts-imc-prosperity-4" / "data"
BT = ROOT / "chrispyroberts-imc-prosperity-4" / "backtester" / ".venv" / "bin" / "prosperity3bt"


def make_variant(name: str, base_src: pathlib.Path, *,
                 osm_fv_override: int | None = None,
                 gate_mode: str = "static",  # 'static', 'dynamic_clamp_N'
                 clamp_n: int = 10) -> pathlib.Path:
    text = base_src.read_text()
    # Rewrite imports
    text = re.sub(r"^from datamodel import", "from prosperity3bt.datamodel import", text, flags=re.M)

    if osm_fv_override is not None:
        text = re.sub(r"^OSM_FV = \d+", f"OSM_FV = {osm_fv_override}", text, flags=re.M)

    if gate_mode == "static":
        # Ensure the take-gate uses fv (already the case in iter23)
        pass

    outdir = pathlib.Path(tempfile.gettempdir()) / "osm_variants"
    outdir.mkdir(exist_ok=True)
    outpath = outdir / f"{name}.py"
    outpath.write_text(text)
    return outpath


def run_bt(trader_path: pathlib.Path, day_arg: str) -> dict:
    cmd = [str(BT), str(trader_path), day_arg, "--data", str(DATA), "--no-out"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    out = result.stdout + result.stderr
    osm = pep = total = None
    for line in out.splitlines():
        m = re.search(r"^\s*ASH_COATED_OSMIUM:\s*([-\d,]+\.?\d*)", line)
        if m: osm = float(m.group(1).replace(",", ""))
        m = re.search(r"^\s*INTARIAN_PEPPER_ROOT:\s*([-\d,]+\.?\d*)", line)
        if m: pep = float(m.group(1).replace(",", ""))
        m = re.search(r"^\s*Total profit:\s*([-\d,]+\.?\d*)", line)
        if m: total = float(m.group(1).replace(",", ""))
    return dict(osm=osm, pep=pep, total=total)


def main() -> None:
    # Variants to test
    variants = {
        "iter23 (baseline)": {"src": R2 / "iter23_trader.py", "kwargs": {}},
        "iter24 dyn clamp10": {"src": R2 / "iter24_dynamic_gate_trader.py", "kwargs": {}},
        "iter23 FV=10002":   {"src": R2 / "iter23_trader.py", "kwargs": {"osm_fv_override": 10002}},
        "iter23 FV=10003":   {"src": R2 / "iter23_trader.py", "kwargs": {"osm_fv_override": 10003}},
        "iter23 FV=10004":   {"src": R2 / "iter23_trader.py", "kwargs": {"osm_fv_override": 10004}},
        "iter23 FV=10005":   {"src": R2 / "iter23_trader.py", "kwargs": {"osm_fv_override": 10005}},
    }

    # iter24 with tighter clamp
    for clamp in (3, 5):
        # make a variant of iter24 with different clamp
        text = (R2 / "iter24_dynamic_gate_trader.py").read_text()
        text = re.sub(r"^from datamodel import", "from prosperity3bt.datamodel import", text, flags=re.M)
        text = re.sub(r"^OSM_GATE_CLAMP = \d+", f"OSM_GATE_CLAMP = {clamp}", text, flags=re.M)
        outdir = pathlib.Path(tempfile.gettempdir()) / "osm_variants"
        outdir.mkdir(exist_ok=True)
        path = outdir / f"iter24_clamp{clamp}.py"
        path.write_text(text)
        variants[f"iter24 dyn clamp{clamp}"] = {"precompiled": path}

    # Compile all variants
    compiled = {}
    for name, spec in variants.items():
        if "precompiled" in spec:
            compiled[name] = spec["precompiled"]
        else:
            compiled[name] = make_variant(
                name.replace(" ", "_").replace("(", "").replace(")", "").replace("=", "").lower(),
                spec["src"], **spec["kwargs"])
        print(f"  prepared {name} -> {compiled[name]}")

    days = ("2--1", "2-0", "2-1")
    results: dict[str, dict[str, dict]] = {n: {} for n in variants}
    for day in days:
        print(f"\n==== day {day} ====")
        for name, path in compiled.items():
            r = run_bt(path, day)
            results[name][day] = r
            if r['total'] is not None:
                print(f"  {name:30s}: OSM={r['osm']:>7.0f}  PEP={r['pep']:>7.0f}  total={r['total']:>7.0f}")
            else:
                print(f"  {name:30s}: FAILED")

    # Summary
    print("\n==== 3-DAY TOTALS (sum) ====")
    baseline_total = sum((results["iter23 (baseline)"][d]["total"] or 0) for d in days)
    print(f"  baseline iter23: {baseline_total:.0f}")
    for name in variants:
        if name == "iter23 (baseline)": continue
        t = sum((results[name][d]["total"] or 0) for d in days)
        delta = t - baseline_total
        print(f"  {name:30s}: {t:.0f}  Δ={delta:+.0f}")

    with open(ROOT / "exploration" / "bench_variants.json", "w") as f:
        json.dump(results, f, indent=2)


if __name__ == "__main__":
    main()
