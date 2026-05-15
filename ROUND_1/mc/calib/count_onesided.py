"""How often does OSM / PEP book go one-sided? Count by session.

A one-sided tick is where either bids=[] or asks=[]. At those ticks, a wider-edge
quote becomes the only provider and captures edge-tick PnL per fill.
"""
from __future__ import annotations
import csv
import json
from pathlib import Path

DATA = Path(__file__).parent.parent.parent / "data" / "calib"
RAW = Path(__file__).parent.parent.parent / "data" / "ROUND1"


def live_session(sid):
    acts = json.loads((DATA / f"{sid}_activities.json").read_text())
    return acts


def training_day(day):
    path = RAW / f"prices_round_1_day_{day}.csv"
    rows = []
    with open(path) as f:
        reader = csv.DictReader(f, delimiter=";")
        for r in reader:
            ts = int(r["timestamp"])
            prod = r["product"]
            bids = [(int(r[f"bid_price_{i}"]), int(r[f"bid_volume_{i}"]))
                    for i in (1,2,3) if r[f"bid_price_{i}"]]
            asks = [(int(r[f"ask_price_{i}"]), int(r[f"ask_volume_{i}"]))
                    for i in (1,2,3) if r[f"ask_price_{i}"]]
            rows.append({"ts": ts, "product": prod, "bids": bids, "asks": asks})
    return rows


def analyze(rows, name):
    by_prod = {"ASH_COATED_OSMIUM": {"total": 0, "no_ask": 0, "no_bid": 0, "onesided": 0},
               "INTARIAN_PEPPER_ROOT": {"total": 0, "no_ask": 0, "no_bid": 0, "onesided": 0}}
    for r in rows:
        p = r["product"]
        if p not in by_prod:
            continue
        by_prod[p]["total"] += 1
        if not r["asks"]:
            by_prod[p]["no_ask"] += 1
        if not r["bids"]:
            by_prod[p]["no_bid"] += 1
        if not r["asks"] or not r["bids"]:
            by_prod[p]["onesided"] += 1
    print(f"\n=== {name} ===")
    for p, d in by_prod.items():
        pct = 100 * d["onesided"] / max(1, d["total"])
        print(f"  {p}: {d['total']} ticks, no_ask={d['no_ask']} "
              f"no_bid={d['no_bid']} one-sided={d['onesided']} ({pct:.2f}%)")


def main():
    for sid in ["127989", "113620", "114525"]:
        analyze(live_session(sid), f"live {sid}")
    for day in ["-2", "-1", "0"]:
        analyze(training_day(day), f"training day={day}")


if __name__ == "__main__":
    main()
