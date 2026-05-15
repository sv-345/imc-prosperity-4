"""Validate combined-tweak candidates on 3-day training + 50-seed live MC.
Goal: find the all-weather best candidate combining OSM edge, PEP thr, PEP insider tweaks.
"""
from __future__ import annotations
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from parametric_trader import make_trader
from server_book_replay import run_server_session
from training_book_replay import run_training_session


def tr_day(osm, pep, day):
    t = make_trader(osm=osm, pep=pep)
    osm_p = run_training_session(t, "ASH_COATED_OSMIUM", day).pnl
    t = make_trader(osm=osm, pep=pep)
    pep_p = run_training_session(t, "INTARIAN_PEPPER_ROOT", day).pnl
    return osm_p + pep_p


def tr_all(osm, pep):
    return [tr_day(osm, pep, d) for d in ["-2", "-1", "0"]]


def live_paired(osm, pep, base_osm, base_pep, n=50):
    my = []
    base = []
    for s in range(n):
        t = make_trader(osm=osm, pep=pep)
        t1 = run_server_session(t, "ASH_COATED_OSMIUM", seed=s).pnl
        t = make_trader(osm=osm, pep=pep)
        t2 = run_server_session(t, "INTARIAN_PEPPER_ROOT", seed=s).pnl
        my.append(t1 + t2)
        t = make_trader(osm=base_osm, pep=base_pep)
        t1 = run_server_session(t, "ASH_COATED_OSMIUM", seed=s).pnl
        t = make_trader(osm=base_osm, pep=base_pep)
        t2 = run_server_session(t, "INTARIAN_PEPPER_ROOT", seed=s).pnl
        base.append(t1 + t2)
    diffs = [m - b for m, b in zip(my, base)]
    return (statistics.mean(my), statistics.mean(base),
            statistics.mean(diffs), sum(1 for d in diffs if d > 0))


def main():
    candidates = [
        ("baseline",           {}, {}),
        ("e22+t65",            {"quote_edge": 22}, {"accumulate_threshold": 65}),
        ("e22+t65+iq10",       {"quote_edge": 22}, {"accumulate_threshold": 65, "insider_qty": 10}),
        ("e22+t65+cu0",        {"quote_edge": 22}, {"accumulate_threshold": 65, "cooldown_up": 0}),
        ("e22+t65+iq10+cu0",   {"quote_edge": 22}, {"accumulate_threshold": 65, "insider_qty": 10, "cooldown_up": 0}),
        ("e22+t62+cu0+iq10",   {"quote_edge": 22}, {"accumulate_threshold": 62, "cooldown_up": 0, "insider_qty": 10}),
        ("e22+t65+swap_bids",  {"quote_edge": 22}, {"accumulate_threshold": 65, "sweep_bids_above_fv": True}),
        ("e22+t65+baf6",       {"quote_edge": 22}, {"accumulate_threshold": 65, "buy_above_fv": 6}),
        ("e16+t65",            {"quote_edge": 16}, {"accumulate_threshold": 65}),
        ("e16+t65+iq10+cu0",   {"quote_edge": 16}, {"accumulate_threshold": 65, "insider_qty": 10, "cooldown_up": 0}),
    ]

    base = tr_all({}, {})
    print(f"baseline training: d-2={base[0]:.0f} d-1={base[1]:.0f} d0={base[2]:.0f} "
          f"avg={sum(base)/3:.0f}")

    print(f"\n{'candidate':>20}  {'d-2':>5}  {'d-1':>5}  {'d0':>5}  {'tr_avg':>6}  "
          f"{'live_Δ':>7}  {'wins':>5}")
    for name, osm, pep in candidates:
        if name == "baseline":
            continue
        tr = tr_all(osm, pep)
        diffs_tr = [t - b for t, b in zip(tr, base)]
        avg_tr = sum(diffs_tr) / 3
        li_my, li_base, li_d, wins = live_paired(osm, pep, {}, {}, n=50)
        print(f"{name:>20}  {diffs_tr[0]:+5.0f}  {diffs_tr[1]:+5.0f}  {diffs_tr[2]:+5.0f}  "
              f"{avg_tr:+6.0f}  {li_d:+7.0f}  {wins:2d}/50")


if __name__ == "__main__":
    main()
