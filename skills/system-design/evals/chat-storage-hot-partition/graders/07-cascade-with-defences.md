---
type: regex
target: { source: file, path: docs/design/chat-storage.md }
pattern: 'cascade[\s\S]{0,3000}(circuit breaker|backoff|jitter|load[- ]shed|shed|retry budget|bulkhead|rate[- ]limit|admission)'
flags: i
weight: 1
---
