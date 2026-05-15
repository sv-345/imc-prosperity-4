"""Synthetic book generator for MC backtesting.

Generates per-tick bot books using the locked Phase 2 formulas:

    OSMIUM (Gaussian RW, sigma=0.3117 per tick)
      bid_wall  = floor(fv) - 10            vol ~ U(15,25)
      ask_wall  = ceil(fv)  + 10            vol ~ U(15,25)
      bid_inner = floor(fv-0.5) - 7         vol ~ U(5,15)
      ask_inner = floor(fv-0.5) + 9         vol ~ U(5,15)

    PEPPER (deterministic drift +0.10 per tick)
      bid_wall  = floor(fv) - 9             vol ~ U(15,25)
      ask_wall  = floor(fv) + 10            vol ~ U(15,25)
      bid_inner = floor(fv) - 6             vol ~ U(5,12)
      ask_inner = floor(fv) + 7             vol ~ U(5,12)

Taker model (to be fit in Step 3):
    - Bernoulli arrival per tick with rate `taker_rate`.
    - If taker arrives: side uniform, qty ~ U(qty_lo, qty_hi), price_tol = 0
      (i.e. takes only at best price on that side).

The generator does NOT run the match; it only emits:
    (ts, fv_true, bot_book_orders_dict, [taker_events])

The replay sim combines this with our trader to match fills.
"""
from __future__ import annotations
import math
import random
from dataclasses import dataclass, field


OSMIUM_FV0 = 10000.0
OSMIUM_FV_SIGMA = 0.3117
OSMIUM_WALL_VOL = (15, 25)
OSMIUM_INNER_VOL = (5, 15)
OSMIUM_WALL_PRESENCE = 0.79   # per side, per tick (Phase 2 measured)
OSMIUM_INNER_PRESENCE = 0.90
OSMIUM_BOT3_RATE = 0.04       # per side per tick
OSMIUM_BOT3_PASSIVE_FRAC = 0.67
OSMIUM_BOT3_VOL = (1, 10)
# Bot-3 offsets in ticks from floor(fv); bid_passive = -2 (below fv), etc.
OSMIUM_BOT3_BID_PASSIVE = -2
OSMIUM_BOT3_BID_AGGRESSIVE = 3
OSMIUM_BOT3_ASK_PASSIVE = 3
OSMIUM_BOT3_ASK_AGGRESSIVE = -1

PEPPER_FV0 = 12000.0
PEPPER_FV_DRIFT = 0.10
PEPPER_WALL_VOL = (15, 25)
PEPPER_INNER_VOL = (5, 12)
PEPPER_WALL_PRESENCE = 0.46   # Phase 2: sqrt(0.2139) from day-0 walls_ok
PEPPER_INNER_PRESENCE = 0.80
PEPPER_BOT3_RATE = 0.025
PEPPER_BOT3_PASSIVE_FRAC = 0.35
PEPPER_BOT3_VOL = (3, 12)
PEPPER_BOT3_BID_PASSIVE = -3
PEPPER_BOT3_BID_AGGRESSIVE = 4
PEPPER_BOT3_ASK_PASSIVE = 3
PEPPER_BOT3_ASK_AGGRESSIVE = -3

FV_QUANT = 1.0 / 2048


@dataclass
class TakerEvent:
    side: str  # "BUY" = taker lifts asks; "SELL" = taker hits bids
    qty: int
    price_tol: int = 0  # how far from best price the taker is willing to pay


@dataclass
class TickSnapshot:
    ts: int
    fv_true: float
    buy_orders: dict  # {price: qty} — bot standing bids
    sell_orders: dict  # {price: qty} — bot standing asks
    takers: list = field(default_factory=list)


def _quantize(fv: float) -> float:
    return round(fv / FV_QUANT) * FV_QUANT


def _osm_book(fv: float, rng: random.Random,
              wall_presence=OSMIUM_WALL_PRESENCE,
              inner_presence=OSMIUM_INNER_PRESENCE,
              bot3_rate=OSMIUM_BOT3_RATE) -> tuple[dict, dict]:
    buys, sells = {}, {}
    if rng.random() < wall_presence:
        bw = math.floor(fv) - 10
        buys[bw] = rng.randint(*OSMIUM_WALL_VOL)
    if rng.random() < wall_presence:
        aw = math.ceil(fv) + 10
        sells[aw] = -rng.randint(*OSMIUM_WALL_VOL)
    if rng.random() < inner_presence:
        bi = math.floor(fv - 0.5) - 7
        buys[bi] = buys.get(bi, 0) + rng.randint(*OSMIUM_INNER_VOL)
    if rng.random() < inner_presence:
        ai = math.floor(fv - 0.5) + 9
        sells[ai] = sells.get(ai, 0) - rng.randint(*OSMIUM_INNER_VOL)
    # Bot-3: near-FV noise quotes (independent per side)
    if rng.random() < bot3_rate:
        is_passive = rng.random() < OSMIUM_BOT3_PASSIVE_FRAC
        off = OSMIUM_BOT3_BID_PASSIVE if is_passive else OSMIUM_BOT3_BID_AGGRESSIVE
        bp = math.floor(fv) + off
        buys[bp] = buys.get(bp, 0) + rng.randint(*OSMIUM_BOT3_VOL)
    if rng.random() < bot3_rate:
        is_passive = rng.random() < OSMIUM_BOT3_PASSIVE_FRAC
        off = OSMIUM_BOT3_ASK_PASSIVE if is_passive else OSMIUM_BOT3_ASK_AGGRESSIVE
        ap = math.floor(fv) + off
        sells[ap] = sells.get(ap, 0) - rng.randint(*OSMIUM_BOT3_VOL)
    return buys, sells


