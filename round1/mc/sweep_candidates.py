"""Sweep candidate traders against R1 training data.

Tests each OSMIUM variant × each PEPPER variant on each training day,
reports per-day and average PnL. Shows min-day (DRO) and avg (EV) for
each leg independently.
"""
from __future__ import annotations
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from training_replay import run_replay
from candidate_traders import variants, ParametricTrader

DAYS = (-2, -1, 0)
MAX_TICKS = None  # full day
N_SEEDS = 1  # seed inside run_replay; sweep is per-config


def main():
    osm_factories, pep_factories = variants()
    # Build a pairing: osmium vs osm_base; pepper vs pep_base (holding other leg fixed)
    results = {}  # (osm_name, pep_name) -> {day: total_pnl, ...}

    # Strategy: test each OSMIUM variant with pep_base, then each PEPPER variant with osm_base.
    # Then test the best combo.
    t0 = time.time()
    print(f"Sweep at {time.strftime('%H:%M:%S')}")

    # --- OSMIUM sweep (holding PEPPER at base) ---
    print("\n== OSMIUM variants × pep_base ==")
    for oname, ofac in osm_factories.items():
        osm_fn = ofac()
        day_osm_pnl = {}
        day_pep_pnl = {}
        for day in DAYS:
            trader = ParametricTrader(osm_fn, pep_factories["pep_base"]())
            pnl = run_replay(day, trader, max_ticks=MAX_TICKS)
            day_osm_pnl[day] = pnl.get("ASH_COATED_OSMIUM", 0)
            day_pep_pnl[day] = pnl.get("INTARIAN_PEPPER_ROOT", 0)
        osm_min = min(day_osm_pnl.values())
        osm_avg = sum(day_osm_pnl.values()) / len(DAYS)
        pep_min = min(day_pep_pnl.values())
        pep_avg = sum(day_pep_pnl.values()) / len(DAYS)
        print(f"  {oname:15s} OSM d[-2,-1,0]=({day_osm_pnl[-2]:+7.0f}, {day_osm_pnl[-1]:+7.0f}, {day_osm_pnl[0]:+7.0f}) "
              f"min={osm_min:+7.0f} avg={osm_avg:+7.0f} | PEP avg={pep_avg:+7.0f}")

    # --- PEPPER sweep (holding OSMIUM at base) ---
    print("\n== PEPPER variants × osm_base ==")
    osm_fn_base = osm_factories["osm_base"]()
    for pname, pfac in pep_factories.items():
        day_pep_pnl = {}
        day_osm_pnl = {}
        for day in DAYS:
            trader = ParametricTrader(osm_fn_base, pfac())
            pnl = run_replay(day, trader, max_ticks=MAX_TICKS)
            day_pep_pnl[day] = pnl.get("INTARIAN_PEPPER_ROOT", 0)
            day_osm_pnl[day] = pnl.get("ASH_COATED_OSMIUM", 0)
        pep_min = min(day_pep_pnl.values())
        pep_avg = sum(day_pep_pnl.values()) / len(DAYS)
        osm_avg = sum(day_osm_pnl.values()) / len(DAYS)
        print(f"  {pname:15s} PEP d[-2,-1,0]=({day_pep_pnl[-2]:+7.0f}, {day_pep_pnl[-1]:+7.0f}, {day_pep_pnl[0]:+7.0f}) "
              f"min={pep_min:+7.0f} avg={pep_avg:+7.0f} | OSM avg={osm_avg:+7.0f}")

    print(f"\nSweep total time: {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
