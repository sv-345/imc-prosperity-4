"""PEP hits pos=80 in 8 ticks and holds. Hold mode sells 8/tick — reducing trend exposure.
Test default_sell_qty=0: never sell. Just accumulate and hold."""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from parametric_trader import make_trader
from server_book_replay_v2 import run_server_session_v2
from training_book_replay_v2 import run_training_session_v2


def score(pep):
    t = make_trader(pep=pep)
    li = run_server_session_v2(t, "INTARIAN_PEPPER_ROOT").pnl
    tr = []
    for d in ["-2", "-1", "0"]:
        t = make_trader(pep=pep)
        tr.append(run_training_session_v2(t, "INTARIAN_PEPPER_ROOT", d).pnl)
    return li, tr


base = {"accumulate_threshold": 65, "cooldown_up": 0}
b_li, b_tr = score(base)
print(f"base (t65+cu0): live={b_li:.0f}  tr={[int(x) for x in b_tr]}  avg={sum(b_tr)/3:.0f}")

for sq in [0, 2, 4, 6, 8]:
    p = {**base, "default_sell_qty": sq}
    li, tr = score(p)
    dli = li - b_li
    dtr_avg = sum(tr)/3 - sum(b_tr)/3
    print(f"default_sell_qty={sq:2d}: live={li:6.0f} (Δ{dli:+5.0f})  "
          f"tr_avg={sum(tr)/3:7.0f} (Δ{dtr_avg:+5.0f})  "
          f"tr={[int(x) for x in tr]}")

# Also: combine with t=80 (never switch to hold, always accumulate)
print("\n# accumulate_threshold variants (with sell_qty=0):")
for thr in [55, 60, 65, 70, 75, 80, 85]:
    p = {"accumulate_threshold": thr, "cooldown_up": 0, "default_sell_qty": 0}
    li, tr = score(p)
    print(f"thr={thr:2d}+sq=0: live={li:6.0f}  tr_avg={sum(tr)/3:7.0f}  "
          f"tr={[int(x) for x in tr]}")
