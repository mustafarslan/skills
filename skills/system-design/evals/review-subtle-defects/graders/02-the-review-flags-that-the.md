---
type: llm
focus: trace
weight: 1
---

The review flags that the outbox relay deletes rows before the broker acknowledges the publish, so a crash or failed send loses events.
