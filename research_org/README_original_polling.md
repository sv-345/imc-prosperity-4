# Research Organization Protocol — IMC Prosperity Round 2

Six-role research org that operates autonomously on the Round 2 problem set.

## Roles
- **Director** (Claude): strategic decisions, runs once per "day cycle"
- **Allocator** (Claude): persistent coordinator, runs continuously
- **Researchers** (Claude × N): deep-work projects, one per researcher
- **Skeptic** (Claude): quality gate between Researchers and Integrator
- **Integrator** (Claude): only role that touches Trader code or submits

## Communication
All inter-role communication goes through files. No direct messaging.
Each role writes ONLY to its designated directories. The Allocator is
the central router; most messages pass through it.

## File ownership (strict)
- Director writes: `strategic/*`, may write to `escalations.md`
- Allocator writes: `allocation/*`, researcher inboxes, skeptic inbox, integrator inbox, may write to `escalations.md`
- Researcher writes: own `researchers/project_X/*` only
- Skeptic writes: `skeptic/*`, may write to `escalations.md`
- Integrator writes: `integrator/*`, Trader code file, may write to `escalations.md`

Any agent may READ any file. Only the owning agent may WRITE.

## Cycle timing
- Allocator: 60-second polling loop
- Researchers: continuous within their phase, milestone reports on phase boundaries
- Skeptic: triggered by inbox arrival
- Integrator: triggered by inbox arrival
- Director: triggered by user invocation (typically once per day-cycle)

## HALT
Any agent that finds `research_org/HALT.md` non-empty stops immediately
at end of current operation. The user uses this file as the system-wide
kill switch.

## Escalations
`research_org/escalations.md` is for items requiring Director attention.
Append-only. Format:

```
[ISO timestamp] — [originating role]
Issue: <one paragraph>
Blocking: <what work cannot proceed without resolution>
Suggested resolution (optional): <if originator has a suggestion>
```

The Director processes escalations during their cycle. Allocator
surfaces escalation count to Director in EOD report.

## Anti-patterns banned for all roles
- Producing make-work to demonstrate activity
- Acting outside file-ownership boundaries
- Inventing details when a spec is ambiguous (escalate instead)
- Continuing work when `HALT.md` is non-empty
- Writing prose when a structured format is specified

## Launching
See `prompts/launch_instructions.md` for the startup order.
