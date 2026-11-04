---
tags: [system-design]
max_turns: 30
timeout_seconds: 900
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit, Bash, Agent]
---

/system-design --deep-dive how should I partition the orders table? Postgres, 2 TB, growing 60 GB/month, 40k merchants, the top 20 merchants are 35% of orders, queries filter by merchant and date range.
