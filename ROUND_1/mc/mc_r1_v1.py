"""MC backtester v1 for Round 1 — built from Phase 2 locked parameters.

Design goals:
  1. No values copied from chrispyroberts or prior MC. All from Phase 2 profile.
  2. Simple, explicit, side-by-side comparable to the replay backtester.
  3. Deterministic seeds → reproducible.
  4. Minimal abstractions: one class per simulator, plain dicts for state.
  5. Match the tick-level event order of the real server as close as data
     allows:
        (a) FV update
        (b) Bot 1 (wall) quote with Bernoulli presence
        (c) Bot 2 (inner) quote with Bernoulli presence
        (d) Bot 3 (near-FV) quote with 4%/2.5% presence, passive/aggressive split
        (e) Strategy posts orders (user-provided)
        (f) Two-phase matching:
              Phase 1 — strategy orders vs. current book (takeouts first)
              Phase 2 — taker (background) arrives with IID Bernoulli;
                        picks level (weighted), side, qty; sweeps the book.
                        Strategy orders at that level share queue with bots
                        by owner priority (bot=0, strategy=1).
  6. Log every fill with (tick, side, price, qty, owner, counterparty_level).
  7. Return PnL timeseries and position trajectory.

Parameters are from ROUND_1/notes/PHASE2_DATA_PROFILE.md §2.9.
"""

from __future__ import annotations
import math
import random
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

# ---------------- Calibration (locked from Phase 2) ------------------------

@dataclass(frozen=True)
class ProductParams:
    name: str
    fv_sigma: float
    fv_drift: float
    fv_quant: float = 1.0 / 2048
    bid_wall_fn: Callable[[float], int] = None
    ask_wall_fn: Callable[[float], int] = None
    bid_inner_fn: Callable[[float], int] = None
    ask_inner_fn: Callable[[float], int] = None
    wall_vol: Tuple[int, int] = (0, 0)
    inner_vol: Tuple[int, int] = (0, 0)
    wall_presence_rate: float = 0.79
    inner_presence_rate: float = 0.90
    bot3_rate_per_side: float = 0.0
    bot3_passive_frac: float = 0.5
    bot3_vol: Tuple[int, int] = (0, 0)
    bot3_passive_offsets: Tuple[int, int] = (0, 0)    # (bid_side_offset, ask_side_offset)
    bot3_aggressive_offsets: Tuple[int, int] = (0, 0)
    taker_rate: float = 0.0
    taker_qty: Tuple[int, int] = (0, 0)
    taker_side_buy_frac: float = 0.5
    taker_level_weights: Dict[str, float] = field(default_factory=dict)


OSMIUM = ProductParams(
    name="ASH_COATED_OSMIUM",
    fv_sigma=0.3117, fv_drift=0.0,
    bid_wall_fn=lambda fv: math.floor(fv) - 10,
    ask_wall_fn=lambda fv: math.ceil(fv) + 10,
    bid_inner_fn=lambda fv: math.floor(fv - 0.5) - 7,
    ask_inner_fn=lambda fv: math.floor(fv - 0.5) + 9,
    wall_vol=(20, 30),
    inner_vol=(10, 15),
    wall_presence_rate=0.79,     # sqrt(0.628) ≈ 0.79 (from walls_ok rate)
    inner_presence_rate=0.90,
    bot3_rate_per_side=0.04,
    bot3_passive_frac=0.67,
    bot3_vol=(1, 10),
    bot3_passive_offsets=(-2, +2),     # BID below fv, ASK above fv
    bot3_aggressive_offsets=(+2, -2),  # BID crossing above, ASK crossing below
    taker_rate=0.042,
    taker_qty=(2, 10),
    taker_side_buy_frac=0.50,
    taker_level_weights={"inner": 0.76, "wall": 0.20, "bot3_price": 0.04},
)


