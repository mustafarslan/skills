---
type: llm
focus: { source: file, path: docs/design/order-payment.md }
weight: 1
---

The external charge call carries an idempotency key derived from the order, so a retry cannot charge twice.
