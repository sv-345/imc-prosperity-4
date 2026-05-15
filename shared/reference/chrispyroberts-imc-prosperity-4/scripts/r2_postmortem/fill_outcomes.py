"""For each fill in the ledger, classify by realized 50-tick PnL outcome
and cross-tabulate with book features at fill time.

Question: at the instant we got a fill, what book feature values predicted
good vs bad realized outcome?
"""

from __future__ import annotations

import csv
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path

LEDGER = Path("/Users/svelaga/Documents/IMC Prosperity/chrispyroberts-imc-prosperity-4/scripts/r2_postmortem/ledger_all.csv")
LOGS = {
    "296317": "/tmp/prosperity_logs/296317/305226.log",
    "296379": "/tmp/prosperity_logs/296379/305289.log",
    "296878": "/tmp/prosperity_logs/296878/305790.log",
    "297226": "/tmp/prosperity_logs/297226/306138.log",
}


def load_book_snapshots(path: str) -> dict[tuple[int, str], dict]:
    """Map (ts, product) -> book snapshot."""
    log = json.load(open(path))
    out = {}
    for ln in log["activitiesLog"].strip().split("\n")[1:]:
        c = ln.split(";")
        if len(c) < 17: continue
        try:
            ts = int(c[1]); prod = c[2]
            bp1 = int(c[3]) if c[3] else 0; bv1 = int(c[4]) if c[4] else 0
            ap1 = int(c[9]) if c[9] else 0; av1 = int(c[10]) if c[10] else 0
            if bp1 == 0 or ap1 == 0: continue
            out[(ts, prod)] = {"bp1": bp1, "bv1": bv1, "ap1": ap1, "av1": av1,
                               "mid": float(c[15])}
        except ValueError:
            continue
    return out


def compute_mk50_pnl(row: dict) -> float:
    """Signed dollar P&L over 50 ticks on this fill."""
    mid_now = row["mid_at_fill"]
    mid_50 = row["mid_plus_50"]
    if math.isnan(mid_50) or math.isnan(mid_now):
        return 0.0
    if row["side"] == "BUY":
        return (mid_50 - row["price"]) * row["size"]
    else:
        return (row["price"] - mid_50) * row["size"]


