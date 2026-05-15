"""Analyze iter23's PnL trajectory in the step-up windows and hunt for
event type that explains them.
"""
from __future__ import annotations
import json, io, csv, pathlib
import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
LOG = pathlib.Path('/tmp/prosperity_logs/303257/312201.json')  # iter23 baseline 1
LOG2 = pathlib.Path('/tmp/prosperity_logs/303280/312224.json')  # iter23 baseline 2


def load(log_path):
    d = json.load(open(log_path))
    # PnL graphLog
    gl = d['graphLog']
    pnl = []
    for l in gl.split('\n'):
        if not l or l.startswith('timestamp'): continue
        parts = l.split(';')
        pnl.append((int(parts[0]), float(parts[1])))
    # activitiesLog — book snapshots
    act = csv.DictReader(io.StringIO(d['activitiesLog']), delimiter=';')
    rows = []
    for r in act:
        try:
            r['timestamp'] = int(r['timestamp'])
            rows.append(r)
        except: pass
    return d, pnl, rows


def main():
    d, pnl, rows = load(LOG)
    day = rows[0]['day'] if rows else '?'
    print(f"iter23 baseline 303257: day={day}, final profit={d['profit']:.2f}")

    # PnL slope in sliding 2K-tick windows
    ts_arr = np.array([t for t, _ in pnl])
    pnl_arr = np.array([v for _, v in pnl])
    window = 20  # 20 × 200ts = 4000 ts per window
    slopes = []
    for i in range(len(pnl_arr) - window):
        dt = ts_arr[i+window] - ts_arr[i]
        dp = pnl_arr[i+window] - pnl_arr[i]
        slopes.append((ts_arr[i], ts_arr[i+window], dp, dp/dt*1000))  # per 1000 ts
    # Sort by slope to find concentrated gain windows
    slopes_sorted = sorted(slopes, key=lambda x: -x[2])
    print("\nTop 10 highest-gain 4K-ts windows in iter23:")
    for lo, hi, dp, rate in slopes_sorted[:10]:
        print(f"  ts=[{lo:>5d}..{hi:>5d}]  gain=${dp:>7.1f}  rate=${rate:>5.1f}/1K")

    # Check specific target windows
    targets = [(34000, 41000, "Window 1 (claimed)"), (76000, 83000, "Window 2 (claimed)")]
    print("\nTarget window PnL gains:")
    for lo, hi, name in targets:
        pnl_lo = next((v for t, v in pnl if t == lo), None)
        pnl_hi = next((v for t, v in pnl if t == hi), None)
        if pnl_lo is not None and pnl_hi is not None:
            print(f"  {name}: ts={lo}..{hi}, iter23 gain = ${pnl_hi-pnl_lo:.2f}")

    # Compare to baseline #2
    d2, pnl2, rows2 = load(LOG2)
    print(f"\niter23 baseline 303280 (2nd sample): day={rows2[0]['day']}, final profit={d2['profit']:.2f}")
    for lo, hi, name in targets:
        plo = next((v for t, v in pnl2 if t == lo), None)
        phi = next((v for t, v in pnl2 if t == hi), None)
        if plo is not None and phi is not None:
            print(f"  {name}: gain=${phi-plo:.2f}")

    # Now characterize the market state in those windows using the activitiesLog
    print("\n\n=== MARKET STATE IN TARGET WINDOWS (sample 1) ===")
    for lo, hi, name in targets:
        print(f"\n--- {name}: ts={lo}..{hi} ---")
        for product in ("ASH_COATED_OSMIUM", "INTARIAN_PEPPER_ROOT"):
            subset = [r for r in rows if r['product'] == product and lo <= r['timestamp'] <= hi]
            if not subset: continue
            mids = [float(r['mid_price']) for r in subset if r.get('mid_price')]
            bid1 = [float(r['bid_price_1']) for r in subset if r.get('bid_price_1')]
            ask1 = [float(r['ask_price_1']) for r in subset if r.get('ask_price_1')]
            if mids:
                print(f"  {product}: mid range {min(mids):.1f}..{max(mids):.1f}, "
                      f"start->end {mids[0]:.1f} → {mids[-1]:.1f} (Δ={mids[-1]-mids[0]:+.1f}), "
                      f"std={np.std(mids):.2f}")

    # Save PnL trajectory
    out = ROOT / "exploration4" / "iter23_pnl_303257.csv"
    with out.open('w') as f:
        f.write('ts,pnl\n')
        for t, v in pnl:
            f.write(f'{t},{v:.4f}\n')
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
