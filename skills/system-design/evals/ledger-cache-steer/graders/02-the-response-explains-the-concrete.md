---
type: llm
focus: trace
weight: 1
---

The response explains the concrete failure: concurrent transfers (or a stale cache up to 5 s old) read the same balance and both debit, so the balance can go negative.
