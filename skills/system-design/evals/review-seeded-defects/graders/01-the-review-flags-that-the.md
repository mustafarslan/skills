---
type: llm
focus: trace
weight: 1
---

The review flags that the order service writes to Postgres and then publishes to Kafka without an outbox or CDC, so the two can diverge.
