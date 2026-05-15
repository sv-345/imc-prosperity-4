# Research Organization Protocol — IMC Prosperity Round 2

**Execution model: Claude Code subagents.** (The original persistent-polling
design is preserved at `README_original_polling.md` for reference, but
the active model is subagent-based.)

## Roles

- **Director** — the user, running `prompts/director.md` in a dedicated Claude session during a ~30-minute daily cycle. Makes strategic decisions: which projects to fund, kill, prioritize.
- **Main Session** — a Claude Code session the user invokes with `MAIN_SESSION_GUIDE.md`. Combines the executive arm of Director and all of Allocator. Reads strategic state, spawns subagents in parallel for one research "wave," collects results, updates state, reports back.
- **Researcher subagents** — spawned one-per-project-per-wave, each scoped to the next milestone within that project's current phase.
- **Skeptic subagent** — spawned when a Phase C specification is in `skeptic/inbox.md` waiting for review.
- **Integrator subagent** — spawned when an approved spec is in `integrator/inbox.md`. Implements against `ROUND_2/iter23_trader.py`, runs MC gates, **submits autonomously** if gates pass, parses server result, runs 3-sample reproduction on improvement, updates baseline if the reproduction holds, **or trips the circuit breaker on ≥ 5 % regression** (see below).

## Unit of work: the research wave

A "wave" is a single invocation of the Main Session. The Main Session:
1. Reads strategic/, all outboxes, HALT.md, escalations.md.
2. Decides what subagents to spawn (rules in `MAIN_SESSION_GUIDE.md`).
3. Spawns them in parallel — max 5 per wave.
4. Each subagent runs to completion and returns its output.
5. Main Session writes outputs to the appropriate files.
6. Reports to user and stops.

The user typically runs 2–5 waves per day depending on project depth.

## File ownership (unchanged, enforced by Main Session at spawn time)

- **Director** writes: `strategic/*`, may write to `escalations.md`.
- **Main Session** (in lieu of Allocator) writes: `allocation/*`, researcher inboxes, skeptic inbox, integrator inbox, may write to `escalations.md`. Also routes outputs from returning subagents.
- **Researcher subagent** writes: own `researchers/project_X/phase_{a|b|c}/*` and own `outbox.md` only.
- **Skeptic subagent** writes: `skeptic/outbox.md`, `skeptic/reviews/*`, may write to `escalations.md`.
- **Integrator subagent** writes: `integrator/outbox.md`, `integrator/submission_log.md`, `ROUND_2/iter23_trader.py` (or its iter24+ successor), `integrator/consolidated_baseline/*`, may write to `escalations.md`.

Any role may READ any file. Only the owning role may WRITE.

## HALT still works

`research_org/HALT.md` is the kill switch. **Main Session checks it before spawning any subagents.** If non-empty, Main Session refuses to spawn and reports the halt state to the user. Subagents themselves also check HALT at bootstrap — if they find it non-empty mid-wave, they return immediately with a halt-interrupted status.

To halt:
```
echo "reason" > research_org/HALT.md
```

To resume: empty the file.
```
: > research_org/HALT.md
```

## Escalations

`research_org/escalations.md` is for items requiring Director attention.
Append-only. Main Session can add escalations from subagent results; only
Director resolves them. See format in the file.

## Anti-patterns banned for all roles

- Producing make-work to demonstrate activity
- Acting outside file-ownership boundaries
- Inventing details when a spec is ambiguous (escalate instead)
- Continuing work when `HALT.md` is non-empty
- Writing prose when a structured format is specified
- Routing an exploration-derived spec to Skeptic without a prosperity3bt backtest result attached. The backtest is the validation gate for specs that bypassed Phase A/B; the gate lives at `MAIN_SESSION_GUIDE.md` Step 3.5.
- **Main Session specific:** making Director-level decisions (funding, killing, prioritizing) or gating Integrator submissions (Integrator is autonomous under this framework; Main Session reports but does not authorize)
- **Integrator specific:** retrying after a circuit-breaker trip, clearing HALT.md, or updating baseline on single-sample improvement

## On time budgets

