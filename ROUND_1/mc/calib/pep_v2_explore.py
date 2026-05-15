"""Explore PEP structural params using v2 deterministic replay.

PEP has 6x more SELL flow than BUY flow at 127989 → biased to buying. Want to
find levers that better capture this asymmetry.
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from parametric_trader import make_trader
from server_book_replay_v2 import run_server_session_v2
from training_book_replay_v2 import run_training_session_v2


def pep_scores(pep):
    """Return (live_pnl, tr_d-2, tr_d-1, tr_d0)."""
    t = make_trader(pep=pep)
    li = run_server_session_v2(t, "INTARIAN_PEPPER_ROOT").pnl
    tr = []
    for d in ["-2", "-1", "0"]:
        t = make_trader(pep=pep)
        tr.append(run_training_session_v2(t, "INTARIAN_PEPPER_ROOT", d).pnl)
    return li, tr


def main():
    base_pep = {"accumulate_threshold": 65, "cooldown_up": 0}  # our current best PEP config
    b_li, b_tr = pep_scores(base_pep)
    print(f"base (t65+cu0): live={b_li:.0f}  tr={b_tr[0]:.0f}/{b_tr[1]:.0f}/{b_tr[2]:.0f}")
    print()

    def row(name, p_overrides):
        p = {**base_pep, **p_overrides}
        li, tr = pep_scores(p)
        dli = li - b_li
        dtr = [t - bb for t, bb in zip(tr, b_tr)]
        print(f"{name:>30}  live={li:.0f} ({dli:+5.0f})  "
              f"tr={tr[0]:.0f}/{tr[1]:.0f}/{tr[2]:.0f}  "
              f"trΔ={dtr[0]:+5.0f}/{dtr[1]:+5.0f}/{dtr[2]:+5.0f}")

    print("# accumulate_bid_offset")
    for v in [0, 2, 3]:
        row(f"acc_bo={v}", {"accumulate_bid_offset": v})

    print("\n# bid_offset (hold)")
    for v in [0, 2]:
        row(f"bid_off={v}", {"bid_offset": v})

    print("\n# sell_offset (hold)")
    for v in [0, 2]:
        row(f"sell_off={v}", {"sell_offset": v})

    print("\n# buy_above_fv")
    for v in [5, 10, 12, 15]:
        row(f"baf={v}", {"buy_above_fv": v})

    print("\n# sweep_bids_above_fv (symmetric sweep)")
    row("sweep_bids True", {"sweep_bids_above_fv": True})
    row("sweep_bids +buf0", {"sweep_bids_above_fv": True, "sweep_above_fv_buffer": 0})
    row("sweep_bids +buf5", {"sweep_bids_above_fv": True, "sweep_above_fv_buffer": 5})

    print("\n# insider tuning")
    for iq in [4, 6, 10, 15]:
        row(f"insider_qty={iq}", {"insider_qty": iq})
    for isq in [4, 12, 20, 30]:
        row(f"insider_sell_qty={isq}", {"insider_sell_qty": isq})
    for dsq in [6, 10, 12]:
        row(f"default_sell_qty={dsq}", {"default_sell_qty": dsq})
    for cd in [-20, -30, -50]:
        row(f"cooldown_down={cd}", {"cooldown_down": cd})


if __name__ == "__main__":
    main()
