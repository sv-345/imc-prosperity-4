"""Replay a strategy against the EXACT recorded R1 server book.

For each tick in server_state_round1.json:
  1. Construct the book from recorded bids/asks (each level is 100% bot)
  2. Run strategy → OrderIntent
  3. Phase 1: strategy crosses bot book (takeout)
  4. Phase 2: simulate taker flow from calibrated rate/qty distribution
              (the server data has no trade history for R1, so we sample)
  5. Mark-to-market using recorded FV

Final PnL is compared to submission 127989's reported per-product server PnL.

This is the most faithful validation because it uses the ACTUAL book the
server presented — only taker flow is still MC-sampled.
"""
from __future__ import annotations
import json
import random
import statistics
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent))
from mc_r1_v1 import OSMIUM, PEPPER, Book, Level, OrderIntent, TickContext, Fill
from strategies_r1 import make_osmium_stable, make_pepper_trending

DATA = Path(__file__).parent.parent / "data" / "server_state_round1.json"

SERVER_PNL = {
    "ASH_COATED_OSMIUM": 3143.66,
    "INTARIAN_PEPPER_ROOT": 7577.0,
}


def load_ticks(product):
    d = json.loads(DATA.read_text())
    return [t for t in d['ticks'] if t['product'] == product and t['fv'] is not None]


def build_book_from_record(tick):
    book = Book()
    for price, vol in tick['bids']:
        book.bids[int(price)] = Level(price=int(price), bot_vol=int(vol))
    for price, vol in tick['asks']:
        book.asks[int(price)] = Level(price=int(price), bot_vol=int(vol))
    return book


def recorded_l1(tick):
    """Return (bid_l1, ask_l1) prices from the recorded book, or None if absent.
    Used to clip taker fills to realistic prices (prevents MC from rewarding
    fallback-to-(fv±edge) quotes at absurd prices when book is one-sided)."""
    bid_l1 = max((int(p) for p, _ in tick['bids']), default=None)
    ask_l1 = min((int(p) for p, _ in tick['asks']), default=None)
    return bid_l1, ask_l1


class BookReplayer:
    def __init__(self, product_params, strategy, ticks, seed=0, position_limit=80):
        self.p = product_params
        self.strategy = strategy
        self.ticks_data = ticks
        self.rng = random.Random(seed)
        self.position_limit = position_limit
        self.position = 0
        self.cash = 0.0
        self.fills = []
        self.current_tick = 0
        self.book = None
        self.fv = 0.0

    def _apply_strategy(self, intent):
        # Phase 1: strategy orders cross the bot book
        for price, qty in intent.bids:
            qty_rem = qty
            max_buy = self.position_limit - self.position
            if max_buy <= 0: continue
            qty_rem = min(qty_rem, max_buy)
            ask_levels = [lv for lv in self.book.ask_levels_sorted() if lv.price <= price]
            for lv in ask_levels:
                if qty_rem <= 0: break
                take = min(qty_rem, lv.bot_vol)
                if take > 0:
                    lv.bot_vol -= take
                    qty_rem -= take
                    self.position += take
                    self.cash -= lv.price * take
                    self.fills.append(Fill(self.current_tick, "BUY", lv.price, take, "crossed_bot"))
                if lv.bot_vol == 0 and lv.strat_vol == 0:
                    del self.book.asks[lv.price]
            if qty_rem > 0:
                self.book.add_strat_vol("BID", price, qty_rem)

        for price, qty in intent.asks:
            qty_rem = qty
            max_sell = self.position_limit + self.position
            if max_sell <= 0: continue
            qty_rem = min(qty_rem, max_sell)
            bid_levels = [lv for lv in self.book.bid_levels_sorted() if lv.price >= price]
            for lv in bid_levels:
                if qty_rem <= 0: break
                take = min(qty_rem, lv.bot_vol)
                if take > 0:
                    lv.bot_vol -= take
                    qty_rem -= take
                    self.position -= take
                    self.cash += lv.price * take
                    self.fills.append(Fill(self.current_tick, "SELL", lv.price, take, "crossed_bot"))
                if lv.bot_vol == 0 and lv.strat_vol == 0:
                    del self.book.bids[lv.price]
            if qty_rem > 0:
                self.book.add_strat_vol("ASK", price, qty_rem)

    def _apply_taker(self):
        p = self.p
        if self.rng.random() >= p.taker_rate:
            return
        is_buy = self.rng.random() < p.taker_side_buy_frac
        target = "ASK" if is_buy else "BID"
        levels = self.book.ask_levels_sorted() if target == "ASK" else self.book.bid_levels_sorted()
        if not levels: return
        # Clip to realistic price band — takers shouldn't hit absurd quotes
        # that exploit one-sided-book fallbacks at fv ± huge_edge.
        band = self._taker_band
        if target == "ASK":
            levels = [lv for lv in levels if lv.price <= band[1]]
        else:
            levels = [lv for lv in levels if lv.price >= band[0]]
        if not levels: return
        lv = levels[0]
        qty = self.rng.randint(*p.taker_qty)
        # Consume L1: bot first
        bot_take = min(qty, lv.bot_vol)
        lv.bot_vol -= bot_take
        qty -= bot_take
        if qty > 0 and lv.strat_vol > 0:
            st = min(qty, lv.strat_vol)
            lv.strat_vol -= st
            qty -= st
            if is_buy:
                self.position -= st
                self.cash += lv.price * st
                self.fills.append(Fill(self.current_tick, "SELL", lv.price, st, "taker"))
            else:
                self.position += st
                self.cash -= lv.price * st
                self.fills.append(Fill(self.current_tick, "BUY", lv.price, st, "taker"))
        if lv.bot_vol == 0 and lv.strat_vol == 0:
            if target == "ASK": del self.book.asks[lv.price]
            else: del self.book.bids[lv.price]
        # Walk book for residual (respecting price band)
        if qty > 0:
            next_lvs = self.book.ask_levels_sorted() if target == "ASK" else self.book.bid_levels_sorted()
            band = self._taker_band
            if target == "ASK":
                next_lvs = [nl for nl in next_lvs if nl.price <= band[1]]
            else:
                next_lvs = [nl for nl in next_lvs if nl.price >= band[0]]
            for nl in next_lvs:
                if qty <= 0: break
                bt = min(qty, nl.bot_vol)
                nl.bot_vol -= bt
                qty -= bt
                if qty > 0 and nl.strat_vol > 0:
                    st = min(qty, nl.strat_vol)
                    nl.strat_vol -= st
                    qty -= st
                    if is_buy:
                        self.position -= st
                        self.cash += nl.price * st
                        self.fills.append(Fill(self.current_tick, "SELL", nl.price, st, "taker_sweep"))
                    else:
                        self.position += st
                        self.cash -= nl.price * st
                        self.fills.append(Fill(self.current_tick, "BUY", nl.price, st, "taker_sweep"))
                if nl.bot_vol == 0 and nl.strat_vol == 0:
                    if target == "ASK": del self.book.asks[nl.price]
                    else: del self.book.bids[nl.price]

    def run(self):
        # Taker price clip band: within ±band_width ticks of recorded L1 (or FV fallback)
        band_width = 5
        for i, td in enumerate(self.ticks_data):
            self.current_tick = i
            self.fv = td['fv']
            self.book = build_book_from_record(td)
            rec_bid, rec_ask = recorded_l1(td)
            low  = (rec_bid if rec_bid is not None else int(self.fv) - 1) - band_width
            high = (rec_ask if rec_ask is not None else int(self.fv) + 1) + band_width
            self._taker_band = (low, high)
            ctx = TickContext(tick=i, fv=self.fv, book=self.book,
                              position=self.position, position_limit=self.position_limit,
                              pnl=self.cash)
            intent = self.strategy(ctx)
            self._apply_strategy(intent)
            self._apply_taker()

    def mtm_pnl(self):
        return self.cash + self.position * self.fv


