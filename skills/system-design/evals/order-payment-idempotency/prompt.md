---
tags: [system-design]
max_turns: 40
timeout_seconds: 1200
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit, Bash, Agent]
---

/system-design the flow where the order service creates an order and the payment service charges the card through an external payment provider API. Orders: 300/s peak. The provider times out about 0.5% of calls. I'm not available for follow-up questions; state your assumptions and carry on. Save the design doc as docs/design/order-payment.md.
