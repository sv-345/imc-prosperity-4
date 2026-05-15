"""Run iter25_tb1 baseline and iter26_tape_test on 3 R2 training days,
compute per-day + per-bucket OSM PnL deltas, and summarize fire log.

Per tape_pinning_test_spec.md: buckets are [0,50K), [50K,100K), [100K,150K), [150K,200K).
Full-day totals reported separately.
"""
from __future__ import annotations
import os, re, sys, subprocess, pathlib, tempfile, json, shutil

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "chrispyroberts-imc-prosperity-4" / "data"
BT = ROOT / "chrispyroberts-imc-prosperity-4" / "backtester" / ".venv" / "bin" / "prosperity3bt"

BASELINE = ROOT / "exploration4" / "iter25_tb1.py"
VARIANT = ROOT / "exploration5" / "iter26_tape_test.py"

DAYS = ["2--1", "2-0", "2-1"]
BUCKETS = [(0, 50_000), (50_000, 100_000), (100_000, 150_000), (150_000, 200_000)]
OSM = "ASH_COATED_OSMIUM"


def rewrite(src: pathlib.Path, dst: pathlib.Path) -> None:
    t = src.read_text()
    t = re.sub(r"^from datamodel import", "from prosperity3bt.datamodel import", t, flags=re.M)
    dst.write_text(t)


def run_bt(script: pathlib.Path, day: str, out_log: pathlib.Path, env: dict | None = None) -> tuple[float | None, float | None, float | None]:
    cmd = [str(BT), str(script), day, "--data", str(DATA), "--out", str(out_log), "--no-progress"]
    r = subprocess.run(cmd, capture_output=True, text=True, env=env)
    out = r.stdout + r.stderr
    osm = pep = tot = None
    for line in out.splitlines():
        m = re.search(r"ASH_COATED_OSMIUM:\s*([-\d,]+\.?\d*)", line)
        if m: osm = float(m.group(1).replace(",", ""))
        m = re.search(r"INTARIAN_PEPPER_ROOT:\s*([-\d,]+\.?\d*)", line)
        if m: pep = float(m.group(1).replace(",", ""))
        m = re.search(r"Total profit:\s*([-\d,]+\.?\d*)", line)
        if m: tot = float(m.group(1).replace(",", ""))
    if osm is None:
        sys.stderr.write(f"\n[run_bt WARN] could not parse PnL; last 200 lines of output:\n")
        sys.stderr.write("\n".join(out.splitlines()[-200:]))
        sys.stderr.write("\n")
    return osm, pep, tot


def parse_activities(out_log: pathlib.Path) -> dict:
    """Return {timestamp: {product: pnl}} from the Activities section."""
    txt = out_log.read_text()
    start = txt.find("Activities log:")
    end = txt.find("Trade History:", start)
    if start < 0:
        return {}
    block = txt[start:end if end > 0 else None]
    lines = block.splitlines()
    # header is "day;timestamp;product;...;profit_and_loss"
    header = None
    rows = {}
    for line in lines[1:]:
        if not line.strip():
            continue
        parts = line.split(";")
        if header is None:
            header = parts
            try:
                ts_i = header.index("timestamp")
                prod_i = header.index("product")
                pnl_i = header.index("profit_and_loss")
            except ValueError:
                return {}
            continue
        if len(parts) <= pnl_i:
            continue
        try:
            ts = int(parts[ts_i])
            prod = parts[prod_i]
            pnl = float(parts[pnl_i])
        except (ValueError, IndexError):
            continue
        rows.setdefault(ts, {})[prod] = pnl
    return rows


def bucket_pnl(rows: dict, product: str) -> list[float]:
    """Return per-bucket PnL for product: pnl at bucket_end_ts - pnl at bucket_start_ts.

    pnl is cumulative realized+unrealized from engine. Bucket delta is the
    change within that timestamp window.
    """
    out = []
    sorted_ts = sorted(rows.keys())
    for lo, hi in BUCKETS:
        # Find last ts < lo and last ts < hi
        lo_pnl = 0.0
        hi_pnl = 0.0
        for ts in sorted_ts:
            if ts < lo:
                lo_pnl = rows[ts].get(product, lo_pnl)
            if ts < hi:
                hi_pnl = rows[ts].get(product, hi_pnl)
            else:
                break
        # correction: include pnl at exactly ts<lo as start baseline
        out.append(hi_pnl - lo_pnl)
    return out


