"""Extract activities + market_trades for 113620, 114525 (in addition to 127989).

Source: each submission's .log file (JSON with activitiesLog, logs, tradeHistory).

Writes per session <sid>:
  data/calib/<sid>_activities.json
  data/calib/<sid>_market_trades.json

This allows cross-session validation: a real strategy improvement should beat
the baseline on all three sessions (113620, 114525, 127989), not just one.
"""
from __future__ import annotations
import json
from pathlib import Path

OUT_DIR = Path(__file__).parent.parent.parent / "data" / "calib"


def parse_activities_log(activities_str: str):
    """Parse CSV-formatted activitiesLog into list of per-tick rows."""
    lines = activities_str.strip().split("\n")
    header = lines[0].split(";")
    rows = []
    for line in lines[1:]:
        c = line.split(";")
        if len(c) < len(header):
            continue
        ts = int(c[1])
        product = c[2]

        def i(col):
            v = c[col]
            return int(v) if v else None

        def f(col):
            v = c[col]
            return float(v) if v else None

        bids = []
        for pi, vi in [(3, 4), (5, 6), (7, 8)]:
            bp, bv = i(pi), i(vi)
            if bp is not None:
                bids.append([bp, bv])
        asks = []
        for pi, vi in [(9, 10), (11, 12), (13, 14)]:
            ap, av = i(pi), i(vi)
            if ap is not None:
                asks.append([ap, av])
        rows.append({
            "ts": ts, "product": product,
            "bids": bids, "asks": asks,
            "mid_price": f(15), "pnl": f(16),
        })
    return rows


def extract_market_trades(logs):
    mts = []
    for entry in logs:
        parsed = json.loads(entry['lambdaLog'])
        state = parsed[0]
        ts = state[0]
        for t in state[5]:
            sym, price, qty, buyer, seller, ts_mt = t
            mts.append({
                "ts": ts, "product": sym,
                "price": price, "quantity": qty,
                "buyer": buyer, "seller": seller,
                "ts_trade": ts_mt,
            })
    return mts


def extract_session(sid):
    log_path = f"<repo>/ROUND_1/submissions/{sid}/{sid}.log"
    log = json.loads(Path(log_path).read_text())
    acts = parse_activities_log(log['activitiesLog'])
    mts = extract_market_trades(log['logs'])
    (OUT_DIR / f"{sid}_activities.json").write_text(json.dumps(acts))
    (OUT_DIR / f"{sid}_market_trades.json").write_text(json.dumps(mts))
    # Sanity
    osm_ticks = sum(1 for a in acts if a['product']=='ASH_COATED_OSMIUM')
    pep_ticks = sum(1 for a in acts if a['product']=='INTARIAN_PEPPER_ROOT')
    print(f"{sid}: {len(acts)} act rows  ({osm_ticks} OSM + {pep_ticks} PEP)  {len(mts)} market trades")


def main():
    for sid in ["113620", "114525"]:
        extract_session(sid)


if __name__ == "__main__":
    main()
