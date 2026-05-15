"""Check final position + cash vs mark-to-FV at wide edges.

If wide-edge PnL comes from cash (realized), it's reliable.
If it comes from mark-to-FV of held inventory, it's illusory (dependent on end mid).
"""
from __future__ import annotations
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from parametric_trader import make_trader
from server_book_replay import run_server_session


def run(edge, n=30):
    cash_vals = []
    pos_vals = []
    fv_vals = []
    pnl_vals = []
    for s in range(n):
        t = make_trader(osm={"quote_edge": edge})
        r = run_server_session(t, "ASH_COATED_OSMIUM", seed=s)
        cash_vals.append(r.cash)
        pos_vals.append(r.final_pos)
        fv_vals.append(r.final_fv)
        pnl_vals.append(r.pnl)
    return cash_vals, pos_vals, fv_vals, pnl_vals


def main():
    print(f"{'edge':>4}  {'cash':>8}  {'σ_cash':>6}  {'pos':>5}  "
          f"{'σ_pos':>5}  {'fv':>6}  {'pnl':>6}  {'σ_pnl':>6}")
    for e in [12, 22, 40, 100, 150]:
        c, p, fv, pnl = run(e, n=30)
        print(f"{e:4d}  {statistics.mean(c):8.0f}  {statistics.stdev(c):6.0f}  "
              f"{statistics.mean(p):5.1f}  {statistics.stdev(p):5.1f}  "
              f"{statistics.mean(fv):6.1f}  {statistics.mean(pnl):6.0f}  "
              f"{statistics.stdev(pnl):6.0f}")


if __name__ == "__main__":
    main()
