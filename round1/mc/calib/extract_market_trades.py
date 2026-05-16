"""Extract market_trades (bot-vs-bot trades visible to us as observers)
from 127989.log's per-tick state snapshots. Writes to data/calib/.
"""
from __future__ import annotations
import json
from collections import defaultdict
from pathlib import Path


def main():
    log_path = ("<repo>/"
                "ROUND_1/submissions/127989/127989.log")
    out_path = Path(__file__).parent.parent.parent / "data" / "calib" / "127989_market_trades.json"

    log = json.loads(Path(log_path).read_text())
    # Collect market trades by (product, ts) so server_book_replay can look them up
    mts = []
    for entry in log['logs']:
        parsed = json.loads(entry['lambdaLog'])
        state = parsed[0]
        ts = state[0]
        for t in state[5]:  # market_trades
            sym, price, qty, buyer, seller, ts_mt = t
            mts.append({
                "ts": ts,  # the tick ts at which the trader SAW this trade
                "product": sym,
                "price": price,
                "quantity": qty,
                "buyer": buyer,
                "seller": seller,
                "ts_trade": ts_mt,
            })
    out_path.write_text(json.dumps(mts))
    print(f"Wrote {len(mts)} market trades to {out_path}")

    # Sanity
    from collections import Counter
    qtys_pep = Counter(t["quantity"] for t in mts if t["product"] == "INTARIAN_PEPPER_ROOT")
    qtys_osm = Counter(t["quantity"] for t in mts if t["product"] == "ASH_COATED_OSMIUM")
    print(f"PEPPER qty distribution: {sorted(qtys_pep.items())}")
    print(f"OSMIUM qty distribution: {sorted(qtys_osm.items())}")
    print(f"PEPPER qty=8 events: {qtys_pep[8]}")


if __name__ == "__main__":
    main()