PEPPER = ProductParams(
    name="INTARIAN_PEPPER_ROOT",
    fv_sigma=0.0, fv_drift=0.10,
    bid_wall_fn=lambda fv: math.floor(fv) - 9,
    ask_wall_fn=lambda fv: math.floor(fv) + 10,
    bid_inner_fn=lambda fv: math.floor(fv) - 6,
    ask_inner_fn=lambda fv: math.floor(fv) + 7,
    wall_vol=(15, 25),
    inner_vol=(8, 12),
    wall_presence_rate=0.46,     # sqrt(0.2139) from day 0 walls_ok
    inner_presence_rate=0.80,
    bot3_rate_per_side=0.025,
    bot3_passive_frac=0.35,
    bot3_vol=(3, 12),
    bot3_passive_offsets=(-3, +3),
    bot3_aggressive_offsets=(+4, -4),
    taker_rate=0.033,
    taker_qty=(3, 8),
    taker_side_buy_frac=0.50,
    taker_level_weights={"inner": 0.58, "wall": 0.09, "bot3_price": 0.33},
)


# ---------------- Book data structures ---------------------------------

@dataclass
class Level:
    price: int
    bot_vol: int = 0      # volume owned by bots (owner=0, priority)
    strat_vol: int = 0    # volume owned by strategy (owner=1)

    @property
    def total(self) -> int:
        return self.bot_vol + self.strat_vol


@dataclass
class Book:
    bids: Dict[int, Level] = field(default_factory=dict)
    asks: Dict[int, Level] = field(default_factory=dict)

    def bid_levels_sorted(self) -> List[Level]:
        return sorted(self.bids.values(), key=lambda lv: -lv.price)   # high → low

    def ask_levels_sorted(self) -> List[Level]:
        return sorted(self.asks.values(), key=lambda lv: lv.price)    # low → high

    def best_bid(self) -> Optional[Level]:
        levels = self.bid_levels_sorted()
        return levels[0] if levels else None

    def best_ask(self) -> Optional[Level]:
        levels = self.ask_levels_sorted()
        return levels[0] if levels else None

    def clear(self) -> None:
        self.bids.clear()
        self.asks.clear()

    def add_bot_vol(self, side: str, price: int, vol: int) -> None:
        if vol <= 0: return
        side_dict = self.bids if side == "BID" else self.asks
        if price in side_dict:
            side_dict[price].bot_vol += vol
        else:
            side_dict[price] = Level(price=price, bot_vol=vol)

    def add_strat_vol(self, side: str, price: int, vol: int) -> None:
        if vol <= 0: return
        side_dict = self.bids if side == "BID" else self.asks
        if price in side_dict:
            side_dict[price].strat_vol += vol
        else:
            side_dict[price] = Level(price=price, strat_vol=vol)


# ---------------- Strategy interface -----------------------------------

@dataclass
class OrderIntent:
    """Strategy-placed limit orders for a single tick."""
    bids: List[Tuple[int, int]] = field(default_factory=list)  # (price, qty)
    asks: List[Tuple[int, int]] = field(default_factory=list)


StrategyFn = Callable[["TickContext"], OrderIntent]


@dataclass
class TickContext:
    tick: int
    fv: float
    book: Book
    position: int
    position_limit: int
    pnl: float


@dataclass
class Fill:
    tick: int
    side: str           # "BUY" if strat buys, "SELL" if strat sells
    price: int
    qty: int
    counterparty: str   # "taker" (background) or "crossed_bot"


# ---------------- Simulator --------------------------------------------

