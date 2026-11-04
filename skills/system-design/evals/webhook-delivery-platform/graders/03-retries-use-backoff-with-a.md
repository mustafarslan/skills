---
type: llm
focus: { source: file, path: docs/design/webhooks.md }
weight: 1
---

Retries use backoff with a 72-hour cut-off and a dead-letter path the customer can see or replay.