def main():
    # Load ledger
    rows = []
    with LEDGER.open() as f:
        for r in csv.DictReader(f):
            for k in ("timestamp", "size", "inv_before", "inv_after",
                      "adverse_N2_M10", "adverse_N4_M50"):
                r[k] = int(r[k]) if r[k] != "" else 0
            for k in ("price", "mid_at_fill", "edge_at_fill",
                      "mid_plus_10", "mid_plus_50", "mid_plus_200",
                      "realized_pnl_fifo"):
                try:
                    r[k] = float(r[k])
                except ValueError:
                    r[k] = float("nan")
            rows.append(r)

    # Load book snapshots per submission
    books_by_sub = {}
    for sub, path in LOGS.items():
        books_by_sub[sub] = load_book_snapshots(path)

    # Attach features at fill time
    for r in rows:
        book = books_by_sub[r["sub"]].get((r["timestamp"], r["product"]))
        if book:
            bv = book["bv1"]; av = book["av1"]
            r["imbalance"] = (bv - av) / (bv + av) if (bv + av) > 0 else 0.0
            r["spread"] = book["ap1"] - book["bp1"]
        else:
            r["imbalance"] = 0.0
            r["spread"] = 0
        r["pnl_50"] = compute_mk50_pnl(r)

    # Bucket fills by imbalance at fill time
    print("=== Fill PnL (50-tick realized) by imbalance-at-fill ===\n")
    for product in ["ASH_COATED_OSMIUM", "INTARIAN_PEPPER_ROOT"]:
        print(f"\n{product}:")
        prows = [r for r in rows if r["product"] == product]
        # Bucket by (side, imbalance sign)
        buckets = defaultdict(lambda: {"n": 0, "pnl": 0.0, "qty": 0})
        for r in prows:
            side = r["side"]
            if r["imbalance"] > 0.3: imb_b = "+imb"
            elif r["imbalance"] < -0.3: imb_b = "-imb"
            else: imb_b = "0imb"
            k = (side, imb_b)
            buckets[k]["n"] += 1
            buckets[k]["pnl"] += r["pnl_50"]
            buckets[k]["qty"] += r["size"]
        print(f"  {'side':8s} {'imb':8s} {'n':>5s} {'qty':>6s} {'Σ pnl50':>10s} {'pnl50/qty':>10s}")
        for side in ["BUY", "SELL"]:
            for imb_b in ["+imb", "0imb", "-imb"]:
                v = buckets[(side, imb_b)]
                if v["n"] == 0: continue
                pnl_per = v["pnl"] / v["qty"] if v["qty"] else 0
                print(f"  {side:8s} {imb_b:8s} {v['n']:5d} {v['qty']:6d} {v['pnl']:+10.1f} {pnl_per:+10.2f}")

    # Ask the specific question: would a "skip fills with bad imbalance alignment" filter help?
    # Defn: bad alignment = BUY when imbalance strongly negative, SELL when strongly positive
    print("\n=== If we had SKIPPED fills with adverse imbalance ===\n")
    for product in ["ASH_COATED_OSMIUM", "INTARIAN_PEPPER_ROOT"]:
        prows = [r for r in rows if r["product"] == product]
        bad_fills = []
        for r in prows:
            if r["side"] == "BUY" and r["imbalance"] < -0.3:
                bad_fills.append(r)
            elif r["side"] == "SELL" and r["imbalance"] > 0.3:
                bad_fills.append(r)
        tot_pnl = sum(r["pnl_50"] for r in bad_fills)
        n_subs = len(set(r["sub"] for r in rows))
        print(f"{product}: {len(bad_fills)} 'adverse-aligned' fills, Σ pnl_50 = {tot_pnl:+.0f} ({tot_pnl/n_subs:+.0f}/slice)")

    # Momentum feature at fill time
    print("\n=== Fill PnL (50-tick realized) by 5-tick momentum at fill ===\n")
    for sub in LOGS:
        books = books_by_sub[sub]
        sorted_ts_by_prod = defaultdict(list)
        for (ts, prod) in books:
            sorted_ts_by_prod[prod].append(ts)
        for prod in sorted_ts_by_prod:
            sorted_ts_by_prod[prod].sort()
        # Build fast lookup for mid at ts-5_ticks
        pass  # Keep simple — will use log-scan per fill

    # Actually do this inline: compute mom_5 feature for each fill
    for r in rows:
        # Find mid at ts - 500 (5 ticks back)
        sub_books = books_by_sub[r["sub"]]
        target_ts = r["timestamp"] - 500
        mid_5_back = None
        while target_ts >= 0:
            if (target_ts, r["product"]) in sub_books:
                mid_5_back = sub_books[(target_ts, r["product"])]["mid"]
                break
            target_ts -= 100
        if mid_5_back is None:
            r["mom_5"] = 0.0
        else:
            r["mom_5"] = r["mid_at_fill"] - mid_5_back

    for product in ["ASH_COATED_OSMIUM", "INTARIAN_PEPPER_ROOT"]:
        print(f"\n{product}:")
        prows = [r for r in rows if r["product"] == product]
        buckets = defaultdict(lambda: {"n": 0, "pnl": 0.0, "qty": 0})
        for r in prows:
            side = r["side"]
            if r["mom_5"] > 2: mom_b = "+mom"
            elif r["mom_5"] < -2: mom_b = "-mom"
            else: mom_b = "0mom"
            buckets[(side, mom_b)]["n"] += 1
            buckets[(side, mom_b)]["pnl"] += r["pnl_50"]
            buckets[(side, mom_b)]["qty"] += r["size"]
        print(f"  {'side':8s} {'mom':8s} {'n':>5s} {'qty':>6s} {'Σ pnl50':>10s} {'pnl50/qty':>10s}")
        for side in ["BUY", "SELL"]:
            for mom_b in ["+mom", "0mom", "-mom"]:
                v = buckets[(side, mom_b)]
                if v["n"] == 0: continue
                pnl_per = v["pnl"] / v["qty"] if v["qty"] else 0
                print(f"  {side:8s} {mom_b:8s} {v['n']:5d} {v['qty']:6d} {v['pnl']:+10.1f} {pnl_per:+10.2f}")

    # "Skip fills where buying into -mom or selling into +mom"
    print("\n=== If we had SKIPPED momentum-aligned-against-us fills ===\n")
    for product in ["ASH_COATED_OSMIUM", "INTARIAN_PEPPER_ROOT"]:
        prows = [r for r in rows if r["product"] == product]
        bad_fills = []
        for r in prows:
            if r["side"] == "BUY" and r["mom_5"] < -2:
                bad_fills.append(r)
            elif r["side"] == "SELL" and r["mom_5"] > 2:
                bad_fills.append(r)
        tot_pnl = sum(r["pnl_50"] for r in bad_fills)
        n_subs = len(set(r["sub"] for r in rows))
        print(f"{product}: {len(bad_fills)} 'momentum-adverse' fills, Σ pnl_50 = {tot_pnl:+.0f} ({tot_pnl/n_subs:+.0f}/slice)")


if __name__ == "__main__":
    main()
