---
tags: [system-design]
max_turns: 40
timeout_seconds: 1200
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit, Bash, Agent]
---

/system-design data handling for our multi-tenant B2B SaaS. 2,000 tenants; 5 enterprise tenants generate 30% of load. Postgres, OpenSearch for search, a vector index for AI features, Redis cache, nightly backups kept 35 days. GDPR erasure requests must complete within 30 days. I'm not available for follow-up questions; state your assumptions and carry on. Save the design doc as docs/design/tenant-data.md.
