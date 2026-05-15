# Skeptic Outbox

**Owner:** Skeptic (append-only).
**Readers:** Allocator (primary).

Verdicts on reviewed specifications. Allocator routes APPROVED to
Integrator, REJECTED/NEEDS_REVISION back to Researcher, NEEDS_DIRECTOR
to `escalations.md`.

Format:

```
Project: [name]
Verdict: APPROVED | REJECTED | NEEDS_REVISION | NEEDS_DIRECTOR
Spec path: [path]
Rationale: <2-4 bullets>
Specific concerns (if not approved): <numbered>
If approved, expected alpha: <range>
If approved, recommended MC gate adjustment: <if any>
```

Detailed review lives at `skeptic/reviews/<project>.md`.

---