class MCSim:
    def __init__(
        self,
        product: ProductParams,
        n_ticks: int = 1000,
        fv0: Optional[float] = None,
        position_limit: int = 80,
        seed: int = 0,
        strategy: StrategyFn = None,
    ):
        self.product = product
        self.n_ticks = n_ticks
        self.position_limit = position_limit
        self.rng = random.Random(seed)
        self.strategy = strategy or (lambda ctx: OrderIntent())

        if fv0 is None:
            fv0 = 10000.5 if product is OSMIUM else 12000.1
        self.fv = float(fv0)

        self.book = Book()
        self.position = 0
        self.pnl = 0.0
        self.fills: List[Fill] = []
        self.fv_trace: List[float] = []
        self.pnl_trace: List[float] = []
        self.pos_trace: List[int] = []

    # ---- Bot quoting ----

    def _quote_bots(self) -> None:
        """Re-quote all bots fresh for this tick. Book resets each tick."""
        p = self.product
        self.book.clear()
        # Bot 1 walls
        if self.rng.random() < p.wall_presence_rate:
            bw_price = p.bid_wall_fn(self.fv)
            bw_vol = self.rng.randint(*p.wall_vol)
            self.book.add_bot_vol("BID", bw_price, bw_vol)
        if self.rng.random() < p.wall_presence_rate:
            aw_price = p.ask_wall_fn(self.fv)
            aw_vol = self.rng.randint(*p.wall_vol)
            self.book.add_bot_vol("ASK", aw_price, aw_vol)
        # Bot 2 inners
        if self.rng.random() < p.inner_presence_rate:
            bi_price = p.bid_inner_fn(self.fv)
            bi_vol = self.rng.randint(*p.inner_vol)
            self.book.add_bot_vol("BID", bi_price, bi_vol)
        if self.rng.random() < p.inner_presence_rate:
            ai_price = p.ask_inner_fn(self.fv)
            ai_vol = self.rng.randint(*p.inner_vol)
            self.book.add_bot_vol("ASK", ai_price, ai_vol)
        # Bot 3 per side (independent)
        for side, passive_off, aggressive_off in (
            ("BID", p.bot3_passive_offsets[0], p.bot3_aggressive_offsets[0]),
            ("ASK", p.bot3_passive_offsets[1], p.bot3_aggressive_offsets[1]),
        ):
            if self.rng.random() < p.bot3_rate_per_side:
                is_passive = self.rng.random() < p.bot3_passive_frac
                offset = passive_off if is_passive else aggressive_off
                price = math.floor(self.fv) + offset
                vol = self.rng.randint(*p.bot3_vol)
                self.book.add_bot_vol(side, price, vol)

    # ---- Strategy phase: crossing + posting ----

    def _apply_strategy_orders(self, intent: OrderIntent) -> None:
        """Phase 1 of matching — strategy orders hit the bot book first.
        If a strategy bid is at price >= best ask, it crosses (taker-buy).
        If a strategy ask is at price <= best bid, it crosses (taker-sell).
        Otherwise the order rests (strat_vol at that price).
        """
        # Strategy buys (intent.bids)
        for price, qty in intent.bids:
            qty_remaining = qty
            # Cap at position limit
            max_buy = self.position_limit - self.position
            if max_buy <= 0:
                continue
            qty_remaining = min(qty_remaining, max_buy)
            # Walk the ask book from best to worst; consume anything at price <= price
            ask_levels = [lv for lv in self.book.ask_levels_sorted() if lv.price <= price]
            for lv in ask_levels:
                if qty_remaining <= 0:
                    break
                # Bot volume taken first (bots present in the book have priority
                # on their own quotes, but when strategy crosses into them the
                # strategy is the taker and consumes bot volume).
                take = min(qty_remaining, lv.bot_vol)
                if take > 0:
                    lv.bot_vol -= take
                    qty_remaining -= take
                    self.position += take
                    self.pnl -= lv.price * take
                    self.fills.append(
                        Fill(self.current_tick, "BUY", lv.price, take, "crossed_bot")
                    )
                if lv.bot_vol == 0 and lv.strat_vol == 0:
                    del self.book.asks[lv.price]
            # Rest any remainder as a resting bid
            if qty_remaining > 0:
                self.book.add_strat_vol("BID", price, qty_remaining)

        # Strategy sells (intent.asks)
        for price, qty in intent.asks:
            qty_remaining = qty
            max_sell = self.position_limit + self.position
            if max_sell <= 0:
                continue
            qty_remaining = min(qty_remaining, max_sell)
            bid_levels = [lv for lv in self.book.bid_levels_sorted() if lv.price >= price]
            for lv in bid_levels:
                if qty_remaining <= 0:
                    break
                take = min(qty_remaining, lv.bot_vol)
                if take > 0:
                    lv.bot_vol -= take
                    qty_remaining -= take
                    self.position -= take
                    self.pnl += lv.price * take
                    self.fills.append(
                        Fill(self.current_tick, "SELL", lv.price, take, "crossed_bot")
                    )
                if lv.bot_vol == 0 and lv.strat_vol == 0:
                    del self.book.bids[lv.price]
            if qty_remaining > 0:
                self.book.add_strat_vol("ASK", price, qty_remaining)

    # ---- Taker phase: background IID Bernoulli ----

    def _choose_taker_level(self, side: str) -> Optional[Level]:
        """Taker always hits L1 (best bid/ask). Book walking happens in
        `_apply_taker_phase` when qty exceeds L1 volume.

        The 76/20/4% level distribution observed in training data is an
        EMERGENT property of L1 targeting combined with bot presence rates:
        - When inner is present, L1 = inner → 76% inner hits
        - When inner absent (~20%), L1 = wall → wall hits
        - When strategy quotes tighter, strategy is L1 and gets the flow
        """
        p = self.product
        levels = self.book.bid_levels_sorted() if side == "BID" else self.book.ask_levels_sorted()
        if not levels:
            return None
        return levels[0]

    def _apply_taker_phase(self) -> None:
        p = self.product
        if self.rng.random() >= p.taker_rate:
            return
        # Side: BUY taker hits ask side, SELL taker hits bid side
        is_buy = self.rng.random() < p.taker_side_buy_frac
        target_side = "ASK" if is_buy else "BID"
        level = self._choose_taker_level(target_side)
        if level is None:
            return
        qty = self.rng.randint(*p.taker_qty)
        # Consume level: BOT VOLUME FIRST (owner priority), then strategy.
        price = level.price
        # Bot first
        bot_take = min(qty, level.bot_vol)
        level.bot_vol -= bot_take
        qty -= bot_take
        # Strategy second (owner=1, behind bots at same price)
        if qty > 0 and level.strat_vol > 0:
            strat_take = min(qty, level.strat_vol)
            level.strat_vol -= strat_take
            qty -= strat_take
            if is_buy:
                # strategy is selling (was on ask side) → strategy sells
                self.position -= strat_take
                self.pnl += price * strat_take
                self.fills.append(Fill(self.current_tick, "SELL", price, strat_take, "taker"))
            else:
                # taker sells into bid side → strategy buys
                self.position += strat_take
                self.pnl -= price * strat_take
                self.fills.append(Fill(self.current_tick, "BUY", price, strat_take, "taker"))
        # Remove empty level
        if level.bot_vol == 0 and level.strat_vol == 0:
            if target_side == "ASK":
                del self.book.asks[level.price]
            else:
                del self.book.bids[level.price]
        # If qty remaining > 0 → walk the book (take next level)
        if qty > 0:
            next_levels = self.book.ask_levels_sorted() if target_side == "ASK" else self.book.bid_levels_sorted()
            for lv in next_levels:
                if qty <= 0:
                    break
                bt = min(qty, lv.bot_vol)
                lv.bot_vol -= bt
                qty -= bt
                if qty > 0 and lv.strat_vol > 0:
                    st = min(qty, lv.strat_vol)
                    lv.strat_vol -= st
                    qty -= st
                    if is_buy:
                        self.position -= st
                        self.pnl += lv.price * st
                        self.fills.append(Fill(self.current_tick, "SELL", lv.price, st, "taker_sweep"))
                    else:
                        self.position += st
                        self.pnl -= lv.price * st
                        self.fills.append(Fill(self.current_tick, "BUY", lv.price, st, "taker_sweep"))
                if lv.bot_vol == 0 and lv.strat_vol == 0:
                    if target_side == "ASK":
                        del self.book.asks[lv.price]
                    else:
                        del self.book.bids[lv.price]

    # ---- Main loop ----

    def _update_fv(self) -> None:
        p = self.product
        if p.fv_sigma > 0:
            step = self.rng.gauss(p.fv_drift, p.fv_sigma)
        else:
            step = p.fv_drift
        self.fv += step
        # Quantize to 1/2048 grid
        self.fv = round(self.fv / p.fv_quant) * p.fv_quant

    def run(self) -> None:
        for t in range(self.n_ticks):
            self.current_tick = t
            self._update_fv()
            self._quote_bots()
            # Strategy
            ctx = TickContext(tick=t, fv=self.fv, book=self.book,
                              position=self.position, position_limit=self.position_limit,
                              pnl=self.pnl)
            intent = self.strategy(ctx)
            self._apply_strategy_orders(intent)
            # Taker
            self._apply_taker_phase()
            # Mark-to-market PnL
            mtm = self.pnl + self.position * self.fv
            self.fv_trace.append(self.fv)
            self.pnl_trace.append(mtm)
            self.pos_trace.append(self.position)

    def summary(self) -> Dict:
        return {
            "product": self.product.name,
            "n_ticks": self.n_ticks,
            "final_position": self.position,
            "final_cash_pnl": self.pnl,
            "final_fv": self.fv,
            "final_mtm_pnl": self.pnl + self.position * self.fv,
            "n_fills": len(self.fills),
            "n_buys": sum(1 for f in self.fills if f.side == "BUY"),
            "n_sells": sum(1 for f in self.fills if f.side == "SELL"),
            "total_buy_qty": sum(f.qty for f in self.fills if f.side == "BUY"),
            "total_sell_qty": sum(f.qty for f in self.fills if f.side == "SELL"),
        }