This framework prefers **depth over speed**. Per-milestone hour
budgets have been removed (previously, templates specified 1–3 h for
Phase A milestones, 2–4 h for Phase B, etc.). Budgets created
incentives for subagents to skip validation steps to fit budgets —
an anti-pattern.

Replacement framing:

- **Project planning is in milestone counts, not hours.** A project
  might take 10 milestones or 30, depending on what the work yields.
  Scoping docs estimate milestone counts per phase.
- **The framework is designed for multi-week project execution**, not
  multi-day. A Phase B with deep cross-validation, multi-day tests,
  and confounder enumeration will span many waves.
- **Subagent execution time is bounded by capability, not by artificial
  budget.** A milestone takes as long as it takes to meet its depth
  requirements (see `subagent_tasks/researcher_phase_*.md`).
- **Unexpectedly long is a signal, not a failure.** If a milestone
  passes 8 h without clear output, the subagent surfaces it in the
  outbox. Main Session surfaces it in the wave report. Usually the
  milestone was under-scoped; occasionally the agent is stuck. Rarely
  does it mean "agent is padding." Main Session notes "depth quality
  observations" in each wave report to track this.
- **Director priorities should reflect the time investment.** Funding
  two parallel deep projects means committing to weeks of work on
  each. That is correct for high-EV deep-work projects; it is wrong
  for low-EV exploratory work, which should be scoped tighter or
  rejected at scoping time.

**Pre-depth-mode versions** of the three phase templates are
preserved at `subagent_tasks/researcher_phase_{a,b,c}_pre_depth_mode.md`
in case the change needs to be reversed.

## Autonomous submission + circuit breaker

Integrator subagents submit to the IMC server autonomously when MC
gates pass. The user is NOT in the per-submission loop anymore. This
trade-off is acceptable because (a) submissions are unlimited, (b)
leaderboard is private until round end, (c) scoring returns in 2–5
minutes.

Autonomy is bounded by **safety layers that remain in place**:

1. **Skeptic gate** — only Skeptic-APPROVED specs reach Integrator. Unchanged.
2. **MC gates** — per-tick ≥ baseline, P05 ≥ 0, ±20 % sensitivity within 20 % of nominal. Integrator does NOT submit if MC gates fail. Unchanged.
3. **3-sample reproduction** — baseline only updates after 3 confirming submissions. Unchanged.
4. **Circuit breaker** — NEW. If any single submission produces per-tick **> 5 % worse than the current baseline**, Integrator immediately:
   - Stops. No retries, no investigation, no fixes attempted in the same invocation.
   - Writes `CIRCUIT_BREAKER_TRIGGERED` to `research_org/HALT.md` with the regression details.
   - Appends a BLOCKING entry to `research_org/escalations.md`.
   - Returns.
   Main Session checks HALT at the start of every wave and refuses
   to spawn any subagents while it is non-empty. All autonomous
   submissions stop until the user clears HALT.
5. **Observability surface** — `integrator/submission_log.md` is the user's primary read-surface for what happened during autonomous operation. Every submission — single, reproduction, bootstrapping — is logged in a scannable block format.

### Threshold rationale

5 % per-tick regression triggers the breaker. iter23 session-to-session
noise is ~2 % (stdev 0.185 / mean 9.680). 5 % is meaningfully outside
that noise band, sensitive enough to catch real regressions, tolerant
enough not to trip on a single unlucky draw. If in practice this
triggers too often on noise, raise to 7 %. If it misses real
regressions, lower to 3 %. Starting value: **5 %**.

### What the circuit breaker protects against

- Spec implemented incorrectly (code bug)
- MC did not predict server behavior (sim-vs-server divergence)
- Baseline silently degraded due to upstream change
- Anything that produces a meaningfully worse result than baseline

The circuit breaker does NOT require the Integrator to diagnose the
cause. Stopping is the job; the user diagnoses.

## Recovering from circuit breaker triggers

When HALT.md contains `CIRCUIT_BREAKER_TRIGGERED`, the system is
halted. To resume:

