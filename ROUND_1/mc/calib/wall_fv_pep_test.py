"""Does wall_fv help PEP too? (PEP already uses _estimate_fv_wall natively for fv.)

PEP trading already computes wall-FV in its _trade_pep flow (see line ~215).
So this is a no-op for PEP. This test confirms that — no PEP flag needed.
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from parametric_trader import make_trader
from server_book_replay_v2 import run_server_session_v2
from training_book_replay_v2 import run_training_session_v2


# Best candidate so far
base = {"use_wall_fv": True, "quote_edge": 22}
pep = {"accumulate_threshold": 65, "cooldown_up": 0}

def score(osm, pep):
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
    return o_li, p_li, tr


# With all current wins
o_li, p_li, tr = score(base, pep)
print("Final candidate: wall_fv + e22 + t65 + cu0")
print(f"  v2 live: OSM={o_li:.0f} PEP={p_li:.0f} TOT={o_li+p_li:.0f}")
print(f"  training per-day: {[int(x) for x in tr]}  avg={sum(tr)/3:.0f}")

# Baseline
b_o, b_p, b_tr = score({}, {})
print(f"\nBaseline 127989: v2_live={b_o+b_p:.0f}  training avg={sum(b_tr)/3:.0f}")

d_live = (o_li + p_li) - (b_o + b_p)
d_tr = sum(tr)/3 - sum(b_tr)/3
print(f"\nΔ_live={d_live:+.0f}  Δ_training_avg={d_tr:+.0f}")
print(f"\nServer expectation: baseline got 10721; expected new = 10721 + {d_live:.0f} = {10721 + d_live:.0f}")
print(f"(Training-based estimate: +{d_tr:.0f}/day on 10000-tick session; live is 1000-ticks so ~+{d_tr/10:.0f})")