def run_replay(product_params, strategy, product_key, n_seeds=50, position_limit=80,
               ticks=None):
    """Run N seeds of book-replay. If `ticks` is provided, use that subset;
    otherwise load full session for product_key."""
    if ticks is None:
        ticks = load_ticks(product_key)
    pnls = []
    for seed in range(n_seeds):
        r = BookReplayer(product_params, strategy, ticks, seed=seed, position_limit=position_limit)
        r.run()
        pnls.append(r.mtm_pnl())
    return pnls


def main():
    print("Book-replay vs server_state_round1 (exact recorded book + MC takers)\n")

    print("== OSMIUM, 127989 strategy (edge=10) ==")
    strat = make_osmium_stable(fv_anchor=10000.0, edge=10)
    pnls = run_replay(OSMIUM, strat, "ASH_COATED_OSMIUM", n_seeds=50)
    pnls.sort()
    print(f"  mean={statistics.mean(pnls):.0f}  stdev={statistics.stdev(pnls):.0f}")
    print(f"  p05={pnls[2]:.0f}  p50={pnls[25]:.0f}  p95={pnls[47]:.0f}  max={pnls[-1]:.0f}")
    print(f"  server={SERVER_PNL['ASH_COATED_OSMIUM']}  ratio={statistics.mean(pnls)/SERVER_PNL['ASH_COATED_OSMIUM']:.2%}")

    print("\n== OSMIUM, aligned fv_anchor=10003 ==")
    strat = make_osmium_stable(fv_anchor=10003.0, edge=10)
    pnls = run_replay(OSMIUM, strat, "ASH_COATED_OSMIUM", n_seeds=50)
    pnls.sort()
    print(f"  mean={statistics.mean(pnls):.0f}  stdev={statistics.stdev(pnls):.0f}")
    print(f"  p05={pnls[2]:.0f}  p50={pnls[25]:.0f}  p95={pnls[47]:.0f}  max={pnls[-1]:.0f}")
    print(f"  server={SERVER_PNL['ASH_COATED_OSMIUM']}  ratio={statistics.mean(pnls)/SERVER_PNL['ASH_COATED_OSMIUM']:.2%}")

    print("\n== PEPPER, trending strategy ==")
    strat = make_pepper_trending()
    pnls = run_replay(PEPPER, strat, "INTARIAN_PEPPER_ROOT", n_seeds=20)
    pnls.sort()
    print(f"  mean={statistics.mean(pnls):.0f}  stdev={statistics.stdev(pnls):.0f}")
    print(f"  p05={pnls[0]:.0f}  p50={pnls[10]:.0f}  p95={pnls[18]:.0f}  max={pnls[-1]:.0f}")
    print(f"  server={SERVER_PNL['INTARIAN_PEPPER_ROOT']}  ratio={statistics.mean(pnls)/SERVER_PNL['INTARIAN_PEPPER_ROOT']:.2%}")


if __name__ == '__main__':
    main()
