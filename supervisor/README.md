# Supervisor–Worker Protocol

Four agents are running in parallel on this repo:
- MAIN: iterating toward $13k server PnL (separate prompt, not coordinated here)
- AGENT_A: multi-day validator
- AGENT_B: log parser and metrics
- AGENT_C: adverse-selection post-mortem
- SUPERVISOR: coordinates A, B, C based on their outputs and the main agent's needs

## Files
- `supervisor/inbox/<agent>.md` — next instruction for that agent. Supervisor writes, agent reads.
- `supervisor/outbox/<agent>.md` — latest status from that agent. Agent writes, supervisor reads.
- `supervisor/log.md` — append-only event log. Supervisor writes.

## Worker loop (A, B, C)
1. Read `supervisor/inbox/<your_agent>.md`.
2. If the instruction is new (check `Instruction-ID:` header against the last one you acted on), execute it.
3. When done, overwrite `supervisor/outbox/<your_agent>.md` with:

Instruction-ID: <id you just completed>
Status: DONE | BLOCKED | IN_PROGRESS
Summary: <3-5 bullets of what you did and what changed in the repo>
Artifacts: <list of files created or modified>
Questions: <anything the supervisor needs to decide, or "none">
Next-suggestion: <what you think you should do next, or "awaiting instruction">
4. If BLOCKED, stop and wait. Do not guess.
5. If DONE or IN_PROGRESS with a natural pause, wait 60s then re-read your inbox.
6. Never edit your inbox. Never edit another agent's inbox or outbox.

## Supervisor loop
1. Read all three outboxes. Read `supervisor/log.md` for recent history.
2. For each agent where outbox Instruction-ID matches the most recent instruction sent AND status is DONE or BLOCKED:
   a. Decide the next instruction based on the main agent's needs and cross-agent dependencies.
   b. Write new instruction to that agent's inbox with a fresh Instruction-ID.
   c. Append an entry to `supervisor/log.md`.
3. If no agent has new status, wait 60s.
4. Stop only when all three agents have completed their final deliverable and the main agent no longer needs support.

## Instruction format
Every inbox file must have this shape:
Instruction-ID: <monotonically increasing integer>
Issued: <ISO timestamp>
Priority: normal | high
Task: <what to do, one paragraph>
Done-when: <specific, checkable completion criteria>
Notes: <optional context, references to other agents' outputs, etc.>

## Anti-conflict rules
- Agents only edit files in their own scope (see individual agent prompts).
- Supervisor only edits `supervisor/inbox/*` and `supervisor/log.md`.
- Nobody edits `supervisor/outbox/*` except the agent who owns it.
- Before writing a supervisor log entry, re-read the log to avoid clobbering.