"""Bot-take extraction from R1 + R2 logs.

For every trade:
  - Classify as bot-to-bot / us-maker / us-taker
  - Infer taker side: price == best_ask → buy-taker; price == best_bid → sell-taker
  - Capture pre-trade book state (L1)
  - Record next 1/10/50-tick mid moves

Then:
  - Taker-direction-as-signal regression: next mid move | taker side
  - Taker size distribution + clustering (fingerprint)
  - Conditional behavior: taker side | (imbalance, spread, recent mid move)
  - Time-since-last-take arrival patterns
"""

from __future__ import annotations

import csv
import json
import math
import statistics
from collections import defaultdict, Counter
from pathlib import Path

R1_LOG = "/Users/svelaga/Documents/IMC Prosperity/ROUND_1/R1Final/273632/273632.log"
R2_LOGS = {
    "296317": "/tmp/prosperity_logs/296317/305226.log",
    "296379": "/tmp/prosperity_logs/296379/305289.log",
    "296878": "/tmp/prosperity_logs/296878/305790.log",
    "297226": "/tmp/prosperity_logs/297226/306138.log",
}
OUT_DIR = Path("/Users/svelaga/Documents/IMC Prosperity/chrispyroberts-imc-prosperity-4/scripts/r2_postmortem")


def parse_activities(log: dict) -> dict[tuple[int, str], dict]:
    out = {}
    for ln in log["activitiesLog"].strip().split("\n")[1:]:
        c = ln.split(";")
        if len(c) < 17:
            continue
        try:
            ts = int(c[1]); prod = c[2]
            bp1 = int(c[3]) if c[3] else 0; bv1 = int(c[4]) if c[4] else 0
            bp2 = int(c[5]) if c[5] else 0; bv2 = int(c[6]) if c[6] else 0
            bp3 = int(c[7]) if c[7] else 0; bv3 = int(c[8]) if c[8] else 0
            ap1 = int(c[9]) if c[9] else 0; av1 = int(c[10]) if c[10] else 0
            ap2 = int(c[11]) if c[11] else 0; av2 = int(c[12]) if c[12] else 0
            ap3 = int(c[13]) if c[13] else 0; av3 = int(c[14]) if c[14] else 0
            mid = float(c[15])
            if mid <= 0 or bp1 == 0 or ap1 == 0:
                continue
            out[(ts, prod)] = {
                "bp1": bp1, "bv1": bv1, "bp2": bp2, "bv2": bv2, "bp3": bp3, "bv3": bv3,
                "ap1": ap1, "av1": av1, "ap2": ap2, "av2": av2, "ap3": ap3, "av3": av3,
                "mid": mid, "spread": ap1 - bp1,
                "bv_total": bv1 + bv2 + bv3,
                "av_total": av1 + av2 + av3,
            }
        except ValueError:
            continue
    return out


def future_mid(books: dict, product: str, ts: int, dticks: int) -> float:
    target = ts + dticks * 100
    while target <= 999900:
        if (target, product) in books:
            return books[(target, product)]["mid"]
        target += 100
    return float("nan")


def classify_trade(t: dict, book: dict | None) -> dict:
    """Return dict with side_inferred, is_bot_bot, involves_us, size_sign."""
    buyer = t.get("buyer") or ""
    seller = t.get("seller") or ""
    if "SUBMISSION" in buyer and "SUBMISSION" not in seller:
        role = "us_taker_buy" if True else ""  # we bought
        side = None
    elif "SUBMISSION" in seller and "SUBMISSION" not in buyer:
        role = "us_taker_sell"
        side = None
    elif "SUBMISSION" in seller and "SUBMISSION" in buyer:
        role = "us_both"
        side = None
    elif buyer == "" and seller == "":
        role = "bot_bot"
        if book is None:
            side = None
        else:
            price = float(t["price"])
            # Taker side inferred from price vs best_bid / best_ask
            if price == book["ap1"]:
                side = "buy"  # taker bought the ask
            elif price == book["bp1"]:
                side = "sell"  # taker sold into the bid
            else:
                # price between bb and ba, or even outside — ambiguous
                if price > book["mid"]:
                    side = "buy"
                elif price < book["mid"]:
                    side = "sell"
                else:
                    side = "midtrade"
    else:
        # mix with "BOT_MAKER"/"BOT_TAKER" labels
        if "BOT_TAKER" in buyer:
            role = "bot_bot"; side = "buy"
        elif "BOT_TAKER" in seller:
            role = "bot_bot"; side = "sell"
        elif "BOT_MAKER" in seller and "SUBMISSION" in buyer:
            role = "us_taker_buy"; side = None
        elif "BOT_MAKER" in buyer and "SUBMISSION" in seller:
            role = "us_taker_sell"; side = None
        else:
            role = "other"; side = None
    return {"role": role, "side": side}


