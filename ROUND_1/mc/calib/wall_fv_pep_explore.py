"""Can wall_fv concepts help PEP too? PEP already uses wall_fv as primary.

What about EMA smoothing of wall_fv for PEP? Or PEP-specific FV improvements?
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from parametric_trader import make_trader
from server_book_replay_v2 import run_server_session_v2
from training_book_replay_v2 import run_training_session_v2


def score_pep(pep):
    t = make_trader(pep=pep)
    li = run_server_session_v2(t, "INTARIAN_PEPPER_ROOT").pnl
    tr = []
    for d in ["-2", "-1", "0"]:
        t = make_trader(pep=pep)
        tr.append(run_training_session_v2(t, "INTARIAN_PEPPER_ROOT", d).pnl)
    return li, tr


b_li, b_tr = score_pep({})
print(f"PEP baseline: live={b_li:.0f}  tr={[int(x) for x in b_tr]}  avg={sum(b_tr)/3:.0f}")
print()

# Test various PEP parameter tunings that haven't been deeply explored
print("# Offset tuning combinations")
for bo in [0, 1, 2]:
    for so in [0, 1, 2]:
        p = {"accumulate_threshold": 65, "cooldown_up": 0, "bid_offset": bo, "sell_offset": so}
        li, tr = score_pep(p)
        d = li - b_li
        dtr = sum(tr)/3 - sum(b_tr)/3
        print(f"  bo={bo} so={so}: live={li:.0f} (Δ{d:+4.0f})  tr_avg={sum(tr)/3:.0f} (Δ{dtr:+5.0f})")

print("\n# accumulate_bid_offset")
for abo in [0, 1, 2, 3]:
    p = {"accumulate_threshold": 65, "cooldown_up": 0, "accumulate_bid_offset": abo}
    li, tr = score_pep(p)
    d = li - b_li
    dtr = sum(tr)/3 - sum(b_tr)/3
    print(f"  abo={abo}: live={li:.0f} (Δ{d:+4.0f})  tr_avg={sum(tr)/3:.0f} (Δ{dtr:+5.0f})")

print("\n# buy_above_fv")
for baf in [5, 8, 10, 12, 15, 20]:
    p = {"accumulate_threshold": 65, "cooldown_up": 0, "buy_above_fv": baf}
    li, tr = score_pep(p)
    d = li - b_li
    dtr = sum(tr)/3 - sum(b_tr)/3
    print(f"  baf={baf}: live={li:.0f} (Δ{d:+4.0f})  tr_avg={sum(tr)/3:.0f} (Δ{dtr:+5.0f})")

print("\n# insider_qty variations (was tested with base, retry with t65+cu0)")
for iq in [4, 6, 8, 10, 15]:
    p = {"accumulate_threshold": 65, "cooldown_up": 0, "insider_qty": iq}
    li, tr = score_pep(p)
    d = li - b_li
    dtr = sum(tr)/3 - sum(b_tr)/3
    print(f"  iq={iq}: live={li:.0f} (Δ{d:+4.0f})  tr_avg={sum(tr)/3:.0f} (Δ{dtr:+5.0f})")
