"""Pool two MC seeds to tighten the V5 PEP-Kalman CI."""
import csv, json, math, statistics
from pathlib import Path

def load(path):
    rows = []
    with open(path) as f:
        r = csv.DictReader(f)
        for row in r:
            prod = json.loads(row["product_stats_json"])
            rows.append(
                {
                    "sid": int(row["session_id"]),
                    "day": int(row["day"]),
                    "total": float(row["total_pnl"]),
                    "osm": float(prod.get("ASH_COATED_OSMIUM", {}).get("pnl", 0)),
                    "pep": float(prod.get("INTARIAN_PEPPER_ROOT", {}).get("pnl", 0)),
                }
            )
    rows.sort(key=lambda r: r["sid"])
    return rows


BASE = Path("<repo>/research_org/researchers/project_latent_fv_kalman/phase_b/b1_mc_results")
v0a = load(BASE / "V0_iter23_baseline.csv")
v5a = load(BASE / "V5_pep_only_kalman.csv")
v0b = load(BASE / "V0_iter23_baseline_seed2.csv")
v5b = load(BASE / "V5_pep_only_kalman_seed2.csv")

def paired_stats(b, v, key="total"):
    d = [x[key] - y[key] for x, y in zip(v, b)]
    n = len(d)
    m = sum(d) / n
    s = statistics.stdev(d)
    se = s / math.sqrt(n)
    return m, se, n, d

for name, b, v in [("seed1", v0a, v5a), ("seed2", v0b, v5b)]:
    for key in ("total", "osm", "pep"):
        m, se, n, _ = paired_stats(b, v, key)
        print(f"{name} {key}: n={n} mean={m:+.2f} se={se:.2f} 95%CI=[{m-1.984*se:+.2f},{m+1.984*se:+.2f}]")

# Pooled across seeds (200 paired observations)
print()
d_total = [x["total"] - y["total"] for x, y in zip(v5a + v5b, v0a + v0b)]
d_pep = [x["pep"] - y["pep"] for x, y in zip(v5a + v5b, v0a + v0b)]
d_osm = [x["osm"] - y["osm"] for x, y in zip(v5a + v5b, v0a + v0b)]
for label, d in (("total", d_total), ("osm", d_osm), ("pep", d_pep)):
    n = len(d)
    m = sum(d) / n
    s = statistics.stdev(d)
    se = s / math.sqrt(n)
    print(f"POOLED {label}: n={n} mean={m:+.2f} se={se:.2f} 95%CI=[{m-1.96*se:+.2f},{m+1.96*se:+.2f}]")

# Per-day across pooled
print()
by_day = {-1: [], 0: [], 1: []}
for x, y in zip(v5a + v5b, v0a + v0b):
    by_day[x["day"]].append(x["total"] - y["total"])
for d in (-1, 0, 1):
    ds = by_day[d]
    n = len(ds)
    m = sum(ds) / n
    s = statistics.stdev(ds)
    se = s / math.sqrt(n)
    print(f"POOLED day {d:+d} total: n={n} mean={m:+.2f} se={se:.2f} 95%CI=[{m-1.96*se:+.2f},{m+1.96*se:+.2f}]")
