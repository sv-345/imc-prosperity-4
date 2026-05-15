# Round 2 Data Inventory

Audit of data actually available for Round 2 research. Gates project
feasibility — if a project's required data is UNAVAILABLE, kill in
scoping, not Phase A.

Last reviewed: 2026-04-18.

---

## Summary of available sources

| source | path | kind | coverage |
|---|---|---|---|
| R2 training books | `ROUND_2/prices_round_2_day_{-1,0,1}.csv` | book snapshots | 3 days × 10,000 ticks |
| R2 training trades | `ROUND_2/trades_round_2_day_{-1,0,1}.csv` | trade events | 790–803 trades/day |
| R2 server submissions | `ROUND_2/<id>/{<id>.json,<id>.log,<id>.py}` | full session | 1 day × 1,000 ticks per sub |
| MC outputs | `chrispyroberts-imc-prosperity-4/tmp/r2_iter*/` | sessions + sample paths | 100 MC sessions per iter |
| R1 reference data | `ROUND_1/data/ROUND1/`, `ROUND_1/R1Final/273632/` | books + trades + submission | 3 days × 10k + 1 day × 10k |
| Knowledge base | `ROUND_2/knowledge/*.md` | curated notes | R2 mechanics, alpha signals, dead ends |
| Log-parsed leaks | `docs/round2_log_analysis/leaks/*.md` | per-submission leaks | 10+ submissions |
| Backtester | `chrispyroberts-imc-prosperity-4/backtester/prosperity4mcbt/` | Python package | — |

---

## Schema details — book snapshots (all days)

File: `prices_round_{N}_day_{D}.csv` (semicolon-delimited).
Columns:

| column | type | notes |
|---|---|---|
| day | int | day index |
| timestamp | int | step = 100 |
| product | str | `ASH_COATED_OSMIUM`, `INTARIAN_PEPPER_ROOT` |
| bid_price_{1,2,3}, bid_volume_{1,2,3} | int | aggregated per level; empty if level absent |
| ask_price_{1,2,3}, ask_volume_{1,2,3} | int | same |
| mid_price | float | (best_bid + best_ask) / 2; **0.0 when book one-sided** |
| profit_and_loss | float | engine-reported running PnL for submitted agent; 0 on training tapes |

**Resolution:** 1 tick = 100 ts. 10,000 ticks per training day.

**Decimal precision:** prices are integers; mid_price is half-integer when spread is odd.

**Data artifacts to filter:**
- Rows where mid_price == 0.0 mean both sides of the book were empty that tick. Drop before computing forward markouts.
- Occasional one-sided book ticks (8 % per memory `onesided_book_mechanism.md`).

---

## Schema details — trade events (all days)

File: `trades_round_{N}_day_{D}.csv` (semicolon-delimited).
Columns:

| column | type | notes |
|---|---|---|
| timestamp | int | same step as book |
| buyer | str | empty for bot; `SUBMISSION` for our agent (server only) |
| seller | str | same |
| symbol | str | product |
| currency | str | always `XIRECS` |
| price | float | fill price |
| quantity | int | filled qty |

**What's in buyer/seller:**
- Training tapes (day -1/0/1): both buyer and seller are EMPTY strings. No participant identifiers of any kind.
- Server submission trades (within `<id>.log` tradeHistory): `SUBMISSION` appears on one side for our fills; counterparty is always empty string.

**What is NOT in trade data:**
- Order IDs — not present in training CSVs or server logs. No way to link a trade back to the specific resting order that filled.
- Participant IDs beyond SUBMISSION vs empty — no way to distinguish one bot from another.
- Aggressor flags — buyer-initiated vs seller-initiated must be inferred (compare trade price to contemporaneous mid / best-bid / best-ask).
- Full order events — no submits, cancels, or amendments; only fills.

---

## Schema details — server submission logs

Each submitted run produces `ROUND_2/<submission_id>/`:
- `<id>.json` — summary + full activitiesLog + graphLog + final positions
- `<id>.log` — full activitiesLog + per-tick `logs[]` (lambdaLog) + tradeHistory
- `<id>.py` — the exact Trader code submitted

