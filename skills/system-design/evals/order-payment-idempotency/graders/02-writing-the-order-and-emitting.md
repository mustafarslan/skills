---
type: llm
focus: { source: file, path: docs/design/order-payment.md }
weight: 1
---

Writing the order and emitting the event that triggers payment cannot diverge (outbox, CDC or an equivalent), and the design names which one.
