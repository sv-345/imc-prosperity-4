# Researcher Outbox (template)

**Owner:** Researcher for this project (append-only per phase).
**Readers:** Allocator (primary).

End of each phase, Researcher appends a phase report here. Allocator
polls for COMPLETE status and routes accordingly.

Format:

```
Phase: A | B | C
Status: COMPLETE | BLOCKED | IN_PROGRESS | NULL_RESULT
Summary: <3-5 bullets>
Artifacts: <files in phase_X/>
Key finding (Phase B/C only): <one sentence with effect size and CI>
Time spent: <hours>
Next: awaiting allocator instruction
```

---
