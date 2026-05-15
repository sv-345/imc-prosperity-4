"""Deep dive on iter23's PnL acceleration windows.

Extract for each window:
  - trades (prices, sides, qtys)
  - book depths (bid/ask, vols)
  - iter23's lambda logs if present (shows our orders per tick)
  - PnL delta per product per 1K-ts sub-segment
"""
from __future__ import annotations
import json, io, csv, pathlib, re
import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
LOG = pathlib.Path('/tmp/prosperity_logs/303257/312201.log')
JSON = pathlib.Path('/tmp/prosperity_logs/303257/312201.json')


def main():
    d = json.load(open(JSON))
    log = open(LOG).read()
    print('log size:', len(log), 'chars')
    # log has per-tick JSON blocks (lambdaLog)
    # Check format
    # typical structure: each tick is a JSON record
    print('log first 400 chars:', log[:400])
    print()
    print('...log near ts=34000:')
    idx = log.find('34000')
    if idx >= 0:
        print(log[idx:idx+500])


if __name__ == "__main__":
    main()
