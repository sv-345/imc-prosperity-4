"""Diagnose what the MC simulator presents to the Kalman filter."""
from __future__ import annotations
import csv, math, os, sys, statistics
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "b1_variants"))
from _kalman_core import LatentFVKalman  # type: ignore


def inner_mid_osm(row):
    ib = ia = None
    for i in (1, 2, 3):
        p = row.get(f"bid_price_{i}", "")
        v = row.get(f"bid_volume_{i}", "")
        if p and v:
            vi = int(v)
            if 10 <= vi <= 15:
                ib = float(p)
                break
    for i in (1, 2, 3):
        p = row.get(f"ask_price_{i}", "")
        v = row.get(f"ask_volume_{i}", "")
        if p and v:
            vi = int(v)
            if 10 <= vi <= 15:
                ia = float(p)
                break
    if ib is not None and ia is not None and 15 <= ia - ib <= 17:
        return (ib + ia) / 2.0
    if ib is not None:
        return ib + 8.0
    if ia is not None:
        return ia - 8.0
    return None


def replay_session(prices_csv: Path):
    filt = None
    fvs = []
    ys = []
    raw_mids = []
    with prices_csv.open() as f:
        r = csv.DictReader(f, delimiter=";")
        for row in r:
            if row["product"] != "ASH_COATED_OSMIUM":
                continue
            bb_s = row.get("bid_price_1", "")
            ba_s = row.get("ask_price_1", "")
            bb = float(bb_s) if bb_s else None
            ba = float(ba_s) if ba_s else None
            one_sided = (bb is None) or (ba is None)
            y = inner_mid_osm(row)
            if bb is not None and ba is not None:
                raw_mids.append((bb + ba) / 2.0)
            if filt is None and y is not None:
                filt = LatentFVKalman.cold_osm()
                filt.tick = int(row["timestamp"]) // 100 - 1
            if filt is not None:
                filt.update(y, one_sided=one_sided)
                fvs.append(filt.fv())
                if y is not None:
                    ys.append(y)
    return fvs, ys, raw_mids


def main():
    session_base = Path("<repo>/research_org/researchers/project_latent_fv_kalman/phase_b/b1_tmp/V0_iter23/sessions")
    sess_dirs = sorted([p for p in session_base.iterdir() if p.is_dir()])
    print(f"Found {len(sess_dirs)} session dirs")
    for sd in sess_dirs:
        r2_dir = sd / "round2"
        # Find the prices csv
        csvs = list(r2_dir.glob("prices_round_2_day_*.csv"))
        if not csvs:
            continue
        for pc in csvs:
            day_tag = pc.stem.split("day_")[1]
            fvs, ys, raw = replay_session(pc)
            if not fvs:
                continue
            print(
                f"  {sd.name} day{day_tag}: n={len(fvs)} "
                f"fv_mean={statistics.mean(fvs):.3f} fv_std={statistics.stdev(fvs):.3f} "
                f"y_mean={statistics.mean(ys):.3f} "
                f"raw_mean={statistics.mean(raw):.3f} "
                f"below10001={sum(1 for v in fvs if v < 10001)} above={sum(1 for v in fvs if v > 10001)}"
            )


if __name__ == "__main__":
    main()
