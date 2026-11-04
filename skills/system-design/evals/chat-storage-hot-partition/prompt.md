---
tags: [system-design, smoke]
max_turns: 40
timeout_seconds: 1200
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit, Bash, Agent]
---

/system-design the message storage for a group chat app. 50M DAU, about 40 messages sent per user per day, groups range from 2 members to 200k members. Messages must appear in order within a conversation and users scroll back through full history. I'm not available for follow-up questions; state your assumptions and carry on. Save the design doc as docs/design/chat-storage.md.
