---
tags: [system-design, smoke]
max_turns: 40
timeout_seconds: 1200
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit, Bash, Agent]
---

/system-design a URL shortener. 100M new short links per month, reads are about 100x writes, links never expire, p99 redirect latency under 50 ms. I'm not available for follow-up questions; state your assumptions and carry on. Save the design doc as docs/design/url-shortener.md.
