# Launching the research org

Run each role in its own Claude session with filesystem access. Order
matters for first launch.

## First launch (in order)

1. **Allocator first**, with prompt from `prompts/allocator.md`.
   It will start polling and create initial `allocation/state.md`.

2. **Director second** (you, invoking Claude with `prompts/director.md`).
   First Director run sets initial priorities. You'll need to populate
   `strategic/new_projects.md` with at least one initial project, drawing
   from the Phase 1 scoping recommendation in
   `docs/round2_deep_work_scoping/recommendation.md`.

3. **One Researcher** with `prompts/researcher.md`, with `[PROJECT_NAME]`
   substituted for the project Director funded. Allocator will route
   it through phases.

4. **Skeptic** with `prompts/skeptic.md` once the first Researcher
   approaches Phase C.

5. **Integrator** with `prompts/integrator.md` once Skeptic has approved
   anything.

## Adding researchers later

After the first Researcher is running smoothly, Director can fund
additional projects via `strategic/new_projects.md`. Allocator creates
the directory; you spawn a Researcher session with the appropriate
`[PROJECT_NAME]` substitution.

Maximum recommended concurrent Researchers: 3. More creates Skeptic
queue backup.

## Stopping the system

Touch `research_org/HALT.md` with a non-empty message:

```
echo "Halting for [reason]" > research_org/HALT.md
```

Every agent stops at end of current operation. To resume, empty the
file:

```
> research_org/HALT.md
```

## Daily ritual (you, the human)

Once per day:
1. Read `allocation/eod_report.md`
2. Invoke Director (Claude session with `prompts/director.md`)
3. Director processes escalations and updates priorities
4. Allocator picks up changes within 60 seconds

You spend ~30-60 minutes per day. The rest runs autonomously.

## When to break the protocol (intervene manually)

- `submission_log.md` shows unexpected per-tick crash (regression bug)
- Same escalation appears 3+ times unresolved (Director is failing)
- Skeptic queue exceeds 5 unreviewed items (Skeptic is bottlenecked)
- You have new external information (leaderboard intel, rule clarification) that changes priorities — write directly to `strategic/priorities.md` as if you were Director

Manual intervention is acceptable. The autonomy is a default, not a
constraint.
