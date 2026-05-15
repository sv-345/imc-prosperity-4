"""Quantify how much of the OSM 'clustering' in viz_OSM_day0_0_200000.html
is the deterministic taker schedule vs residual non-scheduled activity.

For each day:
  - agg_bid / agg_ask quote events (bid crossing >=FV, ask crossing <=FV)
  - taker trades (signed by classify)
  - fraction of each that hits ts in OSM_SCHEDULE
  - rolling density (win=5000 ts) of total vs non-scheduled events
"""
from __future__ import annotations
import pathlib, sys
import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "exploration3"))
from osm_schedule import OSM_SCHEDULE  # type: ignore

DATA = ROOT / "ROUND_2"
OSM = "ASH_COATED_OSMIUM"
FV = 10001.0


def load(day: int):
    p = pd.read_csv(DATA / f"prices_round_2_day_{day}.csv", sep=";")
    p = p[p["product"] == OSM].sort_values("timestamp").reset_index(drop=True)
    t = pd.read_csv(DATA / f"trades_round_2_day_{day}.csv", sep=";")
    t = t[t["symbol"] == OSM].sort_values("timestamp").reset_index(drop=True)
    return p, t


def agg_masks(p: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    n = len(p)
    ab = np.zeros(n, dtype=bool)
    aa = np.zeros(n, dtype=bool)
    for i in (1, 2, 3):
        bp = p[f"bid_price_{i}"].values
        ap = p[f"ask_price_{i}"].values
        ab |= (~pd.isna(bp)) & (bp >= FV)
        aa |= (~pd.isna(ap)) & (ap <= FV)
    return ab, aa


def windowed_density(ts: np.ndarray, flags: np.ndarray, win_ts: int = 5000) -> pd.Series:
    s = pd.Series(flags.astype(int), index=ts).sort_index()
    # Events per rolling win_ts (ts in units of 100 → win_ts=5000 = 50 ticks)
    # Use time-based rolling on the index treated as int
    grouped = s.groupby(s.index // win_ts).sum()
    grouped.index = grouped.index * win_ts
    return grouped


def main():
    sched_ts = set(OSM_SCHEDULE.keys())
    print(f"OSM_SCHEDULE: {len(sched_ts)} deterministic ticks\n")

    for day in (-1, 0, 1):
        p, t = load(day)
        ts = p["timestamp"].values
        ab, aa = agg_masks(p)

        is_sched = np.array([int(x) in sched_ts for x in ts])

        ab_ct = int(ab.sum())
        aa_ct = int(aa.sum())
        ab_sched = int((ab & is_sched).sum())
        aa_sched = int((aa & is_sched).sum())

        # Taker trade analysis
        t_ts = t["timestamp"].astype(int).values
        t_sched = np.array([x in sched_ts for x in t_ts])
        t_qty = t["quantity"].values
        total_qty = int(t_qty.sum())
        sched_qty = int(t_qty[t_sched].sum())

        print(f"=== DAY {day} ===")
        print(f"  agg_bid quote events:  total={ab_ct:4d}  on_sched_ts={ab_sched:4d}  ({100*ab_sched/max(ab_ct,1):.1f}%)")
        print(f"  agg_ask quote events:  total={aa_ct:4d}  on_sched_ts={aa_sched:4d}  ({100*aa_sched/max(aa_ct,1):.1f}%)")
        print(f"  taker trade count:     total={len(t):4d}  on_sched_ts={int(t_sched.sum()):4d}  ({100*t_sched.sum()/max(len(t),1):.1f}%)")
        print(f"  taker qty:             total={total_qty:5d}  on_sched_ts={sched_qty:5d}  ({100*sched_qty/max(total_qty,1):.1f}%)")

        # Window-level: for day 0 and range 0-200000 (the viz window), show per-50k-ts density
        if day == 0:
            print(f"  --- day 0 density per 50000 ts bucket (viz range 0-200000) ---")
            ts_a = ts[:]
            for bucket_start in range(0, 200000, 50000):
                bucket_end = bucket_start + 50000
                in_bucket = (ts_a >= bucket_start) & (ts_a < bucket_end)
                ab_b = int((ab & in_bucket).sum())
                aa_b = int((aa & in_bucket).sum())
                ab_b_sched = int((ab & in_bucket & is_sched).sum())
                aa_b_sched = int((aa & in_bucket & is_sched).sum())
                tb_mask = (t_ts >= bucket_start) & (t_ts < bucket_end)
                tb_ct = int(tb_mask.sum())
                tb_sched = int((tb_mask & t_sched).sum())
                tb_qty = int(t_qty[tb_mask].sum())
                tb_sched_qty = int(t_qty[tb_mask & t_sched].sum())
                print(f"  [{bucket_start:6d},{bucket_end:6d})  "
                      f"agg_bid={ab_b:3d}(sched={ab_b_sched:3d})  "
                      f"agg_ask={aa_b:3d}(sched={aa_b_sched:3d})  "
                      f"trades={tb_ct:3d}(sched={tb_sched:3d})  "
                      f"qty={tb_qty:4d}(sched={tb_sched_qty:4d},{100*tb_sched_qty/max(tb_qty,1):.0f}%)")
        print()


if __name__ == "__main__":
    main()