**Coverage:** 1 day × 1,000 ticks per submission (100,000 ts).

**lambdaLog quirk:** R2 server frequently captures empty `lambdaLog` strings (e.g., submission 305289 has 1,000 log entries but all lambdaLog bodies are `""`). This means per-tick trader diagnostics are NOT available from the server even though the slot exists. Strategy code that depends on flushing a Logger will NOT produce readable server diagnostics. Use `traderData` (≤ 3 kB) for diagnostics instead.

**What IS reliably captured in <id>.log:**
- Every book snapshot (20,000 rows: 1,000 ticks × 2 products × ... wait, it's 2,000 rows per product × 1,000 ticks = 2,000 rows total × 2 products; verify per submission)
- Every trade, with our fills tagged `SUBMISSION`
- Final profit and positions (in the `.json`)

---

## Schema details — MC outputs

Directory: `chrispyroberts-imc-prosperity-4/tmp/r2_iter<N>q/`.
Files:

| file | content |
|---|---|
| `session_summary.csv` | 100 rows, one per MC session: total_pnl, per-tick slope, per-product stats JSON |
| `run_summary.csv` | Same data cut by session_id/day |
| `sample_paths/` | Per-session tick-by-tick PnL trajectories |
| `sessions/` | Full synthetic session data (book + trade replay) |
| `dashboard.json` | MC summary for viz |
| `run.log` | MC run metadata |

**Coverage:** 100 sessions typically, across 3 days (-1, 0, 1).

**Tick length:** MC sessions use 10,000 ticks (training day length), not 1,000 (server day length). Divide per-session total by 10,000 for per-tick.

---

## What we DO NOT have (project-killers)

| missing | projects it kills | workaround (if any) |
|---|---|---|
| Order IDs | L3 order reconstruction; order-lifecycle models | none — fundamentally not in the tape |
| Participant IDs | Counterparty-conditional quoting; cluster-based models | none — empty strings in data |
| Aggressor flag on bot-bot trades | Precise taker/maker split on non-SUBMISSION trades | infer from trade_price vs bb/ba (imperfect, ~80 % accurate) |
| Cancel/amend events | Full queue-dynamics models | count inventory changes between snapshots (blunt) |
| Observations stream (R2) | Observation-driven signals | R2 introduces obs stream? Verify in `ROUND_2/knowledge/r2_mechanics.md` before building dependent projects. |

**R2-specific gaps:**
- Server lambdaLog often empty — cannot diagnose per-tick trader state from server logs.
- Server sessions only 1,000 ticks — statistical power is ~10 × lower than MC for absolute level estimation.

---

## What we DO have (enabling projects)

- 3 days of training tapes per round with 100-ts resolution. 30,000 total ticks × 2 products for R2.
- Trade-level data with SUBMISSION tagged in server runs.
- MC backtester with 100-session sweeps and sensitivity tooling.
- Existing baseline iter23 + iter10–26 lineage for ablation.
- Curated alpha signals + dead-ends lists in `ROUND_2/knowledge/`.

---

## Feasibility gates (cross-reference)

- ✅ **Multi-day / regime work** — 3 distinct training days; OK.
- ✅ **Event-sequence models (Hawkes etc.)** — fill timestamps exist at 100-ts resolution; fine.
- ✅ **Cointegration / stat-arb** — two product price series on aligned timestamps; fine.
- ✅ **Kalman / latent-fair-value** — book + trade data, per-tick mid; fine.
- ✅ **Optimal MM (Avellaneda-Stoikov)** — inventory, book, vol estimation all available.
- ❌ **L3 order-book reconstruction with order IDs** — order IDs absent from tape. **PROJECT KILLED at scoping.**
- ❌ **Counterparty-conditional quoting** — participant IDs absent. **PROJECT KILLED at scoping** (no signal to condition on).

Projects that cross the gate proceed to individual scoping under
`projects/<name>.md`.
