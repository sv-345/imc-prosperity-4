"""Validate candidates on training days -2, -1, 0. Fully deterministic.

A real improvement must beat baseline on ALL 3 days. This is our strongest
cross-session test since each day has independent bot trajectories.
"""
from __future__ import annotations
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from parametric_trader import make_trader
from training_book_replay import run_training_session


def run_candidate(osm_params, pep_params):
    totals = {}
    for day in ["-2", "-1", "0"]:
        t = make_trader(osm=osm_params, pep=pep_params)
        osm = run_training_session(t, "ASH_COATED_OSMIUM", day).pnl
        t = make_trader(osm=osm_params, pep=pep_params)
        pep = run_training_session(t, "INTARIAN_PEPPER_ROOT", day).pnl
        totals[day] = {"osm": osm, "pep": pep, "tot": osm + pep}
    return totals


def main():
    candidates = [
        ("baseline",    {}, {}),
        # Best symmetric candidates (anchor)
        ("e22+t62",     {"quote_edge": 22}, {"accumulate_threshold": 62}),
        ("e22+t65",     {"quote_edge": 22}, {"accumulate_threshold": 65}),
        # Asymmetric OSM edge
        ("bE22/sE18",   {"buy_edge": 22, "sell_edge": 18}, {}),
        ("bE18/sE22",   {"buy_edge": 18, "sell_edge": 22}, {}),
        ("bE22/sE12",   {"buy_edge": 22, "sell_edge": 12}, {}),
        ("bE12/sE22",   {"buy_edge": 12, "sell_edge": 22}, {}),
        # Position skewing (symmetric e=22)
        ("e22+sk.05",   {"quote_edge": 22, "skew_per_pos": 0.05}, {}),
        ("e22+sk.10",   {"quote_edge": 22, "skew_per_pos": 0.10}, {}),
        ("e22+sk.15",   {"quote_edge": 22, "skew_per_pos": 0.15}, {}),
        ("e22+sk-.05",  {"quote_edge": 22, "skew_per_pos": -0.05}, {}),  # reverse (build position)
        # Combined: e22+t62 with skew
        ("22t62+sk.10", {"quote_edge": 22, "skew_per_pos": 0.10}, {"accumulate_threshold": 62}),
        ("22t62+sk.15", {"quote_edge": 22, "skew_per_pos": 0.15}, {"accumulate_threshold": 62}),
        # Min-inside tweaks
        ("e22+mi10",    {"quote_edge": 22, "min_inside_qty": 10}, {}),
        ("e22+mi25",    {"quote_edge": 22, "min_inside_qty": 25}, {}),
        ("e22+mi40",    {"quote_edge": 22, "min_inside_qty": 40}, {}),
    ]
    b = run_candidate({}, {})
    print(f"baseline:")
    print(f"  day={'-2':>3} OSM={b['-2']['osm']:6.0f} PEP={b['-2']['pep']:6.0f} TOT={b['-2']['tot']:6.0f}")
    print(f"  day={'-1':>3} OSM={b['-1']['osm']:6.0f} PEP={b['-1']['pep']:6.0f} TOT={b['-1']['tot']:6.0f}")
    print(f"  day={' 0':>3} OSM={b['0']['osm']:6.0f} PEP={b['0']['pep']:6.0f} TOT={b['0']['tot']:6.0f}")
    avg_baseline = sum(b[d]['tot'] for d in b) / 3
    print(f"  avg = {avg_baseline:.0f}\n")

    print(f"{'candidate':>10}  {'d-2':>7}  {'d-1':>7}  {'d0':>7}  {'avg Δ':>7}  verdict")
    for name, osm, pep in candidates:
        if name == "baseline":
            continue
        res = run_candidate(osm, pep)
        diffs = [res[d]['tot'] - b[d]['tot'] for d in ["-2", "-1", "0"]]
        signs = [">" if d > 0 else ("<" if d < 0 else "=") for d in diffs]
        all_pos = all(d > 0 for d in diffs)
        avg_d = sum(diffs) / 3
        verdict = "ROBUST" if all_pos else (
            "1/3" if sum(1 for d in diffs if d > 0) == 1 else
            "2/3" if sum(1 for d in diffs if d > 0) == 2 else "0/3"
        )
        print(f"{name:>10}  {diffs[0]:+7.0f}  {diffs[1]:+7.0f}  {diffs[2]:+7.0f}  {avg_d:+7.0f}  {verdict}")


if __name__ == "__main__":
    main()
