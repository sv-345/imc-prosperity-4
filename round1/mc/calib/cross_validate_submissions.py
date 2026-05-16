"""Cross-validate server-book replay against all 4 submissions.

Server PnL totals (from each submission's JSON):
    110534:  3,940  (probably a bad run / different strategy)
    113620: 10,114
    114525: 10,413
    127989: 10,721

Goal: server-book replay (with calibrated MC takers) should rank them in the
same order. This is the strongest validation signal for our MC.
"""
from __future__ import annotations
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from server_book_replay import run_server_session
from synth_replay import _load_trader_from_path


SUBS = {
    "110534":  "<repo>/ROUND_1/submissions/110534/110534.py",
    "113620":  "<repo>/ROUND_1/submissions/113620/113620.py",
    "114525":  "<repo>/ROUND_1/submissions/114525/114525.py",
    "127989":  "<repo>/ROUND_1/submissions/127989/127989.py",
}

SERVER_PNL = {
    "110534":  3940,
    "113620": 10114,
    "114525": 10413,
    "127989": 10721,
}


def main():
    n_seeds = 50
    print(f"Server-book replay, {n_seeds} seeds each\n")
    print(f"{'sub':>8}  {'OSM mean±std':>16}  {'PEP mean±std':>16}  "
          f"{'TOT mean':>9}  {'server':>6}")
    results = {}
    for sid, path in SUBS.items():
        osm_pnls = []
        pep_pnls = []
        for s in range(n_seeds):
            t = _load_trader_from_path(path)
            osm_pnls.append(run_server_session(t, "ASH_COATED_OSMIUM", seed=s).pnl)
            t = _load_trader_from_path(path)
            pep_pnls.append(run_server_session(t, "INTARIAN_PEPPER_ROOT", seed=s).pnl)
        om = statistics.mean(osm_pnls)
        os_ = statistics.stdev(osm_pnls)
        pm = statistics.mean(pep_pnls)
        ps = statistics.stdev(pep_pnls)
        tot = om + pm
        results[sid] = {"osm": om, "pep": pm, "tot": tot}
        print(f"{sid:>8}  {om:8.0f}±{os_:4.0f}  {pm:8.0f}±{ps:4.0f}  "
              f"{tot:9.0f}  {SERVER_PNL[sid]:6d}")

    # Rank
    print("\nRanking:")
    mc_rank = sorted(results.items(), key=lambda kv: -kv[1]["tot"])
    sv_rank = sorted(SERVER_PNL.items(), key=lambda kv: -kv[1])
    print(f"  MC:     {' > '.join(k for k,_ in mc_rank)}")
    print(f"  server: {' > '.join(k for k,_ in sv_rank)}")

    # Spearman correlation
    ids = list(SERVER_PNL.keys())
    mc_totals = [results[i]["tot"] for i in ids]
    sv_totals = [SERVER_PNL[i] for i in ids]
    # Spearman via rank
    def ranks(vals):
        pairs = sorted(enumerate(vals), key=lambda x: x[1])
        r = [0] * len(vals)
        for i, (idx, _) in enumerate(pairs):
            r[idx] = i + 1
        return r
    rm = ranks(mc_totals)
    rs = ranks(sv_totals)
    n = len(ids)
    # Spearman for no ties: rho = 1 - 6 sum(d^2)/(n(n^2-1))
    ssd = sum((a - b) ** 2 for a, b in zip(rm, rs))
    rho = 1 - 6 * ssd / (n * (n * n - 1)) if n > 2 else None
    print(f"\n  Spearman ρ = {rho:.3f}" if rho is not None else "")


if __name__ == "__main__":
    main()