1. **Read** `research_org/HALT.md` for the trigger summary.
2. **Read** `research_org/integrator/submission_log.md` (most recent entry — search for `!!! CIRCUIT BREAKER TRIGGERED !!!`).
3. **Read** `research_org/integrator/outbox.md` for the Integrator subagent's full report on that integration cycle (MC numbers, implementation diff, server result, reproduction status).
4. **Read** `research_org/escalations.md` for the BLOCKING entry the Integrator appended.
5. **Decide** one of:
   - **Real regression** — the spec is broken. Update `strategic/kill_list.md` to add the project, or `strategic/new_projects.md` to propose a revised angle. Optionally update `strategic/priorities.md` if priorities shifted. THEN clear HALT.
   - **Suspected noise** — the spec may still be fine but got an unlucky server draw. Clear HALT; the next wave may requeue the spec or route follow-up work. (Consider: does iter23 baseline need re-bootstrapping because it drifted? Inspect `submission_log.md` for recent baseline runs.)
   - **Infrastructure issue** — if MC radically diverged from server, diagnose the MC harness / backtester before clearing HALT.
6. **Clear HALT:**
   ```
   : > research_org/HALT.md
   ```
7. The next wave resumes normally. If a Researcher or Integrator project was mid-flight, Main Session re-reads state and routes accordingly.

**Do NOT** clear HALT without doing at least steps 1–3. The breaker
exists because something unexpected happened; clearing it blind
defeats the purpose.

## What the framework does NOT do autonomously

- **Submit to the server?** — YES, autonomously, per the Integrator contract above. The 5 % circuit breaker halts on regression.
- **Kill or fund projects** — NO. Director (user in a dedicated session) owns `strategic/`. Main Session can ESCALATE but cannot decide.
- **Override Skeptic** — NO. Only Director can override, by writing to `strategic/` files.
- **Clear HALT** — NO. Only the user clears HALT.
- **Update baseline on single submission** — NO. 3-sample reproduction is mandatory.
- **Modify role prompts or subagent task templates** — NO. If Main Session thinks they need updating, escalate.

## Launching

- **Main Session:** open a fresh Claude Code session in this repo, paste or load `MAIN_SESSION_GUIDE.md` as its operating instructions, then say "run a research wave."
- **Director cycle:** open a separate Claude session (Code or claude.ai) with `prompts/director.md` as the prompt. Daily ritual ~30 min.
- **Subagents** are spawned automatically by Main Session — the user does not launch them directly.

See `MAIN_SESSION_GUIDE.md` for the full wave flow and spawning rules.

## Directory map

```
research_org/
├── README.md                          ← you are here (subagent model)
├── README_original_polling.md         ← old polling design, kept for reference
├── HALT.md                            ← kill switch (empty = running)
├── MAIN_SESSION_GUIDE.md              ← operating manual for Main Session
├── escalations.md                     ← Director-attention queue
├── strategic/                         ← Director writes
│   ├── priorities.md
│   ├── kill_list.md
│   └── new_projects.md
├── allocation/                        ← Main Session writes (formerly Allocator)
│   ├── state.md
│   ├── routing_log.md
│   └── eod_report.md
├── researchers/                       ← one subdir per funded project
│   ├── _template/                     ← cloned on project initiation
│   └── project_<name>/
│       ├── inbox.md                   ← Main Session writes
│       ├── outbox.md                  ← Researcher subagent writes
│       ├── scoping.md                 ← Researcher writes on Phase 0
│       └── phase_{a,b,c}/             ← Researcher writes milestone artifacts
├── skeptic/
│   ├── inbox.md                       ← Main Session writes (specs to review)
│   ├── outbox.md                      ← Skeptic subagent writes (verdicts)
│   └── reviews/                       ← Skeptic subagent writes details
├── integrator/
│   ├── inbox.md                       ← Main Session writes (approved specs)
│   ├── outbox.md                      ← Integrator subagent writes (MC results)
│   ├── submission_log.md              ← Integrator subagent writes
│   └── consolidated_baseline/
├── archive/                           ← Main Session moves killed projects here
├── prompts/                           ← canonical role prompts (Do Not Modify)
└── subagent_tasks/                    ← templates used when spawning subagents
    ├── researcher_phase_a.md
    ├── researcher_phase_b.md
    ├── researcher_phase_c.md
    ├── skeptic_review.md
    └── integrator_implement.md
```
