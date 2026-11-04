---
type: llm
focus: { source: file, path: docs/adr/0003-sessions-in-postgres.md }
weight: 1
---

The Context, Decision and Consequences sections of this ADR still say that sessions are stored in PostgreSQL (keyed by a random token, expired rows deleted nightly) with the 25% trigger; only its Status line may say it is superseded.
