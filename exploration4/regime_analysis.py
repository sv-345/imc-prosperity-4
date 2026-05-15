"""Analyze OSM mid regime behavior — does mid revert after elevated
periods? If so, a short-when-elevated strategy would capture it.
"""
from __future__ import annotations
import json, io, csv, pathlib
import numpy as np

LOG_JSON = pathlib.Path('/tmp/prosperity_logs/303257/312201.json')


def main():
    d = json.load(open(LOG_JSON))
    act = csv.DictReader(io.StringIO(d['activitiesLog']), delimiter=';')
    osm = []  # (ts, mid, pnl)
    for r in act:
        if r.get('product') != 'ASH_COATED_OSMIUM': continue
        try: ts = int(r['timestamp'])
        except: continue
        mid = float(r['mid_price']) if r.get('mid_price') else None
        pnl = float(r['profit_and_loss']) if r.get('profit_and_loss') else None
        if mid is not None:
            osm.append((ts, mid, pnl))

    print(f"OSM rows: {len(osm)}")
    ts_arr = np.array([t for t, _, _ in osm])
    mid_arr = np.array([m for _, m, _ in osm])
    pnl_arr = np.array([p for _, _, p in osm])

    # regime segments: mid > 10003 (high), < 9999 (low), else normal
    high_mask = mid_arr >= 10004
    low_mask = mid_arr <= 9998
    normal_mask = ~(high_mask | low_mask)

    print(f"high regime (mid>=10004) ticks: {high_mask.sum()} ({100*high_mask.sum()/len(mid_arr):.1f}%)")
    print(f"low regime (mid<=9998): {low_mask.sum()} ({100*low_mask.sum()/len(mid_arr):.1f}%)")
    print(f"normal (9999-10003): {normal_mask.sum()} ({100*normal_mask.sum()/len(mid_arr):.1f}%)")

    # iter23 PnL gain per regime
    pnl_diffs = np.diff(pnl_arr)
    for name, mask in (('high', high_mask[:-1]), ('low', low_mask[:-1]), ('normal', normal_mask[:-1])):
        gains = pnl_diffs[mask]
        print(f"  {name}: n={len(gains)}  total_gain=${gains.sum():.2f}  mean_per_tick=${gains.mean():.2f}")

    # Identify contiguous high-regime segments and measure subsequent reversion
    print("\n\nCONTIGUOUS HIGH-REGIME SEGMENTS (mid>=10004 for N+ ticks):")
    segments = []
    i = 0
    while i < len(mid_arr):
        if high_mask[i]:
            j = i
            while j < len(mid_arr) and high_mask[j]:
                j += 1
            segments.append((ts_arr[i], ts_arr[j-1], j-i))
            i = j
        else:
            i += 1
    print(f"n_segments: {len(segments)}")
    for lo, hi, n_ticks in segments:
        if n_ticks >= 5:  # at least 5 ticks
            # What happens AFTER the segment?
            # Find mid 10 ticks after hi
            idx_hi = np.where(ts_arr == hi)[0][0]
            post_idx = min(idx_hi + 10, len(mid_arr) - 1)
            post_mid = mid_arr[post_idx]
            entry_mid = mid_arr[np.where(ts_arr == lo)[0][0]]
            peak_idx = np.argmax(mid_arr[np.where(ts_arr == lo)[0][0]:idx_hi+1]) + np.where(ts_arr == lo)[0][0]
            peak_mid = mid_arr[peak_idx]
            # iter23 PnL in this segment
            pnl_entry = pnl_arr[np.where(ts_arr == lo)[0][0]]
            pnl_exit = pnl_arr[idx_hi]
            pnl_delta = pnl_exit - pnl_entry
            print(f"  segment ts={lo}..{hi} ({n_ticks} ticks)  peak_mid={peak_mid:.1f} (entry={entry_mid:.1f})  post_mid={post_mid:.1f}  iter23_pnl_in_seg=${pnl_delta:+.1f}")

    # Simpler: what's OSM mid trajectory over time (bucketed 5K-ts)
    print("\n\n5K-ts buckets of OSM mid + iter23 PnL slope:")
    buckets = []
    for b_start in range(0, 100000, 5000):
        b_end = b_start + 5000
        mask = (ts_arr >= b_start) & (ts_arr < b_end)
        if not mask.any(): continue
        mid_avg = mid_arr[mask].mean()
        mid_range = (mid_arr[mask].min(), mid_arr[mask].max())
        pnl_gain = (pnl_arr[mask][-1] - pnl_arr[mask][0]) if mask.sum() > 1 else 0
        print(f"  ts=[{b_start:>5d}..{b_end:>5d}]  mid_avg={mid_avg:.1f}  mid_range={mid_range[0]:.1f}..{mid_range[1]:.1f}  iter23_pnl_gain=${pnl_gain:+.1f}")


if __name__ == "__main__":
    main()
