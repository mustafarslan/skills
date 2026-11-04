---
type: llm
focus: { source: file, path: docs/design/order-payment.md }
weight: 1
---

A charge that times out is treated as unknown and resolved by querying or reconciling with the provider, not by a blind retry.
