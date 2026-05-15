"""Scan the full 1000-tick session for mean-reversion events in OSM.

Definition:
  mid is "elevated" when avg(last 5 ticks) >= 10005
  mid is "deflated" when avg(last 5 ticks) <= 9997
  reversion event: elevated → returns within 10002-10004 within N ticks

For each event, compute:
  - peak mid reached
  - time to reversion (in ticks)
  - magnitude of reversion (peak - post)
  - iter23's PnL gain during the event window
"""
from __future__ import annotations
import json, io, csv, pathlib
import numpy as np

LOG_JSON = pathlib.Path('/tmp/prosperity_logs/303257/312201.json')


def main():
    d = json.load(open(LOG_JSON))
    act = csv.DictReader(io.StringIO(d['activitiesLog']), delimiter=';')
    osm = []
    for r in act:
        if r.get('product') != 'ASH_COATED_OSMIUM': continue
        try: ts = int(r['timestamp'])
        except: continue
        mid = float(r['mid_price']) if r.get('mid_price') else None
        pnl = float(r['profit_and_loss']) if r.get('profit_and_loss') else None
        if mid is not None:
            osm.append((ts, mid, pnl))

    ts_arr = np.array([t for t, _, _ in osm])
    mid_arr = np.array([m for _, m, _ in osm])
    pnl_arr = np.array([p for _, _, p in osm])

    # Rolling 5-tick mean mid
    window = 5
    roll = np.convolve(mid_arr, np.ones(window)/window, mode='same')

    # Find "elevated" onsets: roll crosses above 10005
    above = roll >= 10005
    onsets = []
    for i in range(1, len(above)):
        if above[i] and not above[i-1]:
            onsets.append(i)
    print(f"n_elevated_onsets: {len(onsets)}")

    # For each onset, find subsequent peak and reversion
    events = []
    for i0 in onsets:
        # Look forward up to 50 ticks
        j = i0
        peak = roll[i0]; peak_i = i0
        while j < min(i0 + 50, len(roll)):
            if roll[j] > peak:
                peak = roll[j]; peak_i = j
            if roll[j] <= 10003:
                break
            j += 1
        reverted_i = j if j < len(roll) and roll[j] <= 10003 else None
        duration = (ts_arr[reverted_i] - ts_arr[i0]) if reverted_i else None
        post_mid = roll[reverted_i] if reverted_i else roll[j-1]
        reversion = peak - post_mid
        # iter23 PnL during event
        if reverted_i:
            pnl_gain = pnl_arr[reverted_i] - pnl_arr[i0]
        else:
            pnl_gain = pnl_arr[min(i0+50, len(pnl_arr)-1)] - pnl_arr[i0]
        events.append({
            'onset_ts': int(ts_arr[i0]),
            'peak_ts': int(ts_arr[peak_i]),
            'peak_mid': float(peak),
            'post_ts': int(ts_arr[reverted_i]) if reverted_i else None,
            'post_mid': float(post_mid),
            'duration': int(duration) if duration else None,
            'reversion': float(reversion),
            'iter23_pnl_gain': float(pnl_gain),
            'reverted': reverted_i is not None,
        })

    # Summary
    reverted = [e for e in events if e['reverted']]
    not_rev = [e for e in events if not e['reverted']]
    print(f"events that reverted within 50 ticks: {len(reverted)}")
    print(f"events that did NOT revert: {len(not_rev)}")

    if reverted:
        peaks = [e['peak_mid'] for e in reverted]
        durs = [e['duration'] for e in reverted]
        revs = [e['reversion'] for e in reverted]
        gains = [e['iter23_pnl_gain'] for e in reverted]
        print(f"  avg peak_mid: {np.mean(peaks):.2f}")
        print(f"  avg duration: {np.mean(durs):.0f} ts ({np.mean(durs)/100:.1f} ticks)")
        print(f"  avg reversion: {np.mean(revs):.2f}")
        print(f"  avg iter23 PnL gain during event: ${np.mean(gains):.2f}")
        print(f"  total iter23 PnL gain across all events: ${sum(gains):.2f}")

    # List events with biggest reversion
    events_sorted = sorted(events, key=lambda e: -e['reversion'])
    print(f"\nTop 10 biggest reversions:")
    for e in events_sorted[:10]:
        print(f"  onset ts={e['onset_ts']}  peak ts={e['peak_ts']} peak={e['peak_mid']:.1f}  "
              f"post={e['post_mid']:.1f}  duration={e['duration']}ts  rev={e['reversion']:.1f}  iter23=${e['iter23_pnl_gain']:+.1f}")


if __name__ == "__main__":
    main()
