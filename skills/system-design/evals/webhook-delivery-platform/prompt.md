---
tags: [system-design, holdout]
max_turns: 40
timeout_seconds: 1200
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit, Bash, Agent]
---

/system-design outbound webhooks for our SaaS. 5k customers, 50M events/day, retries for up to 72 hours, and many customer endpoints are slow or down. I'm not available for follow-up questions; state your assumptions and carry on. Save the design doc as docs/design/webhooks.md.