def summarize_fires(fire_log: pathlib.Path) -> dict:
    if not fire_log.exists():
        return {}
    lines = fire_log.read_text().strip().splitlines()
    by_day_bucket = {}
    for ln in lines:
        parts = ln.split(",")
        if len(parts) < 6:
            continue
        day, ts, direction, fills, avg_price, ref_fv = parts[:6]
        try:
            ts = int(ts); fills = int(fills); avg_price = float(avg_price)
        except ValueError:
            continue
        bucket_idx = None
        for i, (lo, hi) in enumerate(BUCKETS):
            if lo <= ts < hi:
                bucket_idx = i
                break
        bucket_key = f"b{bucket_idx}" if bucket_idx is not None else "other"
        key = (day, bucket_key, direction)
        rec = by_day_bucket.setdefault(key, {"n": 0, "qty": 0, "px_sum": 0.0})
        rec["n"] += 1
        rec["qty"] += fills
        rec["px_sum"] += avg_price * fills
    return by_day_bucket


def main():
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="tape_test_"))
    baseline_staged = tmp / "baseline.py"
    variant_staged = tmp / "variant.py"
    rewrite(BASELINE, baseline_staged)
    rewrite(VARIANT, variant_staged)

    fire_log = tmp / "fires.csv"
    sig_log = tmp / "signals.csv"
    for p in (fire_log, sig_log):
        if p.exists():
            p.unlink()

    print("Run dir:", tmp)
    print(f"Baseline: {BASELINE}")
    print(f"Variant:  {VARIANT}")
    print()

    summary = {"baseline": {}, "variant": {}}
    for day in DAYS:
        b_log = tmp / f"base_{day}.log"
        v_log = tmp / f"var_{day}.log"

        osm_b, pep_b, tot_b = run_bt(baseline_staged, day, b_log)
        env = {**os.environ, "TAPE_TEST_FIRE_LOG": str(fire_log), "TAPE_TEST_SIGNAL_LOG": str(sig_log), "TAPE_TEST_DAY": day}
        osm_v, pep_v, tot_v = run_bt(variant_staged, day, v_log, env=env)

        rows_b = parse_activities(b_log)
        rows_v = parse_activities(v_log)
        buckets_b = bucket_pnl(rows_b, OSM)
        buckets_v = bucket_pnl(rows_v, OSM)
        buckets_pep_b = bucket_pnl(rows_b, "INTARIAN_PEPPER_ROOT")
        buckets_pep_v = bucket_pnl(rows_v, "INTARIAN_PEPPER_ROOT")

        summary["baseline"][day] = {"osm": osm_b, "pep": pep_b, "tot": tot_b,
                                     "osm_buckets": buckets_b, "pep_buckets": buckets_pep_b}
        summary["variant"][day] = {"osm": osm_v, "pep": pep_v, "tot": tot_v,
                                    "osm_buckets": buckets_v, "pep_buckets": buckets_pep_v}

    print("=" * 88)
    print(f"{'day':<6} {'base osm':>10} {'var osm':>10} {'Δ osm':>10} {'base pep':>10} {'var pep':>10} {'base tot':>10} {'var tot':>10} {'Δ tot':>10}")
    tot_osm_b = tot_osm_v = tot_full_b = tot_full_v = 0.0
    for day in DAYS:
        b = summary["baseline"][day]; v = summary["variant"][day]
        d_osm = (v["osm"] or 0) - (b["osm"] or 0)
        d_tot = (v["tot"] or 0) - (b["tot"] or 0)
        tot_osm_b += (b["osm"] or 0); tot_osm_v += (v["osm"] or 0)
        tot_full_b += (b["tot"] or 0); tot_full_v += (v["tot"] or 0)
        print(f"{day:<6} {b['osm']:>10.0f} {v['osm']:>10.0f} {d_osm:>+10.0f} {b['pep']:>10.0f} {v['pep']:>10.0f} {b['tot']:>10.0f} {v['tot']:>10.0f} {d_tot:>+10.0f}")
    print(f"{'SUM':<6} {tot_osm_b:>10.0f} {tot_osm_v:>10.0f} {tot_osm_v-tot_osm_b:>+10.0f} {'':>10} {'':>10} {tot_full_b:>10.0f} {tot_full_v:>10.0f} {tot_full_v-tot_full_b:>+10.0f}")
    print()

    print("OSM per-bucket PnL (Δ = variant - baseline). Window in timestamps.")
    print(f"{'day':<6} {'bucket':<14} {'base':>10} {'var':>10} {'Δ':>10}")
    for day in DAYS:
        b = summary["baseline"][day]["osm_buckets"]
        v = summary["variant"][day]["osm_buckets"]
        for i, (lo, hi) in enumerate(BUCKETS):
            label = f"{lo//1000}K-{hi//1000}K"
            print(f"{day:<6} {label:<14} {b[i]:>10.0f} {v[i]:>10.0f} {v[i]-b[i]:>+10.0f}")
    print()

    print("Fire events summary (variant only; fires in (fv,fv+BAND] UP or [fv-BAND,fv) DN):")
    fires = summarize_fires(fire_log)
    if not fires:
        print("  (no fires logged)")
    else:
        print(f"  {'day':<6} {'bucket':<6} {'dir':<4} {'n':>6} {'qty':>6} {'avg_px':>10}")
        # aggregate per day too
        for (day, bk, direction), rec in sorted(fires.items()):
            avg_px = rec["px_sum"] / rec["qty"] if rec["qty"] else 0.0
            print(f"  {day:<6} {bk:<6} {direction:<4} {rec['n']:>6} {rec['qty']:>6} {avg_px:>10.2f}")
        # totals
        print()
        per_day = {}
        for (day, bk, direction), rec in fires.items():
            pd_ = per_day.setdefault(day, {"n": 0, "qty": 0})
            pd_["n"] += rec["n"]; pd_["qty"] += rec["qty"]
        print(f"  {'day':<6} {'total n':>8} {'total qty':>10}")
        for day, rec in sorted(per_day.items()):
            print(f"  {day:<6} {rec['n']:>8} {rec['qty']:>10}")

    # Dump structured JSON for downstream docs
    json_out = tmp / "summary.json"
    with json_out.open("w") as f:
        json.dump({"summary": summary, "fires": {str(k): v for k, v in fires.items()}}, f, indent=2, default=str)
    print(f"\nJSON summary: {json_out}")
    print(f"Fire log:     {fire_log}")

    # Copy outputs to exploration5
    shutil.copy(json_out, ROOT / "exploration5" / "tape_test_summary.json")
    if fire_log.exists():
        shutil.copy(fire_log, ROOT / "exploration5" / "tape_test_fires.csv")
    if sig_log.exists():
        shutil.copy(sig_log, ROOT / "exploration5" / "tape_test_signals.csv")

    # Signal-log quick summary (by day, by bucket)
    if sig_log.exists():
        by_key = {}
        for ln in sig_log.read_text().strip().splitlines():
            parts = ln.split(",")
            if len(parts) < 7:
                continue
            day, ts = parts[0], int(parts[1])
            sig = int(parts[2])
            for i, (lo, hi) in enumerate(BUCKETS):
                if lo <= ts < hi:
                    bucket = f"b{i}"
                    break
            else:
                bucket = "other"
            direction = "UP" if sig > 0 else "DN"
            key = (day, bucket, direction)
            by_key[key] = by_key.get(key, 0) + 1
        print("\nSignal crossings (|S| >= DENSITY_THRESH):")
        print(f"  {'day':<6} {'bucket':<6} {'dir':<4} {'n':>6}")
        for k in sorted(by_key):
            print(f"  {k[0]:<6} {k[1]:<6} {k[2]:<4} {by_key[k]:>6}")


if __name__ == "__main__":
    main()
