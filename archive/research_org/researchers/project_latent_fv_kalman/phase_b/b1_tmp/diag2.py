import csv, sys, statistics
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "b1_variants"))
from _kalman_core import LatentFVKalman


def inner_mid_osm(row):
    ib = ia = None
    for i in (1, 2, 3):
        p = row.get(f"bid_price_{i}", "")
        v = row.get(f"bid_volume_{i}", "")
        if p and v and 10 <= int(v) <= 15:
            ib = float(p)
            break
    for i in (1, 2, 3):
        p = row.get(f"ask_price_{i}", "")
        v = row.get(f"ask_volume_{i}", "")
        if p and v and 10 <= int(v) <= 15:
            ia = float(p)
            break
    if ib is not None and ia is not None and 15 <= ia - ib <= 17:
        return (ib + ia) / 2.0
    if ib is not None:
        return ib + 8.0
    if ia is not None:
        return ia - 8.0
    return None


path = Path("<repo>/research_org/researchers/project_latent_fv_kalman/phase_b/b1_tmp/V0_iter23/sessions/session_00000/round2/prices_round_2_day_-1.csv")
filt = LatentFVKalman.cold_osm()
init = False
ys = []
fvs = []
first_100 = []
with path.open() as f:
    r = csv.DictReader(f, delimiter=";")
    for row in r:
        if row["product"] != "ASH_COATED_OSMIUM":
            continue
        bb_s = row.get("bid_price_1", "")
        ba_s = row.get("ask_price_1", "")
        one_sided = not (bb_s and ba_s)
        y = inner_mid_osm(row)
        if not init and y is not None:
            filt.tick = int(row["timestamp"]) // 100 - 1
            init = True
        filt.update(y, one_sided=one_sided)
        if y is not None:
            ys.append(y)
        fvs.append(filt.fv())
        if len(fvs) <= 30:
            first_100.append((row["timestamp"], y, filt.fv(), filt.P, one_sided))

print(f"n ticks = {len(fvs)}")
print(f"y (inner-mid): mean={statistics.mean(ys):.3f}  std={statistics.stdev(ys):.3f}")
print(f"fv (filter):   mean={statistics.mean(fvs):.3f}  std={statistics.stdev(fvs):.3f}")
print("\nFirst 30 ticks:")
for ts, y, fv, P, os in first_100:
    print(f"  ts={ts}  y={y}  fv={fv:.3f}  P={P:.3f}  one_sided={os}")
