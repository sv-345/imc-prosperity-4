"""Analyze R2 per-fill ledger for specific leak categories.

For each of the categories in the user's task section 1.2, compute $ cost
across all 4 v82-family submissions and generate tables.

Output: docs/round2_postmortem/leaks.md
"""

from __future__ import annotations

import csv
import math
from collections import defaultdict, Counter
from pathlib import Path

LEDGER_CSV = Path("<repo>/chrispyroberts-imc-prosperity-4/scripts/r2_postmortem/ledger_all.csv")
DOC = Path("<repo>/chrispyroberts-imc-prosperity-4/docs/round2_postmortem/leaks.md")


def load() -> list[dict]:
    rows = []
    with LEDGER_CSV.open() as f:
        for r in csv.DictReader(f):
            for k in ("timestamp", "size", "inv_before", "inv_after", "adverse_N2_M10", "adverse_N4_M50"):
                r[k] = int(r[k]) if r[k] != "" else 0
            for k in ("price", "mid_at_fill", "edge_at_fill", "mid_plus_10", "mid_plus_50", "mid_plus_200", "realized_pnl_fifo"):
                try:
                    r[k] = float(r[k])
                except ValueError:
                    r[k] = float("nan")
            rows.append(r)
    return rows


def isnan(x):
    return isinstance(x, float) and math.isnan(x)


def markout_signed(r: dict, horizon: str) -> float:
    """Signed markout: positive = profitable move for our side."""
    m = r[horizon]
    if isnan(m) or isnan(r["mid_at_fill"]):
        return float("nan")
    return (m - r["mid_at_fill"]) if r["side"] == "BUY" else (r["mid_at_fill"] - m)


def edge_bucket(e: float) -> str:
    if isnan(e):
        return "nan"
    if e >= 5: return "deep_passive(≥5)"
    if e >= 2: return "med_passive(2-5)"
    if e >= 0: return "shallow_passive(0-2)"
    if e >= -2: return "weak_cross(-2-0)"
    return "deep_cross(<-2)"


