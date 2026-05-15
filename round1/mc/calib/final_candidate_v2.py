"""Final candidate: wall_fv + ema + e22 + t65 + cu0."""
from __future__ import annotations
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from parametric_trader import make_trader
from server_book_replay_v2 import run_server_session_v2
from training_book_replay_v2 import run_training_session_v2


def eval_cand(name, osm, pep):
    t = make_trader(osm=osm, pep=pep)
    o_li = run_server_session_v2(t, "ASH_COATED_OSMIUM").pnl
    t = make_trader(osm=osm, pep=pep)
    p_li = run_server_session_v2(t, "INTARIAN_PEPPER_ROOT").pnl
    tr = []
    for d in ["-2", "-1", "0"]:
        t = make_trader(osm=osm, pep=pep)
        o = run_training_session_v2(t, "ASH_COATED_OSMIUM", d).pnl
        t = make_trader(osm=osm, pep=pep)
        p = run_training_session_v2(t, "INTARIAN_PEPPER_ROOT", d).pnl
        tr.append(o + p)
    return name, o_li, p_li, tr


b_name, b_oli, b_pli, b_tr = eval_cand("baseline", {}, {})
print(f"{'name':>30}  {'osm':>5} {'pep':>5} {'tot':>5}  {'Δ':>5}  {'tr_avg':>7} {'Δ':>6}")
print(f"{b_name:>30}  {b_oli:5.0f} {b_pli:5.0f} {b_oli+b_pli:5.0f}  "
      f"{0:+5d}  {sum(b_tr)/3:7.0f}  {0:+6d}")
print()

cands = [
    ("e22+t65+cu0 (prev-best)",       {"quote_edge": 22},                {"accumulate_threshold": 65, "cooldown_up": 0}),
    ("wall_fv",                        {"use_wall_fv": True},              {}),
    ("wall_fv+e22+t65+cu0",            {"use_wall_fv": True, "quote_edge": 22}, {"accumulate_threshold": 65, "cooldown_up": 0}),
    ("wall_fv+ema5",                   {"use_wall_fv": True, "wall_fv_ema_alpha": 0.5}, {}),
    ("wall_fv+ema5+e22",               {"use_wall_fv": True, "wall_fv_ema_alpha": 0.5, "quote_edge": 22}, {}),
    ("wall_fv+ema5+e22+t65+cu0",       {"use_wall_fv": True, "wall_fv_ema_alpha": 0.5, "quote_edge": 22}, {"accumulate_threshold": 65, "cooldown_up": 0}),
    ("wall_fv+ema3+e22+t65+cu0",       {"use_wall_fv": True, "wall_fv_ema_alpha": 0.3, "quote_edge": 22}, {"accumulate_threshold": 65, "cooldown_up": 0}),
]

for name, osm, pep in cands:
    _, o, p, tr = eval_cand(name, osm, pep)
    dli = o + p - (b_oli + b_pli)
    dtr = sum(tr)/3 - sum(b_tr)/3
    print(f"{name:>30}  {o:5.0f} {p:5.0f} {o+p:5.0f}  {dli:+5.0f}  "
          f"{sum(tr)/3:7.0f}  {dtr:+6.0f}")
