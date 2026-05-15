"""Evaluate top candidates using server_book_replay_v2 (deterministic, no RNG).

Since v2 is deterministic, each candidate has a single PnL number on each
product — no variance, no seed sweep. This is the cleanest evaluation we have.

Also runs training_book_replay_v2 to get 3-day deterministic training PnL.
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from parametric_trader import make_trader
from server_book_replay_v2 import run_server_session_v2
from training_book_replay_v2 import run_training_session_v2


def score(osm, pep):
    # Live (v2): 1 session, deterministic
    t = make_trader(osm=osm, pep=pep)
    li_osm = run_server_session_v2(t, "ASH_COATED_OSMIUM").pnl
    t = make_trader(osm=osm, pep=pep)
    li_pep = run_server_session_v2(t, "INTARIAN_PEPPER_ROOT").pnl
    # Training (v2): 3 days, each deterministic
    tr_days = []
    for d in ["-2", "-1", "0"]:
        t = make_trader(osm=osm, pep=pep)
        osm_p = run_training_session_v2(t, "ASH_COATED_OSMIUM", d).pnl
        t = make_trader(osm=osm, pep=pep)
        pep_p = run_training_session_v2(t, "INTARIAN_PEPPER_ROOT", d).pnl
        tr_days.append(osm_p + pep_p)
    return li_osm, li_pep, tr_days


def main():
    candidates = [
        ("baseline",       {}, {}),
        # OSM edge
        ("edge=14",        {"quote_edge": 14}, {}),
        ("edge=16",        {"quote_edge": 16}, {}),
        ("edge=22",        {"quote_edge": 22}, {}),
        # PEP thr
        ("thr=60",         {}, {"accumulate_threshold": 60}),
        ("thr=65",         {}, {"accumulate_threshold": 65}),
        ("thr=55",         {}, {"accumulate_threshold": 55}),
        # Combined
        ("e16+t60",        {"quote_edge": 16}, {"accumulate_threshold": 60}),
        ("e22+t60",        {"quote_edge": 22}, {"accumulate_threshold": 60}),
        ("e22+t65",        {"quote_edge": 22}, {"accumulate_threshold": 65}),
        ("e22+t55",        {"quote_edge": 22}, {"accumulate_threshold": 55}),
        ("e22+t65+cu0",    {"quote_edge": 22}, {"accumulate_threshold": 65, "cooldown_up": 0}),
        ("e22+t60+cu0",    {"quote_edge": 22}, {"accumulate_threshold": 60, "cooldown_up": 0}),
        # Adaptive
        ("e12+bon10+t65",  {"quote_edge": 12, "onesided_edge_bonus": 10}, {"accumulate_threshold": 65, "cooldown_up": 0}),
        ("e12+bon20+t65",  {"quote_edge": 12, "onesided_edge_bonus": 20}, {"accumulate_threshold": 65, "cooldown_up": 0}),
    ]

    b_li_o, b_li_p, b_tr = score({}, {})
    b_li_t = b_li_o + b_li_p
    b_tr_avg = sum(b_tr) / 3
    print(f"baseline: live OSM={b_li_o:.0f} PEP={b_li_p:.0f} TOT={b_li_t:.0f}  "
          f"training avg={b_tr_avg:.0f}  d-2/d-1/d0={b_tr[0]:.0f}/{b_tr[1]:.0f}/{b_tr[2]:.0f}")

    print(f"\n{'candidate':>18}  {'li_OSM':>6}  {'li_PEP':>6}  {'li_TOT':>6}  {'li_Δ':>6}  "
          f"{'tr_d-2':>6}  {'tr_d-1':>6}  {'tr_d0':>6}  {'tr_avg_Δ':>8}")
    for name, osm, pep in candidates:
        if name == "baseline":
            continue
        li_o, li_p, tr = score(osm, pep)
        li_t = li_o + li_p
        tr_diffs = [t - b for t, b in zip(tr, b_tr)]
        print(f"{name:>18}  {li_o:6.0f}  {li_p:6.0f}  {li_t:6.0f}  {li_t-b_li_t:+6.0f}  "
              f"{tr_diffs[0]:+6.0f}  {tr_diffs[1]:+6.0f}  {tr_diffs[2]:+6.0f}  "
              f"{sum(tr_diffs)/3:+8.0f}")


if __name__ == "__main__":
    main()