# ---------------- Example strategies ------------------------------------

def strategy_passive_inside(ctx: TickContext) -> OrderIntent:
    """Quote 1 tick INSIDE Bot 2's inner on both sides.
       OSMIUM inner is at ≈±8 from fv; we quote at ±7 (strategy best bid/ask)."""
    fv = ctx.fv
    # Use tightest-possible quotes that are still inside inner.
    # We derive the exact inner price from the observed book to be safe.
    best_bid_lv = ctx.book.best_bid()
    best_ask_lv = ctx.book.best_ask()
    if best_bid_lv is None or best_ask_lv is None:
        return OrderIntent()
    my_bid = best_bid_lv.price + 1
    my_ask = best_ask_lv.price - 1
    if my_bid >= my_ask:
        return OrderIntent()
    # Stay within position limit (simple size = 5)
    return OrderIntent(bids=[(my_bid, 5)], asks=[(my_ask, 5)])


def strategy_passive_at_inner(ctx: TickContext) -> OrderIntent:
    """Quote AT Bot 2's inner (same price). Will sit behind bot (owner priority)."""
    best_bid_lv = ctx.book.best_bid()
    best_ask_lv = ctx.book.best_ask()
    if best_bid_lv is None or best_ask_lv is None:
        return OrderIntent()
    return OrderIntent(bids=[(best_bid_lv.price, 5)], asks=[(best_ask_lv.price, 5)])


