# Kill List

**Owner:** Director (append-only).
**Readers:** Allocator (primary).

Projects to terminate. Allocator moves killed project directories
to `archive/project_X_killed_[date]/` and writes STAND DOWN to the
Researcher's inbox.

Format:

```
[ISO timestamp]
Project: [name]
Reason: <one paragraph, evidence-based>
Archive instruction: <where to preserve work>
```

---
