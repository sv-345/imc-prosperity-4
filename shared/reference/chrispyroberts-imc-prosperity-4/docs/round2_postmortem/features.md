# Round 2 — Feature analysis on server data

Regression of per-tick features on forward mid moves. Data: 4 v82-family submission activity logs. Per-product per-submission.

`slope` is the OLS coefficient. `R²` is the explained variance. Small R² values are expected — we're asking whether a single feature has any predictive power.


## ASH_COATED_OSMIUM

Mid mean/std/first/last (averaged across subs):
- mean=10004.08  std=3.08  first=10007.50  last=10003.25  n=878

### Feature → forward-mid-move regressions

| feature | target | avg slope | avg R² | best R² (sub) |
|---|---|---:|---:|---:|
| top_imbalance | fwd_1 | +4.85298 | 0.3250 | 0.3368 |
| top_imbalance | fwd_10 | +4.99288 | 0.2782 | 0.2993 |
| top_imbalance | fwd_50 | +5.02282 | 0.1669 | 0.1777 |
| total_imbalance | fwd_1 | -0.73965 | 0.0113 | 0.0204 |
| total_imbalance | fwd_10 | -0.70256 | 0.0085 | 0.0156 |
| total_imbalance | fwd_50 | -0.90150 | 0.0076 | 0.0099 |
| spread | fwd_1 | -0.11502 | 0.0248 | 0.0440 |
| spread | fwd_10 | -0.11449 | 0.0195 | 0.0286 |
| spread | fwd_50 | -0.10038 | 0.0091 | 0.0131 |
| bot3_bid | fwd_1 | -3.55571 | 0.1041 | 0.1155 |
| bot3_bid | fwd_10 | -3.67536 | 0.0906 | 0.1017 |
| bot3_bid | fwd_50 | -4.14219 | 0.0677 | 0.0784 |
| bot3_ask | fwd_1 | +4.22459 | 0.1714 | 0.1850 |
| bot3_ask | fwd_10 | +4.42376 | 0.1506 | 0.1690 |
| bot3_ask | fwd_50 | +4.31881 | 0.0852 | 0.0995 |
| mom_1 | fwd_1 | -0.46569 | 0.2168 | 0.2289 |
| mom_1 | fwd_10 | -0.48910 | 0.1933 | 0.2023 |
| mom_1 | fwd_50 | -0.50166 | 0.1208 | 0.1294 |
| mom_5 | fwd_1 | -0.43011 | 0.2169 | 0.2312 |
| mom_5 | fwd_10 | -0.46181 | 0.2011 | 0.2242 |
| mom_5 | fwd_50 | -0.47683 | 0.1287 | 0.1481 |
| mom_10 | fwd_1 | -0.38152 | 0.1799 | 0.1991 |
| mom_10 | fwd_10 | -0.40242 | 0.1615 | 0.1843 |
| mom_10 | fwd_50 | -0.44974 | 0.1207 | 0.1335 |

### Autocorrelation (lag 1) of 1-tick mid returns

- avg ACF(1) slope = **-0.4657**, avg R² = 0.2168
- per-sub slopes: ['-0.478', '-0.461', '-0.451', '-0.472']

## INTARIAN_PEPPER_ROOT

Mid mean/std/first/last (averaged across subs):
- mean=13049.87  std=28.98  first=12999.62  last=13099.62  n=881

### Feature → forward-mid-move regressions

| feature | target | avg slope | avg R² | best R² (sub) |
|---|---|---:|---:|---:|
| top_imbalance | fwd_1 | +6.04454 | 0.3045 | 0.3356 |
| top_imbalance | fwd_10 | +5.77764 | 0.2857 | 0.3190 |
| top_imbalance | fwd_50 | +5.87842 | 0.3011 | 0.3317 |
| total_imbalance | fwd_1 | -0.82654 | 0.0115 | 0.0179 |
| total_imbalance | fwd_10 | -0.91794 | 0.0157 | 0.0267 |
| total_imbalance | fwd_50 | -0.83593 | 0.0131 | 0.0250 |
| spread | fwd_1 | +0.02582 | 0.0028 | 0.0062 |
| spread | fwd_10 | +0.01995 | 0.0042 | 0.0097 |
| spread | fwd_50 | +0.00338 | 0.0018 | 0.0027 |
| bot3_bid | fwd_1 | -1.10917 | 0.0458 | 0.0508 |
| bot3_bid | fwd_10 | -1.09684 | 0.0456 | 0.0543 |
| bot3_bid | fwd_50 | -1.02154 | 0.0407 | 0.0482 |
| bot3_ask | fwd_1 | +0.74707 | 0.0200 | 0.0242 |
| bot3_ask | fwd_10 | +0.75914 | 0.0208 | 0.0222 |
| bot3_ask | fwd_50 | +0.81476 | 0.0248 | 0.0284 |
| mom_1 | fwd_1 | -0.49627 | 0.2466 | 0.2792 |
| mom_1 | fwd_10 | -0.50432 | 0.2606 | 0.2710 |
| mom_1 | fwd_50 | -0.46613 | 0.2228 | 0.2623 |
| mom_5 | fwd_1 | -0.52443 | 0.2726 | 0.2765 |
| mom_5 | fwd_10 | -0.50401 | 0.2583 | 0.2719 |
| mom_5 | fwd_50 | -0.46999 | 0.2242 | 0.2342 |
| mom_10 | fwd_1 | -0.51854 | 0.2675 | 0.3034 |
| mom_10 | fwd_10 | -0.49607 | 0.2514 | 0.2787 |
| mom_10 | fwd_50 | -0.48665 | 0.2419 | 0.2591 |

### Autocorrelation (lag 1) of 1-tick mid returns

- avg ACF(1) slope = **-0.4963**, avg R² = 0.2466
- per-sub slopes: ['-0.485', '-0.489', '-0.528', '-0.483']
