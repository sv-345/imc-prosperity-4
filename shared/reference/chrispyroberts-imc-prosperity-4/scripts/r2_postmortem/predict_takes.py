"""Predict-the-take analysis.

For every bot-bot take in R1 + R2 logs, extract pre-take book state at
lags 1, 3, 5, 10 ticks BEFORE the take. Build feature panel; test
whether pre-take features predict take occurrence and direction.

Also build fingerprints: cluster takes by (size, book state, inter-arrival).
Check informed-vs-uninformed: do takes in each cluster predict mid move?
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
OUT = Path("/Users/svelaga/Documents/IMC Prosperity/chrispyroberts-imc-prosperity-4/scripts/r2_postmortem")


def parse_books(log_path: str) -> dict[tuple[int, str], dict]:
    log = json.load(open(log_path))
    out = {}
    for ln in log["activitiesLog"].strip().split("\n")[1:]:
        c = ln.split(";")
        if len(c) < 17: continue
        try:
            ts = int(c[1]); prod = c[2]
            bp1 = int(c[3]) if c[3] else 0; bv1 = int(c[4]) if c[4] else 0
            bp2 = int(c[5]) if c[5] else 0; bv2 = int(c[6]) if c[6] else 0
            bp3 = int(c[7]) if c[7] else 0; bv3 = int(c[8]) if c[8] else 0
            ap1 = int(c[9]) if c[9] else 0; av1 = int(c[10]) if c[10] else 0
            ap2 = int(c[11]) if c[11] else 0; av2 = int(c[12]) if c[12] else 0
            ap3 = int(c[13]) if c[13] else 0; av3 = int(c[14]) if c[14] else 0
            mid = float(c[15])
            if mid <= 0 or bp1 == 0 or ap1 == 0: continue
            out[(ts, prod)] = {
                "bp1": bp1, "bv1": bv1, "bp2": bp2, "bv2": bv2, "bp3": bp3, "bv3": bv3,
                "ap1": ap1, "av1": av1, "ap2": ap2, "av2": av2, "ap3": ap3, "av3": av3,
                "mid": mid, "spread": ap1 - bp1,
                "depth_bid": bv1 + bv2 + bv3,
                "depth_ask": av1 + av2 + av3,
                "imb_l1": (bv1 - av1) / (bv1 + av1) if (bv1 + av1) > 0 else 0.0,
                "imb_total": ((bv1 + bv2 + bv3) - (av1 + av2 + av3)) /
                             max(1, (bv1 + bv2 + bv3 + av1 + av2 + av3)),
            }
        except ValueError:
            continue
    return out


def classify_take(t: dict, book: dict) -> dict | None:
    buyer = t.get("buyer") or ""
    seller = t.get("seller") or ""
    if "SUBMISSION" in buyer or "SUBMISSION" in seller:
        return None
    if not book: return None
    price = float(t["price"])
    qty = int(t["quantity"])
    if price >= book["ap1"]:
        return {"side": "buy", "qty": qty, "price": price}
    elif price <= book["bp1"]:
        return {"side": "sell", "qty": qty, "price": price}
    else:
        return None  # ambiguous mid-trade


def extract_take_events(log_path: str, label: str) -> tuple[list, dict]:
    log = json.load(open(log_path))
    books = parse_books(log_path)
    trades = log.get("tradeHistory") or []
    events = []
    for t in sorted(trades, key=lambda x: x.get("timestamp", 0)):
        ts = t.get("timestamp", 0)
        prod = t.get("symbol", "?")
        book = books.get((ts, prod))
        cls = classify_take(t, book)
        if cls is None: continue
        events.append({
            "label": label, "ts": ts, "product": prod,
            "side": cls["side"], "qty": cls["qty"], "price": cls["price"],
        })
    return events, books


def pre_take_features(event: dict, books: dict, lag_ticks: int) -> dict | None:
    """Book state at (event_ts - lag_ticks*100) for the event's product."""
    ts_lag = event["ts"] - lag_ticks * 100
    book = books.get((ts_lag, event["product"]))
    if not book:
        return None
    return book


