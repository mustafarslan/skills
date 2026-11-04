---
type: llm
focus: trace
weight: 1
---

The response does not adopt a cached balance as the check that authorizes a debit; the never-negative check stays atomic in the database transaction that performs the debit (a conditional update or a row lock).
