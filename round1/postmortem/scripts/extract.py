"""Extract official R1 data from 273632.log into CSVs.

Produces:
  artifacts/prices_official.csv  (book snapshots: day,timestamp,product,bid1..3,ask1..3,mid,pnl)
  artifacts/trades_official.csv  (all trades: timestamp,symbol,buyer,seller,price,qty)
  artifacts/our_fills.csv        (SUBMISSION-only fills; side=BUY/SELL, qty positive)
  artifacts/graph_pnl.csv        (timestamp, cumulative pnl)
"""
from __future__ import annotations
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ART = ROOT / "artifacts"
ART.mkdir(parents=True, exist_ok=True)

LOG = Path("<repo>/ROUND_1/R1Final/273632/273632.log")


def main() -> None:
    with LOG.open() as f:
        d = json.load(f)

    # 1. activitiesLog -> prices_official.csv (already CSV-like)
    prices_path = ART / "prices_official.csv"
    with prices_path.open("w") as f:
        # normalize: keep semicolons, but also write a comma version for easier consumption
        f.write(d["activitiesLog"])
    # also write comma-delimited copy
    csv_path = ART / "prices_official_comma.csv"
    lines = d["activitiesLog"].splitlines()
    with csv_path.open("w", newline="") as f:
        w = csv.writer(f)
        for line in lines:
            w.writerow(line.split(";"))

    # 2. tradeHistory -> trades_official.csv
    trades_path = ART / "trades_official.csv"
    with trades_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["timestamp", "symbol", "buyer", "seller", "price", "quantity", "currency"])
        for t in d["tradeHistory"]:
            w.writerow([
                t["timestamp"], t["symbol"],
                t.get("buyer", ""), t.get("seller", ""),
                t["price"], t["quantity"], t.get("currency", ""),
            ])

    # 3. our fills only
    fills_path = ART / "our_fills.csv"
    with fills_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["timestamp", "symbol", "side", "price", "quantity"])
        for t in d["tradeHistory"]:
            if t.get("buyer") == "SUBMISSION":
                w.writerow([t["timestamp"], t["symbol"], "BUY", t["price"], t["quantity"]])
            elif t.get("seller") == "SUBMISSION":
                w.writerow([t["timestamp"], t["symbol"], "SELL", t["price"], t["quantity"]])

    # 4. graphLog (from 273632.json) -> graph_pnl.csv
    jf = Path("<repo>/ROUND_1/R1Final/273632/273632.json")
    if jf.exists():
        with jf.open() as f:
            jd = json.load(f)
        gp = ART / "graph_pnl.csv"
        with gp.open("w", newline="") as f:
            w = csv.writer(f)
            for line in jd["graphLog"].splitlines():
                w.writerow(line.split(";"))
    else:
        jd = None

    # 5. Final summary printed
    status = {
        "profit_reported": jd.get("profit") if jd else None,
        "submissionId": d.get("submissionId"),
        "n_ticks_book": sum(1 for _ in d["activitiesLog"].splitlines()) - 1,
        "n_trades": len(d["tradeHistory"]),
        "n_our_fills": sum(1 for t in d["tradeHistory"] if "SUBMISSION" in (t.get("buyer"), t.get("seller"))),
        "n_bot_bot": sum(1 for t in d["tradeHistory"] if not t.get("buyer") and not t.get("seller")),
    }
    summary_path = ART / "extract_summary.json"
    with summary_path.open("w") as f:
        json.dump(status, f, indent=2)
    print(json.dumps(status, indent=2))


if __name__ == "__main__":
    main()