def build_take_panel():
    """Returns: all take events with pre-take features at lag=1,3,5 ticks."""
    all_events = []
    all_books = {}
    # Build per-label books
    per_label_books = {}
    per_label_books["R1"] = parse_books(R1_LOG)
    events, _ = extract_take_events(R1_LOG, "R1")
    all_events.extend(events)
    for sub, path in R2_LOGS.items():
        per_label_books[f"R2_{sub}"] = parse_books(path)
        ev, _ = extract_take_events(path, f"R2_{sub}")
        all_events.extend(ev)

    panel = []
    for ev in all_events:
        books = per_label_books[ev["label"]]
        row = {**ev}
        # Book state AT take tick (post-trade, but for comparison)
        book_at = books.get((ev["ts"], ev["product"]))
        if book_at:
            row["imb_at"] = book_at["imb_l1"]
            row["spread_at"] = book_at["spread"]
            row["depth_bid_at"] = book_at["depth_bid"]
            row["depth_ask_at"] = book_at["depth_ask"]
        # Pre-take at lag 1 / 3 / 5 / 10
        for lag in (1, 3, 5, 10):
            b = pre_take_features(ev, books, lag)
            if b:
                row[f"imb_lag{lag}"] = b["imb_l1"]
                row[f"spread_lag{lag}"] = b["spread"]
                row[f"depth_bid_lag{lag}"] = b["depth_bid"]
                row[f"depth_ask_lag{lag}"] = b["depth_ask"]
                row[f"mid_lag{lag}"] = b["mid"]
        # Imbalance gradient (lag5 → lag1)
        if "imb_lag1" in row and "imb_lag5" in row:
            row["imb_delta_5_1"] = row["imb_lag1"] - row["imb_lag5"]
        # Mid move in the 5 pre-take ticks
        if "mid_lag5" in row and "mid_lag1" in row:
            row["mid_pre5"] = row["mid_lag1"] - row["mid_lag5"]
        panel.append(row)
    return panel, per_label_books


def build_nontake_panel(per_label_books, take_events):
    """For each (label, product), sample ticks where NO take happened in the
    preceding N ticks (to serve as negative class). Keep same feature shape."""
    # Build set of take timestamps per (label, product)
    take_ts = defaultdict(set)
    for ev in take_events:
        take_ts[(ev["label"], ev["product"])].add(ev["ts"])
    nontakes = []
    for (label, product), take_set in take_ts.items():
        books = per_label_books[label]
        for (ts, prod), book in books.items():
            if prod != product:
                continue
            # Sample only ticks where no take in the next 5 ticks
            if any(t in take_set for t in range(ts, ts + 6 * 100, 100)):
                continue
            # Build same feature shape at this tick (not a real take; we treat
            # this tick as the "pre-take" anchor for a hypothetical take event
            # that would happen at ts+100). Features are pre-take lags.
            virt = {"label": label, "ts": ts + 100, "product": product,
                    "side": "NONE", "qty": 0, "price": 0.0}
            for lag in (1, 3, 5, 10):
                b = pre_take_features(virt, books, lag)
                if b:
                    virt[f"imb_lag{lag}"] = b["imb_l1"]
                    virt[f"spread_lag{lag}"] = b["spread"]
                    virt[f"depth_bid_lag{lag}"] = b["depth_bid"]
                    virt[f"depth_ask_lag{lag}"] = b["depth_ask"]
                    virt[f"mid_lag{lag}"] = b["mid"]
            if "imb_lag1" in virt and "imb_lag5" in virt:
                virt["imb_delta_5_1"] = virt["imb_lag1"] - virt["imb_lag5"]
            if "mid_lag5" in virt and "mid_lag1" in virt:
                virt["mid_pre5"] = virt["mid_lag1"] - virt["mid_lag5"]
            nontakes.append(virt)
    return nontakes


def logistic(x: float) -> float:
    try:
        return 1.0 / (1.0 + math.exp(-x))
    except OverflowError:
        return 0.0 if x < 0 else 1.0


def auc(scores_and_labels: list[tuple[float, int]]) -> float:
    """AUC of the (score, label) pairs. Label 1 = positive (take), 0 = negative."""
    pos = [s for s, l in scores_and_labels if l == 1]
    neg = [s for s, l in scores_and_labels if l == 0]
    if not pos or not neg:
        return 0.0
    # Faster: rank-based AUC
    all_scored = sorted(scores_and_labels, key=lambda x: x[0])
    rank_sum = 0
    for rank, (score, label) in enumerate(all_scored, 1):
        if label == 1:
            rank_sum += rank
    n_pos = len(pos); n_neg = len(neg)
    return (rank_sum - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg)


