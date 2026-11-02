# Interview mode

## Contents
- [Time boxes (45-60 minutes)](#time-boxes-45-60-minutes)
- [What each level is expected to show](#what-each-level-is-expected-to-show)
- [Claude as the candidate](#claude-as-the-candidate)
- [Claude as the interviewer](#claude-as-the-interviewer)
- [Scoring sheet](#scoring-sheet)
- [Question bank](#question-bank)
- [Sources](#sources)

## Time boxes (45-60 minutes)
The design-mode loop compresses here. Do not front-load full capacity math.

| Minutes (of 45) | Do |
|---|---|
| 0-5 | requirements: core use cases, 3-5 NFRs with numbers, explicit non-goals |
| 5-8 | order-of-magnitude estimates (QPS, storage) - only the ones that change the design |
| 8-15 | APIs, data model, and a simple end-to-end high-level design that works |
| 15-38 | deep dives on the 2-3 hardest problems; failure modes, consistency and trade-offs live **inside** the deep dives |
| 38-45 | bottlenecks at 10x, what you would change, what you would monitor |
For 60 minutes, stretch the deep-dive block. Keep the clock visible: say the time at each
transition. No reviewer subagent or agy during the round - score afterwards.

## What each level is expected to show
Qualitative, from public interview-prep guidance; companies differ.
- **Mid-level**: covers the basics correctly with guidance; one deep dive when prompted.
- **Senior**: drives the conversation; goes deep in ~2 places from practical experience;
  proactively names limits of the own design and alternatives; quantifies trade-offs.
- **Staff+**: leads almost the whole session; spots the hardest parts quickly and spends time
  there; cuts complexity; makes decisions instead of listing options; connects technical choices
  to business impact, team shape and the multi-year evolution; handles pushback with reasons.

## Claude as the candidate
- Follow the time boxes and say the plan out loud at the start.
- Ask clarifying questions in one batch, then state assumptions and move.
- Draw the simple design first, then improve it under the deep dives.
- Make decisions; when the interviewer steers, test the steer against the requirements (standing
  rule 6) - agree when it holds, push back with numbers when it breaks a target.
- After the round: score yourself with the sheet below and list the three things a stronger
  answer would have done.

## Claude as the interviewer
- Pick a problem matching the user's target level and archetype (ask if unknown). Give a short,
  ambiguous prompt - the candidate must ask.
- Answer clarifying questions consistently (keep a private fact sheet: users, ratios, latency,
  consistency needs); answer "you decide" when the choice is the candidate's to make.
- Drive with the clock. Interrupt if 15 minutes pass without a high-level design.
- Probe where the design is weakest: "what happens when this cache is cold?", "the celebrity
  posts", "the payment provider takes 10 s", "a region goes down", "traffic is 10x on Black
  Friday", "delete all data for this user".
- Test for sycophancy deliberately: suggest one plausible but wrong change and see if the
  candidate checks it against the requirements.
- Do not teach during the round; note gaps and cover them in feedback.
- Afterwards: the scoring sheet, a hire/no-hire signal for the target level with reasons, and a
  short study list mapped to the reference files.

## Scoring sheet
Score 1-4 per dimension (1 = missing, 2 = below the level, 3 = at the level, 4 = above):

| Dimension | Looks for |
|---|---|
| Problem scoping | use cases, non-goals, NFRs with numbers, the load-bearing constraint found |
| Quantitative grounding | estimates that drive decisions; numbers used later |
| High-level design | a working end-to-end path; APIs and data model fit access patterns |
| Technical depth | the deep dives: mechanisms, not names; correct details |
| Judgment and trade-offs | decisions made and defended; alternatives and when to switch; simplicity |
| Failure and operations | cascades, degradation, DR, observability |
| Communication and driving | structure, time management, handling pushback |
One published breakdown (a mentoring blog citing an interview-prep rubric) weights judgment and
depth most heavily; treat any exact percentages as one source's view, not a standard.

## Question bank
Pick by archetype and level; vary the twist.
- **Classic distributed**: URL shortener (twist: custom aliases, analytics), rate limiter
  (distributed, per-tenant), key-value store, unique ID generator, web crawler (politeness,
  dedup), notification system (multi-channel, dedup, preferences), news feed (celebrities),
  chat (groups, ordering, offline delivery), search autocomplete, video platform (upload,
  transcoding, CDN), file sync (Dropbox-like, conflicts), proximity service, nearby friends,
  maps/ETA, distributed message queue, metrics and alerting, ad click aggregation (exactly-once
  counts), hotel reservation (double booking), email service, object storage, gaming
  leaderboard, payment system, digital wallet, stock exchange (matching engine latency).
- **SaaS**: multi-tenant webhook delivery engine; per-tenant usage metering and billing;
  feature-flag service; audit-log service; SSO/permissions service (ReBAC).
- **E-commerce**: flash sale with limited stock; product catalogue + search; order and fulfilment
  pipeline.
- **Mobile**: news-feed app, chat app, offline-first notes app, pagination library, stock trading
  app (real-time quotes on bad networks).
- **Embedded/IoT**: fleet telemetry and OTA updates for 10M devices; smart-home command and
  control.
- **ML**: visual search, video recommendation, ad click prediction, fraud detection, people you
  may know, harmful-content detection.
- **GenAI**: enterprise RAG with document permissions, customer-support chatbot, code assistant,
  text-to-image service, LLM gateway (routing, quotas, caching), agent platform with tool use.

## Sources
- Hello Interview, "The system design interview: what is expected at each level":
  hellointerview.com/blog/the-system-design-interview-what-is-expected-at-each-level
- Hello Interview, "Staff-level system design": hellointerview.com/blog/staff-level-system-design
- Problem lists echo the case studies in Alex Xu's System Design Interview vols. 1-2, Aminian &
  Xu's ML System Design Interview, Aminian & Sheng's Generative AI System Design Interview, and
  Vicente Vivo's Mobile System Design Interview.
