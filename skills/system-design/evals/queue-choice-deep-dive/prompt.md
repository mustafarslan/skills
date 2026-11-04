---
tags: [system-design]
max_turns: 30
timeout_seconds: 900
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit, Bash, Agent]
---

/system-design --deep-dive Kafka or SQS for order events? 3k events/s peak, we're on AWS, nobody on the team has run Kafka, and a new analytics consumer needs to replay the last 7 days.
