"""Extract per-product PnL trajectory from iter23 baseline log,
identify which product drives each step-up window.
"""
from __future__ import annotations
import json, io, csv, pathlib
import numpy as np

LOG_JSON = pathlib.Path('/tmp/prosperity_logs/303257/312201.json')


def main():
    d = json.load(open(LOG_JSON))
    act = csv.DictReader(io.StringIO(d['activitiesLog']), delimiter=';')
    osm_pnl = []  # (ts, pnl)
    pep_pnl = []
    osm_book = []  # (ts, bid1, ask1, mid)
    pep_book = []
    for r in act:
        try: ts = int(r['timestamp'])
        except: continue
        try: pnl = float(r['profit_and_loss'])
        except: continue
        bid = float(r['bid_price_1']) if r.get('bid_price_1') else None
        ask = float(r['ask_price_1']) if r.get('ask_price_1') else None
        mid = float(r['mid_price']) if r.get('mid_price') else None
        if r['product'] == 'ASH_COATED_OSMIUM':
            osm_pnl.append((ts, pnl))
            osm_book.append((ts, bid, ask, mid))
        else:
            pep_pnl.append((ts, pnl))
            pep_book.append((ts, bid, ask, mid))

    print(f"OSM: {len(osm_pnl)} rows, final pnl {osm_pnl[-1][1]:.2f}")
    print(f"PEP: {len(pep_pnl)} rows, final pnl {pep_pnl[-1][1]:.2f}")

    # Sliding window gains (4K ts)
    def window_gains(pnl_list, window_ts=4000):
        # return list of (lo, hi, gain)
        out = []
        ts_arr = np.array([t for t, _ in pnl_list])
        v_arr = np.array([v for _, v in pnl_list])
        step = 100  # ts per row (2 products at each ts, so PnL series has one value per 100ts)
        n_per_win = window_ts // step
        for i in range(len(pnl_list) - n_per_win):
            lo = ts_arr[i]; hi = ts_arr[i+n_per_win]
            gain = v_arr[i+n_per_win] - v_arr[i]
            out.append((lo, hi, gain))
        return out

    print("\nTop 10 OSM 4K-ts gain windows:")
    for lo, hi, g in sorted(window_gains(osm_pnl), key=lambda x: -x[2])[:10]:
        # What's OSM mid doing in this window?
        subset = [m for t, _, _, m in osm_book if lo <= t <= hi and m is not None]
        mid_range = f"{min(subset):.1f}..{max(subset):.1f}" if subset else "n/a"
        mid_start = next((m for t, _, _, m in osm_book if t >= lo and m is not None), None)
        mid_end_list = [m for t, _, _, m in osm_book if t <= hi and m is not None]
        mid_end = mid_end_list[-1] if mid_end_list else None
        drift = mid_end - mid_start if mid_start is not None and mid_end is not None else 0
        print(f"  ts=[{lo:>5d}..{hi:>5d}]  gain=${g:>7.1f}  mid_range={mid_range}  drift={drift:+.1f}")

    print("\nTop 10 PEP 4K-ts gain windows:")
    for lo, hi, g in sorted(window_gains(pep_pnl), key=lambda x: -x[2])[:10]:
        subset = [m for t, _, _, m in pep_book if lo <= t <= hi and m is not None]
        mid_range = f"{min(subset):.1f}..{max(subset):.1f}" if subset else "n/a"
        mid_start = next((m for t, _, _, m in pep_book if t >= lo and m is not None), None)
        mid_end_list = [m for t, _, _, m in pep_book if t <= hi and m is not None]
        mid_end = mid_end_list[-1] if mid_end_list else None
        drift = mid_end - mid_start if mid_start is not None and mid_end is not None else 0
        print(f"  ts=[{lo:>5d}..{hi:>5d}]  gain=${g:>7.1f}  mid_range={mid_range}  drift={drift:+.1f}")

    # Specific target windows
    print("\n\nTarget windows (claimed step-ups):")
    for lo, hi, name in [(34000, 41000, 'Window 1'), (76000, 83000, 'Window 2')]:
        osm_lo = next((v for t, v in osm_pnl if t >= lo), osm_pnl[0][1])
        osm_hi = next((v for t, v in osm_pnl if t >= hi), osm_pnl[-1][1])
        pep_lo = next((v for t, v in pep_pnl if t >= lo), pep_pnl[0][1])
        pep_hi = next((v for t, v in pep_pnl if t >= hi), pep_pnl[-1][1])
        print(f"\n  {name}: ts={lo}..{hi}")
        print(f"    OSM gain: ${osm_hi - osm_lo:+.2f}")
        print(f"    PEP gain: ${pep_hi - pep_lo:+.2f}")
        # Mid moves
        osm_mid_lo = next((m for t, _, _, m in osm_book if t >= lo and m is not None), None)
        osm_mid_hi_list = [m for t, _, _, m in osm_book if t <= hi and m is not None]
        osm_mid_hi = osm_mid_hi_list[-1] if osm_mid_hi_list else None
        pep_mid_lo = next((m for t, _, _, m in pep_book if t >= lo and m is not None), None)
        pep_mid_hi_list = [m for t, _, _, m in pep_book if t <= hi and m is not None]
        pep_mid_hi = pep_mid_hi_list[-1] if pep_mid_hi_list else None
        print(f"    OSM mid: {osm_mid_lo} → {osm_mid_hi}  (Δ {osm_mid_hi - osm_mid_lo if osm_mid_lo and osm_mid_hi else 'n/a':+.1f})")
        print(f"    PEP mid: {pep_mid_lo} → {pep_mid_hi}  (Δ {pep_mid_hi - pep_mid_lo if pep_mid_lo and pep_mid_hi else 'n/a':+.1f})")


if __name__ == "__main__":
    main()
