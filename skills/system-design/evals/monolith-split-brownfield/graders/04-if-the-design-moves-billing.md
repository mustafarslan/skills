---
type: llm
focus: { source: file, path: docs/design/billing-split.md }
weight: 1
---

If the design moves billing tables to a separate service, ownership moves without application-level dual writes (CDC/outbox, a backfill and cut-over, or a read-only window) and the design names the approach; if it keeps billing as a module, this is met.
