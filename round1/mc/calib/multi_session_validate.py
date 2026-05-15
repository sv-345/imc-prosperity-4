"""Validate candidate edge tweaks on 3 server sessions (113620, 114525, 127989).

A real improvement must beat baseline on ALL THREE sessions with consistent
paired-diff sign. This guards against overfitting to 127989's specific book.
"""
from __future__ import annotations
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from parametric_trader import make_trader
import server_book_replay as sbr


def run_on_session(session, osm_params, pep_params, n_seeds=50):
    """Run trader on given session's books."""
    osm_pnls, pep_pnls = [], []
    for s in range(n_seeds):
        # Monkey-patch the session
        original_load_ticks = sbr.load_ticks
        original_load_mt = sbr.load_market_trades
        sbr.load_ticks = lambda product: original_load_ticks(product, session=session)
        sbr.load_market_trades = lambda product: original_load_mt(product, session=session)
        try:
            t = make_trader(osm=osm_params, pep=pep_params)
            osm_pnls.append(sbr.run_server_session(t, "ASH_COATED_OSMIUM", seed=s).pnl)
            t = make_trader(osm=osm_params, pep=pep_params)
            pep_pnls.append(sbr.run_server_session(t, "INTARIAN_PEPPER_ROOT", seed=s).pnl)
        finally:
            sbr.load_ticks = original_load_ticks
            sbr.load_market_trades = original_load_mt
    return osm_pnls, pep_pnls


SERVER_PNL = {
    "113620": {"OSM": 2828, "PEP": 7286, "TOT": 10114},
    "114525": {"OSM": 3127, "PEP": 7286, "TOT": 10413},
    "127989": {"OSM": 3144, "PEP": 7577, "TOT": 10721},
}


def main():
    candidates = [
        ("baseline",    {}, {}),
        ("edge=13",     {"quote_edge": 13}, {}),
        ("edge=14",     {"quote_edge": 14}, {}),
        ("edge=15",     {"quote_edge": 15}, {}),
        ("edge=16",     {"quote_edge": 16}, {}),
        ("edge=18",     {"quote_edge": 18}, {}),
        ("thr=65",      {}, {"accumulate_threshold": 65}),
        ("thr=68",      {}, {"accumulate_threshold": 68}),
        ("e14+t68",     {"quote_edge": 14}, {"accumulate_threshold": 68}),
        ("e16+t65",     {"quote_edge": 16}, {"accumulate_threshold": 65}),
    ]
    sessions = ["113620", "114525", "127989"]

    print(f"{'candidate':>10}  " + "  ".join(f"{s:>8}" for s in sessions) + "  avg_total")
    # First baseline per session
    baselines = {}
    print("  -- baseline (127989 defaults) --")
    for s in sessions:
        op, pp = run_on_session(s, {}, {}, n_seeds=30)
        tot = [o + p for o, p in zip(op, pp)]
        baselines[s] = (statistics.mean(op), statistics.mean(pp), statistics.mean(tot), tot)
    print(f"{'defaults':>10}  " + "  ".join(f"{baselines[s][2]:8.0f}" for s in sessions) +
          f"   {sum(baselines[s][2] for s in sessions)/3:.0f}")
    print(f"{'(server)':>10}  " + "  ".join(f"{SERVER_PNL[s]['TOT']:8d}" for s in sessions) +
          f"   {sum(SERVER_PNL[s]['TOT'] for s in sessions)/3:.0f}")

    print("\n  -- candidates (paired diffs vs baseline, 3 sessions) --")
    for name, osm, pep in candidates:
        if name == "baseline":
            continue
        line = f"{name:>10}  "
        pass_count = 0
        total_gain = 0
        for s in sessions:
            op, pp = run_on_session(s, osm, pep, n_seeds=30)
            tot = [o + p for o, p in zip(op, pp)]
            diffs = [t - b for t, b in zip(tot, baselines[s][3])]
            dm = statistics.mean(diffs)
            wins = sum(1 for d in diffs if d > 0)
            total_gain += dm
            line += f"{dm:+5.0f}({wins:>2d}/30) "
            if dm > 0 and wins >= 20:
                pass_count += 1
        line += f"  avg_Δ={total_gain/3:+.0f}"
        line += "  ROBUST" if pass_count == 3 else f"  ({pass_count}/3)"
        print(line)


if __name__ == "__main__":
    main()