def main():
    print("Building take panel...")
    take_panel, books_by_label = build_take_panel()
    print(f"  {len(take_panel)} takes extracted")

    # Take panel stats
    by_side = Counter(r["side"] for r in take_panel)
    print(f"  By side: {dict(by_side)}")

    print("\nBuilding non-take panel (negative samples)...")
    nontake_panel = build_nontake_panel(books_by_label, take_panel)
    # Sample equal numbers for balanced test
    import random
    random.seed(42)
    sample_size = min(len(take_panel), len(nontake_panel))
    sampled_nontakes = random.sample(nontake_panel, sample_size)
    print(f"  {len(nontake_panel)} non-take windows; sampled {len(sampled_nontakes)}")

    # Test: predict take occurrence by pre-take imbalance
    print("\n=== Predict-take occurrence ===")
    print("For each feature, AUC of (predict take vs non-take) using features at lag=1")
    for feature in ["imb_lag1", "spread_lag1", "depth_bid_lag1", "depth_ask_lag1",
                    "imb_delta_5_1", "mid_pre5"]:
        scored = []
        for r in take_panel:
            if feature not in r: continue
            scored.append((r[feature], 1))
        for r in sampled_nontakes:
            if feature not in r: continue
            scored.append((r[feature], 0))
        if len(scored) < 20:
            print(f"  {feature}: insufficient data")
            continue
        a = auc(scored)
        # Direction: if AUC > 0.5, positive → more takes; if < 0.5, positive → fewer
        print(f"  {feature}: AUC={a:.3f}  (n={len(scored)})")

    # Predict DIRECTION (buy vs sell taker) from features
    print("\n=== Predict-take direction (buy=1, sell=0) ===")
    for product in ["ASH_COATED_OSMIUM", "INTARIAN_PEPPER_ROOT"]:
        rows = [r for r in take_panel if r["product"] == product and r["side"] in ("buy", "sell")]
        for feature in ["imb_lag1", "imb_delta_5_1", "mid_pre5", "spread_lag1"]:
            scored = []
            for r in rows:
                if feature not in r: continue
                label = 1 if r["side"] == "buy" else 0
                scored.append((r[feature], label))
            if len(scored) < 20:
                continue
            a = auc(scored)
            print(f"  {product:22s} {feature}: AUC={a:.3f}  (n={len(scored)})")

    # Fingerprint: cluster by size x book state
    print("\n=== Taker-size fingerprint (informativeness of take direction) ===")
    print("For each qty bucket, is the take followed by a mid move in its direction?")
    # Need post-take mid move: we have books, get mid_lag-1 post-take
    for product in ["ASH_COATED_OSMIUM", "INTARIAN_PEPPER_ROOT"]:
        rows = [r for r in take_panel if r["product"] == product and r["side"] in ("buy", "sell")]
        buckets = defaultdict(lambda: {"n": 0, "move_sum": 0.0, "n_with_move": 0})
        for r in rows:
            qty = r["qty"]
            if qty <= 3: b = "small(1-3)"
            elif qty <= 6: b = "med(4-6)"
            else: b = "large(7+)"
            books = books_by_label[r["label"]]
            post_mid = books.get((r["ts"] + 100, r["product"]))
            if not post_mid or "mid_lag1" not in r:
                continue
            move = post_mid["mid"] - r["mid_lag1"]  # pre-take mid to post-take mid (signed)
            dir_move = move if r["side"] == "buy" else -move
            buckets[b]["n"] += 1
            buckets[b]["move_sum"] += dir_move
            buckets[b]["n_with_move"] += 1
        print(f"  {product}:")
        for b in ["small(1-3)", "med(4-6)", "large(7+)"]:
            v = buckets[b]
            if v["n_with_move"] == 0: continue
            avg = v["move_sum"] / v["n_with_move"]
            print(f"    {b}: n={v['n_with_move']}  avg dir-move = {avg:+.2f}")

    # Persist panel to CSV
    out_csv = OUT / "take_panel.csv"
    if take_panel:
        all_keys = set()
        for r in take_panel:
            all_keys.update(r.keys())
        cols = sorted(all_keys)
        with out_csv.open("w") as f:
            f.write(",".join(cols) + "\n")
            for r in take_panel:
                f.write(",".join(str(r.get(c, "")) for c in cols) + "\n")
        print(f"\nWrote {len(take_panel)} take events to {out_csv}")


if __name__ == "__main__":
    main()
