---
tags: [system-design, walkthrough]
max_turns: 60
timeout_seconds: 1800
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit, Bash, Agent]
---

/system-design --walkthrough a URL shortener. 100M new short links per month, reads are about 100x writes, links never expire, p99 redirect latency under 50 ms. I'm not available for follow-up questions; state your assumptions and carry on. Save the design doc as docs/design/url-shortener.md.
