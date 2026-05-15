"""Joint OSM+PEP sweep against 127989 baseline. Uses calibrated server-book MC."""
from __future__ import annotations
import statistics
import sys
from pathlib import Path
from itertools import product

sys.path.insert(0, str(Path(__file__).parent.parent))
from parametric_trader import make_trader
from server_book_replay import run_server_session


def run_both(osm, pep, n_seeds=50):
    osm_pnls, pep_pnls = [], []
    for s in range(n_seeds):
        t = make_trader(osm=osm, pep=pep)
        osm_pnls.append(run_server_session(t, "ASH_COATED_OSMIUM", seed=s).pnl)
        t = make_trader(osm=osm, pep=pep)
        pep_pnls.append(run_server_session(t, "INTARIAN_PEPPER_ROOT", seed=s).pnl)
    return osm_pnls, pep_pnls


def main():
    n_seeds = 50
    # Baseline = 127989 defaults
    b_osm, b_pep = run_both({}, {}, n_seeds)
    baseline_totals = [o + p for o, p in zip(b_osm, b_pep)]
    bm = statistics.mean(baseline_totals)
    bs = statistics.stdev(baseline_totals)
    print(f"baseline: OSM={statistics.mean(b_osm):.0f}  PEP={statistics.mean(b_pep):.0f}  TOT mean={bm:.0f}  std={bs:.0f}\n")

    edges = [12, 13, 14, 15, 16]
    accum_thrs = [65, 68, 70, 72]
    print(f"{'edge':>4} {'thr':>4}  {'OSM':>5}  {'PEP':>5}  {'TOT':>5}  {'Δ':>5}  {'wins':>5}")
    results = []
    for e, thr in product(edges, accum_thrs):
        o_pnls, p_pnls = run_both({"quote_edge": e}, {"accumulate_threshold": thr}, n_seeds)
        totals = [o + p for o, p in zip(o_pnls, p_pnls)]
        diffs = [t - b for t, b in zip(totals, baseline_totals)]
        dm = statistics.mean(diffs)
        wins = sum(1 for d in diffs if d > 0)
        om = statistics.mean(o_pnls)
        pm = statistics.mean(p_pnls)
        tm = statistics.mean(totals)
        results.append((e, thr, om, pm, tm, dm, wins))
        flag = "*BEAT*" if dm > 0 and wins >= 35 else ""
        print(f"{e:>4d} {thr:>4d}  {om:5.0f}  {pm:5.0f}  {tm:5.0f}  {dm:+5.0f}  {wins:>2d}/{n_seeds}  {flag}")

    # Top 5
    print("\nTop 5 by Δmean:")
    results.sort(key=lambda r: -r[5])
    for e, thr, om, pm, tm, dm, wins in results[:5]:
        print(f"  edge={e:2d} thr={thr:2d}  OSM={om:.0f} PEP={pm:.0f} TOT={tm:.0f} Δ={dm:+.0f} wins={wins}")


if __name__ == "__main__":
    main()
