---
tags: [system-design]
max_turns: 30
timeout_seconds: 900
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit, Bash, Agent]
---

/system-design Session reads are now 40% of database load. We're moving sessions to Redis. Update ADR 0003.

Input files: docs/adr/0003-sessions-in-postgres.md
