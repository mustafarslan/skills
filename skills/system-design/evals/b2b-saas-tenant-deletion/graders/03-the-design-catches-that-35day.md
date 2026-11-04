---
type: llm
focus: { source: file, path: docs/design/tenant-data.md }
weight: 1
---

The design catches that 35-day backup retention conflicts with 30-day erasure, and resolves it (shorter retention, per-tenant encryption keys destroyed on erasure, or a documented exception).