def strategy_flat(ctx: TickContext) -> OrderIntent:
    return OrderIntent()


# ---------------- Run a demo ------------------------------------------

if __name__ == "__main__":
    print("MC v1 demo on OSMIUM (1000 ticks, seed=0)")

    sim = MCSim(OSMIUM, n_ticks=1000, seed=0, strategy=strategy_passive_inside)
    sim.run()
    s = sim.summary()
    for k, v in s.items():
        print(f"  {k}: {v}")

    print("\nMC v1 demo on OSMIUM with AT-INNER quoting (queues behind bot):")
    sim2 = MCSim(OSMIUM, n_ticks=1000, seed=0, strategy=strategy_passive_at_inner)
    sim2.run()
    for k, v in sim2.summary().items():
        print(f"  {k}: {v}")

    print("\nMC v1 demo on PEPPER (1000 ticks, seed=0) with INSIDE quoting:")
    sim3 = MCSim(PEPPER, n_ticks=1000, seed=0, strategy=strategy_passive_inside)
    sim3.run()
    for k, v in sim3.summary().items():
        print(f"  {k}: {v}")

    print("\nMC v1 demo on OSMIUM with NO strategy (baseline, PnL should be ~0):")
    sim4 = MCSim(OSMIUM, n_ticks=1000, seed=0, strategy=strategy_flat)
    sim4.run()
    for k, v in sim4.summary().items():
        print(f"  {k}: {v}")
