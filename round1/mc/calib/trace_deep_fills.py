"""Trace EXACT mechanism of the 20 'deep' sell fills.

Patch _cross_trader_orders and _apply_taker to log every fill's tick+context.
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from parametric_trader import make_trader
import server_book_replay as sbr
from server_book_replay import run_server_session
from synth_replay import Fill

orig_cross = sbr._cross_trader_orders
orig_taker = sbr._apply_taker


def traced_cross(orders, book_buys, book_sells, strat_buys, strat_sells,
                  position, limit, ts):
    fills, pos, cash = orig_cross(orders, book_buys, book_sells,
                                   strat_buys, strat_sells, position, limit, ts)
    for f in fills:
        if f.side == "SELL" and f.price >= 10013:
            print(f"  ts={ts} CROSS sell {f.qty}@{f.price}  book_bids={sorted([(p,v) for p,v in book_buys.items() if p >= 10010], reverse=True)}")
        elif f.side == "BUY" and f.price <= 9987:
            print(f"  ts={ts} CROSS buy {f.qty}@{f.price}  book_asks={sorted([(p,v) for p,v in book_sells.items() if p <= 9990])}")
    return fills, pos, cash


def traced_taker(taker, book_buys, book_sells, strat_buys, strat_sells,
                  position, limit, ts):
    before_sells = dict(strat_sells)
    before_buys = dict(strat_buys)
    fills, pos, cash = orig_taker(taker, book_buys, book_sells,
                                    strat_buys, strat_sells, position, limit, ts)
    for f in fills:
        if f.side == "SELL" and f.price >= 10013:
            print(f"  ts={ts} TAKER({taker.side}) hit strat_sell {f.qty}@{f.price} "
                  f"strat_pre={sorted(before_sells.items())}")
        elif f.side == "BUY" and f.price <= 9987:
            print(f"  ts={ts} TAKER({taker.side}) hit strat_buy {f.qty}@{f.price}")
    return fills, pos, cash


sbr._cross_trader_orders = traced_cross
sbr._apply_taker = traced_taker


def main():
    t = make_trader(osm={"quote_edge": 22})
    print("=== edge=22 seed=0 trace of deep fills (price>=10013 or <=9987) ===")
    r = run_server_session(t, "ASH_COATED_OSMIUM", seed=0)
    print(f"\nfinal PnL={r.pnl:.0f}  fills={len(r.fills)}")


if __name__ == "__main__":
    main()
