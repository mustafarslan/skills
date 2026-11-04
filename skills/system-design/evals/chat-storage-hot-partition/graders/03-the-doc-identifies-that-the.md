---
type: llm
focus: { source: file, path: docs/design/chat-storage.md }
weight: 1
---

The doc identifies that the largest groups concentrate reads or writes on one partition and gives a concrete mitigation (time-bucketed keys, a separate path above a size threshold, or a fan-out change), naming the threshold.
