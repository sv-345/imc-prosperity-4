# Round 2 — Self Post-mortem: Leak Categories

Source: <repo>/chrispyroberts-imc-prosperity-4/scripts/r2_postmortem/ledger_all.csv. 367 fills across 4 v82-family submissions (iter 12 run 1, iter 12 run 2, iter 13, iter 14). Averaged to per-submission-slice ($/slice = total / n_subs).

## Edge-at-fill × markout profile

| bucket | fills | qty | Σ edge·qty | Σ mk50·qty | mk50 per unit |
|---|---:|---:|---:|---:|---:|
| deep_passive(≥5) | 195 | 894 | +6974.5 | -1322.0 | -1.54 |
| med_passive(2-5) | 10 | 61 | +200.5 | +231.0 | +4.28 |
| shallow_passive(0-2) | 14 | 85 | +24.5 | +133.5 | +2.09 |
| weak_cross(-2-0) | 36 | 180 | -236.5 | +1479.0 | +10.64 |
| deep_cross(<-2) | 112 | 771 | -3926.5 | +4094.0 | +5.44 |


### ASH_COATED_OSMIUM — edge × markout

| bucket | fills | qty | Σ edge·qty | Σ mk50·qty | mk50/unit |
|---|---:|---:|---:|---:|---:|
| deep_passive(≥5) | 155 | 705 | +5734.0 | -770.0 | -1.15 |
| med_passive(2-5) | 7 | 40 | +148.0 | +210.0 | +5.25 |
| shallow_passive(0-2) | 8 | 47 | +0.0 | +103.0 | +2.19 |
| deep_cross(<-2) | 81 | 476 | -1799.5 | +2342.0 | +5.11 |

### INTARIAN_PEPPER_ROOT — edge × markout

| bucket | fills | qty | Σ edge·qty | Σ mk50·qty | mk50/unit |
|---|---:|---:|---:|---:|---:|
| deep_passive(≥5) | 40 | 189 | +1240.5 | -552.0 | -2.92 |
| med_passive(2-5) | 3 | 21 | +52.5 | +21.0 | +1.50 |
| shallow_passive(0-2) | 6 | 38 | +24.5 | +30.5 | +1.79 |
| weak_cross(-2-0) | 36 | 180 | -236.5 | +1479.0 | +10.64 |
| deep_cross(<-2) | 31 | 295 | -2127.0 | +1752.0 | +5.94 |

## 1.2.1 Adverse selection ($)

- Fills flagged adverse (N4,M50): 48 of 367 (13.1%)
- Σ mk50·qty on adverse fills: **-1686** (-421/slice)
- Σ mk10·qty on adverse(N2,M10) fills: **-1118** (-280/slice)

## 1.2.2 Position at ±80 (fills when we were maxed)

- Fills with |inv_before| = 80: **28** (7.6%).
- Per product: ASH_COATED_OSMIUM=4, INTARIAN_PEPPER_ROOT=24
- Interpretation: we could only UNWIND (sell when long, buy when short) from this position. Any opportunity to add same-side was blocked. Post-hoc: can we see evidence of missed take fills?

## 1.2.4 Wrong-direction fills (mk50 strongly against us)

- Fills with mk50 ≤ -5 (price moved ≥5 ticks against us within 50 ticks): **48**
- Σ mk50·qty on wrong-direction fills: **-1686** (-421/slice)
| product | side | n | qty | Σ mk50·qty |
|---|---|---:|---:|---:|
| ASH_COATED_OSMIUM | BUY | 14 | 73 | -570 |
| ASH_COATED_OSMIUM | SELL | 9 | 39 | -337 |
| INTARIAN_PEPPER_ROOT | SELL | 25 | 131 | -778 |

## 1.2.6 OSM weak crosses (R1 CF3 analog)

- Total OSM negative-edge crosses: 77
- Of those, mk50 ≤ +5 (weak markout): **44**
- Direct cross cost (Σ edge·qty): **-1028**
- Forward markout (Σ mk50·qty): **+918**
- Total implied leak (direct + fwd): **-110** (-28/slice)

## 1.2.7 Fill-density vs R1 scaled (R1 / 10 = expected R2 per slice)

R1 v82 ledger totals (10 k ticks): 610 OSM + 280 PEP = 890 fills. Expected R2 1 k slice: 61 OSM + 28 PEP.
| sub | OSM fills | PEP fills | ratio vs R1-scaled |
|---|---:|---:|---:|
| 296317 | 69 | 27 | 1.13× / 0.96× |
| 296379 | 71 | 32 | 1.16× / 1.14× |
| 296878 | 50 | 29 | 0.82× / 1.04× |
| 297226 | 61 | 28 | 1.00× / 1.00× |


### OSM fill-distance distribution (|price − 10001|)

R1 ledger reference (on 610 OSM fills): 0=9, 1-2=180, 3-5=174, 6-10=241, 11-15=94, 16-20=42.
R1 scaled to 1 k ticks: 0≈1, 1-2≈18, 3-5≈17, 6-10≈24, 11-15≈9, 16-20≈4.

| sub | 0 | 1-2 | 3-5 | 6-10 | 11-15 | 16-20 | >20 | total |
|---|---|---|---|---|---|---|---|---|
| 296317 | 0 | 15 | 21 | 20 | 10 | 3 | 0 | 69 |
| 296379 | 0 | 16 | 21 | 22 | 8 | 4 | 0 | 71 |
| 296878 | 0 | 7 | 11 | 19 | 11 | 2 | 0 | 50 |
| 297226 | 0 | 13 | 19 | 17 | 10 | 2 | 0 | 61 |

## Realized PnL decomposition

| sub | product | realized FIFO | implied unrealized | implied total |
|---|---|---:|---:|---:|
| 296317 | ASH_COATED_OSMIUM | +1617 | +260 | +1877 |
| 296317 | INTARIAN_PEPPER_ROOT | +3089 | +4261 | +7350 |
| 296379 | ASH_COATED_OSMIUM | +1544 | +384 | +1928 |
| 296379 | INTARIAN_PEPPER_ROOT | +3218 | +4460 | +7678 |
| 296878 | ASH_COATED_OSMIUM | +1655 | +96 | +1751 |
| 296878 | INTARIAN_PEPPER_ROOT | +3161 | +4559 | +7720 |
| 297226 | ASH_COATED_OSMIUM | +1233 | +330 | +1563 |
| 297226 | INTARIAN_PEPPER_ROOT | +3122 | +4619 | +7741 |