def _pep_book(fv: float, rng: random.Random,
              wall_presence=PEPPER_WALL_PRESENCE,
              inner_presence=PEPPER_INNER_PRESENCE,
              bot3_rate=PEPPER_BOT3_RATE) -> tuple[dict, dict]:
    buys, sells = {}, {}
    if rng.random() < wall_presence:
        bw = math.floor(fv) - 9
        buys[bw] = rng.randint(*PEPPER_WALL_VOL)
    if rng.random() < wall_presence:
        aw = math.floor(fv) + 10
        sells[aw] = -rng.randint(*PEPPER_WALL_VOL)
    if rng.random() < inner_presence:
        bi = math.floor(fv) - 6
        buys[bi] = buys.get(bi, 0) + rng.randint(*PEPPER_INNER_VOL)
    if rng.random() < inner_presence:
        ai = math.floor(fv) + 7
        sells[ai] = sells.get(ai, 0) - rng.randint(*PEPPER_INNER_VOL)
    if rng.random() < bot3_rate:
        is_passive = rng.random() < PEPPER_BOT3_PASSIVE_FRAC
        off = PEPPER_BOT3_BID_PASSIVE if is_passive else PEPPER_BOT3_BID_AGGRESSIVE
        bp = math.floor(fv) + off
        buys[bp] = buys.get(bp, 0) + rng.randint(*PEPPER_BOT3_VOL)
    if rng.random() < bot3_rate:
        is_passive = rng.random() < PEPPER_BOT3_PASSIVE_FRAC
        off = PEPPER_BOT3_ASK_PASSIVE if is_passive else PEPPER_BOT3_ASK_AGGRESSIVE
        ap = math.floor(fv) + off
        sells[ap] = sells.get(ap, 0) - rng.randint(*PEPPER_BOT3_VOL)
    return buys, sells


def _sample_takers(
    rng: random.Random,
    taker_rate: float,
    qty_range: tuple[int, int],
    price_tol: int = 0,
) -> list[TakerEvent]:
    out = []
    if rng.random() < taker_rate:
        side = "BUY" if rng.random() < 0.5 else "SELL"
        qty = rng.randint(*qty_range)
        out.append(TakerEvent(side=side, qty=qty, price_tol=price_tol))
    return out


def gen_osmium_session(
    seed: int,
    n_ticks: int = 1000,
    fv0: float = OSMIUM_FV0,
    taker_rate: float = 0.042,
    qty_range: tuple[int, int] = (2, 10),
    price_tol: int = 0,
) -> list[TickSnapshot]:
    rng = random.Random(seed)
    fv = fv0
    out = []
    for i in range(n_ticks):
        fv = _quantize(fv + rng.gauss(0.0, OSMIUM_FV_SIGMA))
        buys, sells = _osm_book(fv, rng)
        takers = _sample_takers(rng, taker_rate, qty_range, price_tol)
        out.append(TickSnapshot(
            ts=i * 100, fv_true=fv,
            buy_orders=buys, sell_orders=sells, takers=takers,
        ))
    return out


def gen_pepper_session(
    seed: int,
    n_ticks: int = 1000,
    fv0: float = PEPPER_FV0,
    taker_rate: float = 0.033,
    qty_range: tuple[int, int] = (3, 8),
    price_tol: int = 0,
) -> list[TickSnapshot]:
    rng = random.Random(seed)
    fv = fv0
    out = []
    for i in range(n_ticks):
        fv = fv + PEPPER_FV_DRIFT
        buys, sells = _pep_book(fv, rng)
        takers = _sample_takers(rng, taker_rate, qty_range, price_tol)
        out.append(TickSnapshot(
            ts=i * 100, fv_true=fv,
            buy_orders=buys, sell_orders=sells, takers=takers,
        ))
    return out


def _summary(name: str, ticks: list[TickSnapshot]):
    fvs = [t.fv_true for t in ticks]
    n_takers = sum(len(t.takers) for t in ticks)
    taker_qtys = [ev.qty for t in ticks for ev in t.takers]
    wall_bid_vols = []
    inner_bid_vols = []
    for t in ticks:
        bids_sorted = sorted(t.buy_orders.items())  # lowest price first = wall
        if bids_sorted:
            wall_bid_vols.append(bids_sorted[0][1])
        if len(bids_sorted) > 1:
            inner_bid_vols.append(bids_sorted[-1][1])
    print(f"=== {name} ({len(ticks)} ticks) ===")
    print(f"fv range: {min(fvs):.2f} .. {max(fvs):.2f}")
    print(f"takers: {n_takers} total ({n_takers/len(ticks)*100:.2f}%/tick), "
          f"qty mean={sum(taker_qtys)/max(1,len(taker_qtys)):.2f} "
          f"range {min(taker_qtys) if taker_qtys else '-'}..{max(taker_qtys) if taker_qtys else '-'}")
    if wall_bid_vols:
        print(f"wall bid vols: mean={sum(wall_bid_vols)/len(wall_bid_vols):.2f}")
    if inner_bid_vols:
        print(f"inner bid vols: mean={sum(inner_bid_vols)/len(inner_bid_vols):.2f}")


if __name__ == "__main__":
    osm = gen_osmium_session(seed=0, n_ticks=1000)
    pep = gen_pepper_session(seed=0, n_ticks=1000)
    _summary("OSMIUM", osm)
    _summary("PEPPER", pep)
    t0 = osm[0]
    print(f"\nsample OSM tick 0: fv={t0.fv_true:.4f}")
    print(f"  bids={sorted(t0.buy_orders.items(), reverse=True)}")
    print(f"  asks={sorted(t0.sell_orders.items())}")