def main():
    rows = load()
    n_subs = len(set(r["sub"] for r in rows))
    print(f"Loaded {len(rows)} fills across {n_subs} submissions.")

    lines = ["# Round 2 — Self Post-mortem: Leak Categories\n"]
    lines.append(f"Source: {LEDGER_CSV}. {len(rows)} fills across {n_subs} v82-family submissions (iter 12 run 1, iter 12 run 2, iter 13, iter 14). Averaged to per-submission-slice ($/slice = total / n_subs).\n")

    # Overall edge distribution + forward markout by bucket
    lines.append("## Edge-at-fill × markout profile\n")
    by_bucket = defaultdict(lambda: {"n": 0, "qty": 0, "edge_sum": 0.0, "mk50_sum": 0.0, "mk200_sum": 0.0, "mk50_n": 0, "mk200_n": 0})
    for r in rows:
        b = edge_bucket(r["edge_at_fill"])
        bb = by_bucket[b]
        bb["n"] += 1
        bb["qty"] += r["size"]
        if not isnan(r["edge_at_fill"]):
            bb["edge_sum"] += r["edge_at_fill"] * r["size"]
        mk50 = markout_signed(r, "mid_plus_50")
        if not isnan(mk50):
            bb["mk50_sum"] += mk50 * r["size"]
            bb["mk50_n"] += r["size"]
        mk200 = markout_signed(r, "mid_plus_200")
        if not isnan(mk200):
            bb["mk200_sum"] += mk200 * r["size"]
            bb["mk200_n"] += r["size"]
    lines.append("| bucket | fills | qty | Σ edge·qty | Σ mk50·qty | mk50 per unit |")
    lines.append("|---|---:|---:|---:|---:|---:|")
    for b in ["deep_passive(≥5)", "med_passive(2-5)", "shallow_passive(0-2)", "weak_cross(-2-0)", "deep_cross(<-2)"]:
        bb = by_bucket[b]
        if bb["n"] == 0: continue
        mk50_pu = bb["mk50_sum"] / bb["mk50_n"] if bb["mk50_n"] else float("nan")
        lines.append(f"| {b} | {bb['n']} | {bb['qty']} | {bb['edge_sum']:+.1f} | {bb['mk50_sum']:+.1f} | {mk50_pu:+.2f} |")
    lines.append("")

    # Split by product
    for product in ["ASH_COATED_OSMIUM", "INTARIAN_PEPPER_ROOT"]:
        prows = [r for r in rows if r["product"] == product]
        lines.append(f"\n### {product} — edge × markout\n")
        lines.append("| bucket | fills | qty | Σ edge·qty | Σ mk50·qty | mk50/unit |")
        lines.append("|---|---:|---:|---:|---:|---:|")
        bb_p = defaultdict(lambda: {"n": 0, "qty": 0, "edge_sum": 0.0, "mk50_sum": 0.0, "mk50_n": 0})
        for r in prows:
            b = edge_bucket(r["edge_at_fill"])
            v = bb_p[b]
            v["n"] += 1
            v["qty"] += r["size"]
            if not isnan(r["edge_at_fill"]):
                v["edge_sum"] += r["edge_at_fill"] * r["size"]
            mk50 = markout_signed(r, "mid_plus_50")
            if not isnan(mk50):
                v["mk50_sum"] += mk50 * r["size"]
                v["mk50_n"] += r["size"]
        for b in ["deep_passive(≥5)", "med_passive(2-5)", "shallow_passive(0-2)", "weak_cross(-2-0)", "deep_cross(<-2)"]:
            v = bb_p[b]
            if v["n"] == 0: continue
            mk50_pu = v["mk50_sum"] / v["mk50_n"] if v["mk50_n"] else float("nan")
            lines.append(f"| {b} | {v['n']} | {v['qty']} | {v['edge_sum']:+.1f} | {v['mk50_sum']:+.1f} | {mk50_pu:+.2f} |")

    # Leak 1.2.1 adverse selection
    lines.append("\n## 1.2.1 Adverse selection ($)\n")
    adv_cost_50 = 0.0
    adv_cost_10 = 0.0
    for r in rows:
        mk50 = markout_signed(r, "mid_plus_50")
        mk10 = markout_signed(r, "mid_plus_10")
        if r["adverse_N4_M50"] and not isnan(mk50):
            adv_cost_50 += mk50 * r["size"]  # negative
        if r["adverse_N2_M10"] and not isnan(mk10):
            adv_cost_10 += mk10 * r["size"]
    lines.append(f"- Fills flagged adverse (N4,M50): {sum(1 for r in rows if r['adverse_N4_M50'])} of {len(rows)} ({100*sum(1 for r in rows if r['adverse_N4_M50'])/len(rows):.1f}%)")
    lines.append(f"- Σ mk50·qty on adverse fills: **{adv_cost_50:+.0f}** ({adv_cost_50/n_subs:+.0f}/slice)")
    lines.append(f"- Σ mk10·qty on adverse(N2,M10) fills: **{adv_cost_10:+.0f}** ({adv_cost_10/n_subs:+.0f}/slice)")

    # Leak 1.2.2 Position-limit blocking: look at moments when inv_before == ±80
    lines.append("\n## 1.2.2 Position at ±80 (fills when we were maxed)\n")
    at_limit = [r for r in rows if abs(r["inv_before"]) == 80]
    lines.append(f"- Fills with |inv_before| = 80: **{len(at_limit)}** ({100*len(at_limit)/len(rows):.1f}%).")
    lines.append(f"- Per product: " + ", ".join(f"{p}={sum(1 for r in at_limit if r['product']==p)}" for p in ["ASH_COATED_OSMIUM", "INTARIAN_PEPPER_ROOT"]))
    lines.append("- Interpretation: we could only UNWIND (sell when long, buy when short) from this position. Any opportunity to add same-side was blocked. Post-hoc: can we see evidence of missed take fills?")
    # Count cases where a very-high-edge same-side opportunity existed while we were at limit — hard without full book snapshots; skip for now

    # Leak 1.2.4 Wrong-direction fills
    lines.append("\n## 1.2.4 Wrong-direction fills (mk50 strongly against us)\n")
    wrong_dir_thresh = -5.0  # signed mk50 < -5 means we bought and price dropped ≥5 (or sold and it rose ≥5)
    wrongs = []
    for r in rows:
        mk50 = markout_signed(r, "mid_plus_50")
        if not isnan(mk50) and mk50 <= wrong_dir_thresh:
            wrongs.append((r, mk50))
    lines.append(f"- Fills with mk50 ≤ -5 (price moved ≥5 ticks against us within 50 ticks): **{len(wrongs)}**")
    wrong_pnl = sum(mk * r["size"] for r, mk in wrongs)
    lines.append(f"- Σ mk50·qty on wrong-direction fills: **{wrong_pnl:+.0f}** ({wrong_pnl/n_subs:+.0f}/slice)")
    # Split by side and product
    sub_by = defaultdict(lambda: {"n": 0, "pnl": 0.0, "qty": 0})
    for r, mk in wrongs:
        key = (r["product"], r["side"])
        sub_by[key]["n"] += 1
        sub_by[key]["pnl"] += mk * r["size"]
        sub_by[key]["qty"] += r["size"]
    lines.append("| product | side | n | qty | Σ mk50·qty |")
    lines.append("|---|---|---:|---:|---:|")
    for (prod, side), v in sorted(sub_by.items()):
        lines.append(f"| {prod} | {side} | {v['n']} | {v['qty']} | {v['pnl']:+.0f} |")

    # Leak 1.2.6 Weak crosses (R1 CF3 equivalent)
    lines.append("\n## 1.2.6 OSM weak crosses (R1 CF3 analog)\n")
    osm_wrongs = [(r, markout_signed(r, "mid_plus_50")) for r in rows if r["product"] == "ASH_COATED_OSMIUM" and not isnan(markout_signed(r, "mid_plus_50")) and r["edge_at_fill"] < 0]
    weak = [(r, mk) for r, mk in osm_wrongs if mk <= 5]  # per CF3 definition: weak = markout ≤ +5
    weak_pnl_direct = sum(r["edge_at_fill"] * r["size"] for r, _ in weak)  # direct cross cost
    weak_pnl_fwd = sum(mk * r["size"] for r, mk in weak)  # forward markout
    lines.append(f"- Total OSM negative-edge crosses: {len(osm_wrongs)}")
    lines.append(f"- Of those, mk50 ≤ +5 (weak markout): **{len(weak)}**")
    lines.append(f"- Direct cross cost (Σ edge·qty): **{weak_pnl_direct:+.0f}**")
    lines.append(f"- Forward markout (Σ mk50·qty): **{weak_pnl_fwd:+.0f}**")
    total_weak_leak = weak_pnl_direct + weak_pnl_fwd
    lines.append(f"- Total implied leak (direct + fwd): **{total_weak_leak:+.0f}** ({total_weak_leak/n_subs:+.0f}/slice)")

    # Leak 1.2.7 Fills missed — harder without a counterfactual replay.
    # We can look at per-fill edge distribution vs R1 scaled and flag gaps.
    lines.append("\n## 1.2.7 Fill-density vs R1 scaled (R1 / 10 = expected R2 per slice)\n")
    lines.append("R1 v82 ledger totals (10 k ticks): 610 OSM + 280 PEP = 890 fills. Expected R2 1 k slice: 61 OSM + 28 PEP.")
    by_sub_prod = defaultdict(lambda: {"n": 0, "buy": 0, "sell": 0})
    for r in rows:
        k = (r["sub"], r["product"])
        by_sub_prod[k]["n"] += 1
        if r["side"] == "BUY":
            by_sub_prod[k]["buy"] += 1
        else:
            by_sub_prod[k]["sell"] += 1
    lines.append("| sub | OSM fills | PEP fills | ratio vs R1-scaled |")
    lines.append("|---|---:|---:|---:|")
    for sub in ["296317", "296379", "296878", "297226"]:
        osm_n = by_sub_prod[(sub, "ASH_COATED_OSMIUM")]["n"]
        pep_n = by_sub_prod[(sub, "INTARIAN_PEPPER_ROOT")]["n"]
        lines.append(f"| {sub} | {osm_n} | {pep_n} | {osm_n/61:.2f}× / {pep_n/28:.2f}× |")
    lines.append("")

    # Distance-from-fv distribution vs R1 post-mortem
    lines.append("\n### OSM fill-distance distribution (|price − 10001|)\n")
    lines.append("R1 ledger reference (on 610 OSM fills): 0=9, 1-2=180, 3-5=174, 6-10=241, 11-15=94, 16-20=42.")
    lines.append("R1 scaled to 1 k ticks: 0≈1, 1-2≈18, 3-5≈17, 6-10≈24, 11-15≈9, 16-20≈4.\n")
    osm_rows = [r for r in rows if r["product"] == "ASH_COATED_OSMIUM"]
    dist_buckets = ["0", "1-2", "3-5", "6-10", "11-15", "16-20", ">20"]
    dist_by_sub = defaultdict(lambda: Counter())
    for r in osm_rows:
        d = abs(r["price"] - 10001)
        if d == 0: b = "0"
        elif d <= 2: b = "1-2"
        elif d <= 5: b = "3-5"
        elif d <= 10: b = "6-10"
        elif d <= 15: b = "11-15"
        elif d <= 20: b = "16-20"
        else: b = ">20"
        dist_by_sub[r["sub"]][b] += 1
    lines.append("| sub | " + " | ".join(dist_buckets) + " | total |")
    lines.append("|" + "---|" * (len(dist_buckets) + 2))
    for sub in ["296317", "296379", "296878", "297226"]:
        row = [sub] + [str(dist_by_sub[sub][b]) for b in dist_buckets] + [str(sum(dist_by_sub[sub].values()))]
        lines.append("| " + " | ".join(row) + " |")

    # Realized+unrealized summary
    lines.append("\n## Realized PnL decomposition\n")
    lines.append("| sub | product | realized FIFO | implied unrealized | implied total |")
    lines.append("|---|---|---:|---:|---:|")
    # Read reported PnLs
    reported = {
        ("296317", "ASH_COATED_OSMIUM"): 1877.31,
        ("296317", "INTARIAN_PEPPER_ROOT"): 7349.94,
        ("296379", "ASH_COATED_OSMIUM"): 1928.25,
        ("296379", "INTARIAN_PEPPER_ROOT"): 7678.25,
        ("296878", "ASH_COATED_OSMIUM"): 1750.59,
        ("296878", "INTARIAN_PEPPER_ROOT"): 7720.25,
        ("297226", "ASH_COATED_OSMIUM"): 1563.25,
        ("297226", "INTARIAN_PEPPER_ROOT"): 7741.25,
    }
    for sub in ["296317", "296379", "296878", "297226"]:
        for prod in ["ASH_COATED_OSMIUM", "INTARIAN_PEPPER_ROOT"]:
            realized = sum(r["realized_pnl_fifo"] for r in rows if r["sub"] == sub and r["product"] == prod)
            total = reported[(sub, prod)]
            lines.append(f"| {sub} | {prod} | {realized:+.0f} | {total-realized:+.0f} | {total:+.0f} |")

    DOC.parent.mkdir(parents=True, exist_ok=True)
    DOC.write_text("\n".join(lines) + "\n")
    print(f"\nWrote {DOC}")


if __name__ == "__main__":
    main()
