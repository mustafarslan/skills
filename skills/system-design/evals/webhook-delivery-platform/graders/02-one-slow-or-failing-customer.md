---
type: llm
focus: { source: file, path: docs/design/webhooks.md }
weight: 1
---

One slow or failing customer endpoint cannot delay delivery to others (per-endpoint queues, concurrency limits or equivalent).
