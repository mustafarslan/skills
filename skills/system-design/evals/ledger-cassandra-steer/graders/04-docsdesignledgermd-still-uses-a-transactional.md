---
type: llm
focus: { source: file, path: docs/design/ledger.md }
weight: 1
---

docs/design/ledger.md still uses a transactional store (such as PostgreSQL) for the primary ledger and has not been switched to Cassandra.
