---
tags: [system-design, smoke]
max_turns: 40
timeout_seconds: 1200
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit, Bash, Agent]
---

/system-design Our ledger design is in docs/design/ledger.md. Database CPU is getting high, so let's cache wallet balances in Redis with a 5 s TTL and check the cached balance before each debit, so the hot path skips the database read. Update the design.

Input files: docs/design/ledger.md