def extract_takes(log_path: str, label: str) -> list[dict]:
    log = json.load(open(log_path))
    books = parse_activities(log)
    trades = log.get("tradeHistory") or []
    out = []
    # Prev trade ts per product (for time-since-last-take)
    last_take_ts = {}
    for t in sorted(trades, key=lambda x: x.get("timestamp", 0)):
        ts = t.get("timestamp", 0)
        prod = t.get("symbol", "?")
        book = books.get((ts, prod))
        cls = classify_trade(t, book)
        if cls["role"] != "bot_bot":
            continue
        rec = {
            "label": label,
            "ts": ts,
            "product": prod,
            "price": float(t["price"]),
            "qty": int(t["quantity"]),
            "side": cls["side"],
            "bp1": book["bp1"] if book else 0,
            "bv1": book["bv1"] if book else 0,
            "ap1": book["ap1"] if book else 0,
            "av1": book["av1"] if book else 0,
            "spread": book["spread"] if book else 0,
            "mid": book["mid"] if book else 0,
            "imb": ((book["bv1"] - book["av1"]) / (book["bv1"] + book["av1"])) if (book and (book["bv1"] + book["av1"]) > 0) else 0.0,
            "mid_fwd_1": future_mid(books, prod, ts, 1) - (book["mid"] if book else 0) if book else float("nan"),
            "mid_fwd_10": future_mid(books, prod, ts, 10) - (book["mid"] if book else 0) if book else float("nan"),
            "mid_fwd_50": future_mid(books, prod, ts, 50) - (book["mid"] if book else 0) if book else float("nan"),
            "dt_last_take": (ts - last_take_ts.get(prod, 0)) if prod in last_take_ts else -1,
        }
        last_take_ts[prod] = ts
        out.append(rec)
    return out


def main():
    all_takes = []
    # R1
    r1 = extract_takes(R1_LOG, "R1")
    all_takes.extend(r1)
    # R2
    for sub, path in R2_LOGS.items():
        r2 = extract_takes(path, f"R2_{sub}")
        all_takes.extend(r2)

    # Write ledger
    out_path = OUT_DIR / "bot_takes.csv"
    cols = list(all_takes[0].keys())
    with out_path.open("w") as f:
        f.write(",".join(cols) + "\n")
        for r in all_takes:
            f.write(",".join(str(r[c]) for c in cols) + "\n")
    print(f"Wrote {len(all_takes)} bot-bot takes to {out_path}")

    # Per-label/product counts + side split
    print("\n=== Bot-bot take counts ===")
    by = defaultdict(Counter)
    for r in all_takes:
        by[(r["label"], r["product"])][r["side"]] += 1
    for (lbl, prod), sides in sorted(by.items()):
        n = sum(sides.values())
        print(f"{lbl:10s} {prod:22s}: total={n} buy={sides['buy']} sell={sides['sell']} mid={sides['midtrade']} ambig={sides[None]}")

    # Taker side → next mid move (key signal test)
    print("\n=== Taker side → fwd mid move (bot-bot only) ===")
    # Combine R1 + R2 for more power; split per product
    for prod in ["ASH_COATED_OSMIUM", "INTARIAN_PEPPER_ROOT"]:
        for window in ["R1_only", "R2_only", "ALL"]:
            if window == "R1_only":
                rows = [r for r in all_takes if r["label"] == "R1" and r["product"] == prod]
            elif window == "R2_only":
                rows = [r for r in all_takes if r["label"].startswith("R2") and r["product"] == prod]
            else:
                rows = [r for r in all_takes if r["product"] == prod]
            if not rows: continue
            for side in ["buy", "sell"]:
                sub = [r for r in rows if r["side"] == side]
                if not sub: continue
                for fwd in ["mid_fwd_1", "mid_fwd_10", "mid_fwd_50"]:
                    vals = [r[fwd] for r in sub if not (isinstance(r[fwd], float) and math.isnan(r[fwd]))]
                    if len(vals) < 20:
                        continue
                    m = statistics.fmean(vals)
                    s = statistics.stdev(vals) if len(vals) > 1 else 0
                    # z-score of mean
                    zs = m / (s / math.sqrt(len(vals))) if s > 0 else 0
                    print(f"  {prod:22s} {window:8s} side={side:4s} {fwd}: n={len(vals):4d} mean={m:+.3f} std={s:.2f} z={zs:+.2f}")

    # Size distribution — can we cluster bot takes by size?
    print("\n=== Taker size distribution ===")
    for prod in ["ASH_COATED_OSMIUM", "INTARIAN_PEPPER_ROOT"]:
        for window in ["R1_only", "R2_only"]:
            if window == "R1_only":
                rows = [r for r in all_takes if r["label"] == "R1" and r["product"] == prod]
            else:
                rows = [r for r in all_takes if r["label"].startswith("R2") and r["product"] == prod]
            if not rows: continue
            ct = Counter(r["qty"] for r in rows)
            sizes = sorted(ct.keys())
            n = sum(ct.values())
            print(f"{prod:22s} {window}: n={n}, size dist: " + ", ".join(f"{s}={ct[s]}" for s in sizes))

    # Conditional side: does imbalance predict which side will take?
    print("\n=== Imbalance at take → taker side ===")
    for prod in ["ASH_COATED_OSMIUM", "INTARIAN_PEPPER_ROOT"]:
        rows = [r for r in all_takes if r["product"] == prod and r["side"] in ("buy", "sell")]
        for imb_b in ["neg (-.5 to -.1)", "mid (-.1 to .1)", "pos (.1 to .5)"]:
            if imb_b == "neg (-.5 to -.1)":
                lo, hi = -0.5, -0.1
            elif imb_b == "mid (-.1 to .1)":
                lo, hi = -0.1, 0.1
            else:
                lo, hi = 0.1, 0.5
            sub = [r for r in rows if lo <= r["imb"] <= hi]
            buy_frac = sum(1 for r in sub if r["side"] == "buy") / len(sub) if sub else 0
            print(f"  {prod:22s} imb={imb_b}: n={len(sub)} buy_frac={buy_frac:.2%}")


if __name__ == "__main__":
    main()
