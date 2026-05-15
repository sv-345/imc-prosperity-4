"""Round 2 validation: KS tests of simulated vs empirical distributions.

Compares the simulated CSVs in `tmp/round2_gen/round2/` against the empirical
CSVs in `data/round2/` across:

  * mid-price
  * per-trade quantity
  * top-of-book spread

Fails loudly (exit 1) if any KS p-value is < 0.01 and prints a proposed
parameter fix. Run as:

    # 1) Generate synthetic CSVs first
    rust_simulator/target/release/rust_simulator --round 2 \\
        --fv-mode simulate --trade-mode simulate \\
        --output tmp/round2_gen
    # 2) Validate
    python scripts/round2_calibration/validate_round2.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parents[2]
EMP = ROOT / "data" / "round2"
SIM = ROOT / "tmp" / "round2_gen" / "round2"
DAYS = [-1, 0, 1]
PRODUCTS = ["ASH_COATED_OSMIUM", "INTARIAN_PEPPER_ROOT"]
REPORT = ROOT / "docs" / "round2_validation.md"
THRESHOLD = 0.01


def load_prices(root: Path) -> pd.DataFrame:
    frames = []
    for d in DAYS:
        p = root / f"prices_round_2_day_{d}.csv"
        if not p.exists():
            print(f"Missing {p}")
            sys.exit(1)
        df = pd.read_csv(p, sep=";")
        df["day"] = d
        frames.append(df)
    out = pd.concat(frames, ignore_index=True)
    return out[out.mid_price > 0].reset_index(drop=True)


def load_trades(root: Path) -> pd.DataFrame:
    frames = []
    for d in DAYS:
        p = root / f"trades_round_2_day_{d}.csv"
        if not p.exists():
            print(f"Missing {p}")
            sys.exit(1)
        df = pd.read_csv(p, sep=";")
        df["day"] = d
        frames.append(df)
    return pd.concat(frames, ignore_index=True)


def compute_spread(df: pd.DataFrame) -> pd.Series:
    return df["ask_price_1"] - df["bid_price_1"]


def ks_report(name: str, emp: np.ndarray, sim: np.ndarray) -> tuple[str, float]:
    if len(emp) == 0 or len(sim) == 0:
        return f"  {name}: EMPTY (emp n={len(emp)}, sim n={len(sim)})", 1.0
    stat, pval = stats.ks_2samp(emp, sim)
    emp_mean, emp_std = float(np.mean(emp)), float(np.std(emp))
    sim_mean, sim_std = float(np.mean(sim)), float(np.std(sim))
    status = "PASS" if pval >= THRESHOLD else "FAIL"
    line = (
        f"  {name}: KS={stat:.4f} p={pval:.2e} [{status}] "
        f"emp μ={emp_mean:.2f} σ={emp_std:.2f} (n={len(emp)})  "
        f"sim μ={sim_mean:.2f} σ={sim_std:.2f} (n={len(sim)})"
    )
    return line, pval


def suggest_fix(name: str, emp: np.ndarray, sim: np.ndarray) -> str:
    if len(emp) == 0 or len(sim) == 0:
        return "  → check that both CSVs were produced for this metric"
    emp_m, sim_m = np.mean(emp), np.mean(sim)
    if abs(emp_m - sim_m) / (abs(emp_m) + 1) > 0.01:
        return f"  → mean mismatch ({emp_m:.2f} vs {sim_m:.2f}); re-check the anchor constant in rust_simulator/src/main.rs"
    emp_s, sim_s = np.std(emp), np.std(sim)
    if emp_s > 0 and abs(emp_s - sim_s) / emp_s > 0.3:
        return f"  → spread mismatch ({emp_s:.2f} vs {sim_s:.2f}); adjust volume U-range or bot-3 presence rate"
    return "  → shape mismatch; inspect histogram"


def main() -> None:
    if not SIM.exists():
        print(f"No simulated data at {SIM}. Run the rust_simulator --round 2 first.")
        sys.exit(1)

    emp_prices = load_prices(EMP)
    sim_prices = load_prices(SIM)
    emp_trades = load_trades(EMP)
    sim_trades = load_trades(SIM)

    lines: list[str] = ["# Round 2 Validation — KS tests\n"]
    lines.append(f"Empirical: `data/round2/` (3 days, {len(emp_prices):,} price rows)")
    lines.append(f"Simulated: `tmp/round2_gen/round2/` (3 days, {len(sim_prices):,} price rows)\n")
    lines.append(f"Threshold: fail when KS p < {THRESHOLD}\n")

    any_fail = False
    for product in PRODUCTS:
        lines.append(f"\n## {product}\n")
        emp_p = emp_prices[emp_prices["product"] == product]
        sim_p = sim_prices[sim_prices["product"] == product]

        # PEP mid drifts deterministically across ticks — comparing raw mid
        # distributions is not informative (it's ~uniform over the drift
        # range). Instead, compare the demeaned mid (mid - linear-fit drift)
        # to probe the noise process.
        if product == "INTARIAN_PEPPER_ROOT":
            def detrend(df: pd.DataFrame) -> np.ndarray:
                out = []
                for d in DAYS:
                    sub = df[df["day"] == d]
                    t = sub["timestamp"].to_numpy() / 100.0
                    y = sub["mid_price"].to_numpy()
                    slope, intercept = np.polyfit(t, y, 1)
                    resid = y - (slope * t + intercept)
                    out.append(resid)
                return np.concatenate(out)

            line, p = ks_report("mid-price (detrended)", detrend(emp_p), detrend(sim_p))
        else:
            line, p = ks_report(
                "mid-price",
                emp_p["mid_price"].to_numpy(),
                sim_p["mid_price"].to_numpy(),
            )
        lines.append(line)
        if p < THRESHOLD:
            any_fail = True
            lines.append(suggest_fix("mid-price", emp_p["mid_price"].to_numpy(),
                                      sim_p["mid_price"].to_numpy()))

        # Spread
        emp_s = compute_spread(emp_p).dropna().to_numpy()
        sim_s = compute_spread(sim_p).dropna().to_numpy()
        line, p = ks_report("spread", emp_s, sim_s)
        lines.append(line)
        if p < THRESHOLD:
            any_fail = True
            lines.append(suggest_fix("spread", emp_s, sim_s))

        # Trade quantity
        emp_q = emp_trades[emp_trades["symbol"] == product]["quantity"].to_numpy()
        sim_q = sim_trades[sim_trades["symbol"] == product]["quantity"].to_numpy()
        line, p = ks_report("trade-qty", emp_q, sim_q)
        lines.append(line)
        if p < THRESHOLD:
            any_fail = True
            lines.append(suggest_fix("trade-qty", emp_q, sim_q))

    report = "\n".join(lines)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(report + "\n")
    print(report)
    if any_fail:
        print(f"\n[FAIL] at least one metric below p={THRESHOLD}; see suggestions above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
