"""At the suspicious deep-fill ticks (24900, 33800, 94700, 98200), what did the
OSM book look like? Why was strat@10022 the best ask?
"""
from __future__ import annotations
import json
from pathlib import Path

DATA = Path(__file__).parent.parent.parent / "data" / "calib"
acts = json.loads((DATA / "127989_activities.json").read_text())

for ts_watch in [24900, 33800, 87800, 94700, 98200]:
    for a in acts:
        if a["product"] == "ASH_COATED_OSMIUM" and a["ts"] == ts_watch:
            print(f"\nts={ts_watch}")
            print(f"  bids: {a['bids']}")
            print(f"  asks: {a['asks']}")
            print(f"  mid:  {a['mid_price']}")
            break
