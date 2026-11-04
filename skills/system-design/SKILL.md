---
name: system-design
description: Designs, reviews and stress-tests software systems at a staff-engineer bar - requirements and non-goals first, capacity math from a script, the simplest design that meets the numbers, failure cascades and disaster recovery, and a trade-off table with a measurable trigger per decision. Use whenever the user asks to design or architect a system or service, choose between technologies (Kafka vs SQS, Postgres vs DynamoDB, monolith vs microservices), partition or shard data, estimate capacity, review a design doc, write or review an ADR, or practise a system design interview as candidate or interviewer, for SaaS, e-commerce, fintech, mobile, IoT, data or AI/RAG systems. Not for writing application code, product requirements (spm), styling a document (design-doc), explaining a single concept, or writing interview question lists.
argument-hint: "[problem] [--interview [candidate|interviewer]] [--review <path>] [--deep-dive <topic>] [--html]"
allowed-tools: Read, Grep, Glob, Write, Edit, Agent, AskUserQuestion, Bash(python3 ${CLAUDE_SKILL_DIR}/scripts/*), Bash(agy-ask *)
---

# system-design

A default model draws "the complete textbook": every box, no numbers, no opinion on what breaks
first, and it agrees with every steer. This skill exists to do the opposite.

## Standing rules (hold on every turn, in every mode)

1. **No boxes before the frame is locked.** No component, database or diagram until the
   functional scope, non-goals, the numeric non-functional targets (latency percentile,
   availability, durability, RPO/RTO) and the archetype are written down. In an interview, a
   2-minute frame is enough. In a real design with the user present, ask (3-5 questions at a
   time) and **stop before phase 2** until the load-bearing constraint is known. If the user
   says they are unavailable or "assume", or AskUserQuestion is not available (a headless
   run), do not ask: put the questions you would have asked in the doc's Open questions,
   answer each with an **assumed** value, and carry on.
2. **Numbers come from the script, not from your head.** Run
   `python3 ${CLAUDE_SKILL_DIR}/scripts/capacity_calc.py` for traffic, storage, cache,
   connections, availability, vector memory, restore time, LLM serving, stream partitions and
   cost. Pass every input you guessed in `--assumed`;
   if a trigger fires only at the high end of the band, the decision rests on a guess -
   confirm that input before building on it. Label every input **given** or **assumed**.
3. **Boring by default.** Start from one deployable (a modular monolith), one primary database,
   synchronous calls and a cache. Add a service, a queue, a second datastore, sharding or
   multi-region only when a number, a hard requirement, or the team's shape forces it - and say
   which. A 5-person team does not run eight services, Kafka and Cassandra.
4. **Every component earns a trade-off row.** `Decision | Solves | Worsens | Change it when`,
   where *Change it when* is an observable trigger with a number and a comparison
   ("p99 write latency > 50 ms for 1 h", "a tenant > 5% of total QPS"). Triggers must agree
   with the estimation - a trigger at 50k QPS on a system the math puts at 500 QPS is a
   strawman.
5. **Make the decision.** Lay out options only to choose between them. Say what you would do
   and why, then what would change your mind.
6. **Push back with numbers.** When the user (or an interviewer) proposes something that breaks a
   locked requirement, do not just comply: show which target it breaks and by how much, offer
   the option that keeps it, and let them decide. Accept a steer that holds up, and say what it
   changes.
7. **Say what the user sees.** Never write "eventual consistency" without the staleness window,
   who sees stale data, and what happens to a decision made on it.
8. **Name what breaks first** at today's numbers and at 10x, and how the system degrades
   rather than how it works on a good day.
9. **Load references just in time**: one file, for the phase at hand, from the map below. Do
   not read them all up front.

Keep these rules at about ten; they are for mistakes that happen in every phase. A lesson for
one phase or topic goes in the `## Traps` section of the reference loaded for it, with the eval
that justifies it (see `evals/README.md`). Paths: if `${CLAUDE_SKILL_DIR}` is empty, use the
directory this SKILL.md was read from.

## Modes

Parse `$ARGUMENTS`. The first non-flag words are the problem.

| Mode | Trigger | Ends with |
|---|---|---|
| **design** (default) | a real system in this or another project | `docs/design/<slug>.md` (+ `docs/adr/NNNN-<slug>.md` per major decision), passing `check_design.py` |
| **interview** | `--interview` or "mock interview", "practise system design" | as `candidate`: a timed answer, then a scored self-review. As `interviewer`: you run the round, then score the user. Rules in `references/interview-mode.md` |
| **review** | `--review <path>` or "review this design" | the gate's structural gaps first (`check_design.py <path> --draft`), then findings ranked by severity, a rubric score, and the questions the design must answer |
| **deep-dive** | `--deep-dive <topic>` or one narrow question ("how should I partition the orders table?") | a short decision write-up: options, the choice, trade-off rows, the numbers behind it |

`--html` also renders the diagram as styled HTML+SVG (see `references/output-templates.md`).
Without it, diagrams are Mermaid blocks in the Markdown.

In **design** mode, if the project already has an architecture (code, `docs/`, ADRs), read
enough of it first to know what exists: this is brownfield, and the migration is part of the
design (`references/evolution-migration.md`).

## The loop

The phases are a loop, not a line. When a new fact or a steer invalidates an earlier phase,
**say so** ("this moves the write rate past one primary - back to phase 4") and go back to that
phase; do not patch the later phases around it.

### 1. Frame
- Classify the **archetype** (one primary, maybe a secondary) and read its section in
  `references/archetypes.md`: what dominates it, the forcing questions, the usual traps.
  Client-heavy systems (mobile, offline-first, embedded/IoT): also `references/clients-mobile-embedded.md`.
  AI/ML/GenAI: also `references/ai-ml-systems.md`.
- Pin down, asking 3-5 high-leverage questions at a time (never a 20-question form):
  users and growth, read/write ratio and shape, latency and availability targets, consistency
  needs per data type, **non-goals**, and - in design mode - **team size and skills, budget,
  compliance/data residency, and what exists today**. These last four constrain topology as much
  as traffic does; collect them now, not in phase 7.
- Spot **contradictory requirements** (global sub-50 ms writes + serializable + cheap) and make
  the user choose. Use `references/requirements-estimation.md` for SLO/SLA wording.
- If the user cannot answer, state an assumption, mark it **assumed**, and move on.

### 2. Quantify
- Run the calculator with given and assumed inputs and save its output next to the doc, e.g.
  `python3 ${CLAUDE_SKILL_DIR}/scripts/capacity_calc.py --dau 2e6 --reads-per-user 40 --writes-per-user 4 --write-bytes 800 --read-bytes 4000 --db-ms 4 --assumed peak,write-bytes --out docs/design/<slug>.calc.json`
  Re-run it whenever an input changes; the gate reads that file. When the brief gives volumes
  rather than users, use `--writes-per-day/--reads-per-day`; for a burst, `--peak-read-qps/
  --peak-write-qps`. `--help` lists every section: availability (`--serial/--parallel`),
  vectors, restore time (`--restore-mbps --rto-min`), LLM serving (`--llm-rps`, token counts,
  `--decode-tps`, model shape, `--gpu-mem-gib`), streams (`--events-per-sec
  --partition-mbps --consumer-ms`) and cost (`--price-*`; prices are always your inputs).
- Turn the output into **forcing functions**: which triggers fired, what they rule in or out.
  Quote the numbers in the doc. Interview mode: order of magnitude in ~2 minutes, size
  components later inside the deep dives.

### 3. Contracts and data model
- The core APIs (style, idempotency keys on every mutating call, pagination, versioning) -
  `references/network-edge-api.md`.
- Entities, access patterns first, then keys: primary, partition, sort/clustering, the indexes
  each query needs, and the concurrency control on contended rows - `references/data-storage.md`.

### 4. Topology
- Draw the simplest end-to-end path that meets the frame (Mermaid). Monolith vs services, sync
  vs async, where state lives - `references/services-architecture.md`.
- For each service or module that you keep: its responsibility, the data it owns, its internal
  shape in a sentence or two (e.g. hexagonal: domain core, ports for its DB and broker).
  Full internal design only on request or in deep-dive.
- **Build or buy**: for each major component, name the managed service or product that would
  do it (a webhook-delivery SaaS, a sync framework, a hosted search) and the condition under
  which buying wins (cost within ~2x of building, team size, time to market).

### 5. Deep dives (most of the time goes here)
Pick the **two hardest problems** for *this* system - the ones most likely to fail, not the most
familiar - and go deep: mechanism, numbers, alternatives, decision. Trace the exact data each
hop carries (client → CDN → service → store) and check every step is atomic or idempotent; a
mechanism that cannot carry the field it needs is the most common deep-dive bug. Load the one reference that
covers each (data-storage, distributed-correctness, network-edge-api, services-architecture,
ai-ml-systems, clients-mobile-embedded).

### 6. Failure and recovery
Test every control loop or admission formula against a **skewed key** (one popular size, one
whale tenant, one hot region) and against users who drop out mid-flow - a formula that is right
on average can stall or starve on the skew. Walk at least one **cascade** end to end (e.g. cache flush → DB pool exhaustion → timeouts →
retry storm → queue backlog) and the defences that stop it; define degradation modes, the DR
tier with RPO/RTO (check the RTO against the calculator's restore time: `--restore-mbps
--rto-min` with the storage inputs or `--data-tib`), and what is sacrificed under partition
(PACELC). Add one **end-to-end
invariant check** that would catch silent loss (a reconciliation job, an alert on items stuck
in a pending state past N minutes) -
`references/reliability-operations.md`, `references/distributed-correctness.md`.

### 7. Cross-cutting
Security and tenancy isolation, data lifecycle (retention, deletion across logs, backups and
indexes), observability (what the on-call engineer looks at first), delivery and rollback, cost
at today's and 10x scale from the calculator's cost section with the user's prices (name the
largest line) - `references/security-delivery-cost.md`,
`references/reliability-operations.md`.

### 8. Trade-offs and evolution
The trade-off table (rule 4), then the path to 10x and 100x: re-run the calculator with
`--scale 10,100` and build each step from what fires at that factor - what changes, the
trigger that starts it, and how to migrate without downtime -
`references/evolution-migration.md`.
In design mode, **write the draft now** (`docs/design/<slug>.md`, status `draft`, and an ADR
per major decision, status `proposed`) so the reviewers have a file to read. Before
dispatching them, run the gate in draft mode and fix what it lists:
`python3 ${CLAUDE_SKILL_DIR}/scripts/check_design.py docs/design/<slug>.md --draft --calc docs/design/<slug>.calc.json`

### 9. Review (mandatory in design and review modes; after the round in interview mode)
Never skip or defer this phase in those modes. Dispatch the reviewer and, when available, agy **in the same message** so they run in parallel:

- **Reviewer agent.** Agent tool with `subagent_type: system-design-reviewer` (installed copy) or
  `skills:system-design-reviewer` (plugin). If neither exists, use `general-purpose` with the
  instruction "Read `${CLAUDE_SKILL_DIR}/../../agents/system-design-reviewer.md` if it exists and
  follow it; otherwise review with five lenses: failure cascades, data and consistency,
  boundaries and communication, security/cost/AI, rubric score." Give it the doc path and the
  calculator output; it shares none of this conversation.
- **No Agent tool on this surface** (e.g. a chat with no subagents): do the review yourself as
  a separate pass - re-read the doc from the top with the five lenses of
  `agents/system-design-reviewer.md` (or the list above) and write findings in its report
  format. Record it in the Review log as **self-review (no independent reviewer available)**
  and say so in the summary. Never describe a self-review as an independent review.
- **agy** (a second model family) - best effort. Write a brief to a temp file: the problem, the
  frame, the doc path, and "challenge the approach: the 3 most likely ways this design fails in
  production, and any trade-off trigger that does not match the estimation; under 400 words".
  Run `agy-ask --cwd <repo root> -f <brief>` exactly - no `--model`/`--effort` (the wrapper's
  defaults are right) and **no `--boost`** unless the user said "boost".
  - `AGY_UNAVAILABLE` (exit 127): skip silently; never suggest installing it.
  - `AGY_FAILED` (2), `AGY_QUOTA` (3), `AGY_AUTH` (4): carry on without it and **say which**.
    Never retry quota or auth failures. Never present a failed review as a clean one.
  - Tag its findings `agy` and keep them a separate voice from the reviewer's and your own.

Verify every finding against the doc before acting on it; reject the ones that do not hold and
say why.

### 10. Revise and gate
Apply what held up. If a fix changes an input (a second stream, a new write path, a bigger
payload), re-run the calculator with `--out` and update every figure that came from it - the
estimation, the triggers and the evolution steps - before the gate. Then run the gate and fix
every gap it lists:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/check_design.py docs/design/<slug>.md --calc docs/design/<slug>.calc.json
python3 ${CLAUDE_SKILL_DIR}/scripts/check_design.py docs/adr/NNNN-<slug>.md --kind adr
```

`DESIGN_OK` means the structure is there, not that the design is good. Report to the user: the
decision summary, the open questions and assumed inputs that most move the design, reviewer and
agy findings (accepted / rejected and why), and the gate result.

## Reference map

| File | Load when |
|---|---|
| `references/archetypes.md` | phase 1, always (one section) |
| `references/requirements-estimation.md` | phase 1-2: SLO wording, estimation method, latency numbers |
| `references/network-edge-api.md` | APIs, DNS/CDN/load balancing, realtime push, rate limits |
| `references/services-architecture.md` | monolith vs services, DDD, hexagonal/onion, messaging, sagas, outbox, CQRS |
| `references/data-storage.md` | choosing a store, schema and keys, indexes, locks and isolation, partitioning, replication, caching, hot keys |
| `references/distributed-correctness.md` | CAP/PACELC, consensus, quorums, idempotency, ordering, clocks, exactly-once |
| `references/reliability-operations.md` | cascades, resilience patterns, DR tiers, observability, probes, SLOs |
| `references/security-delivery-cost.md` | authn/z, tenancy isolation, secrets, compliance and deletion, CI/CD, rollouts, cost |
| `references/ai-ml-systems.md` | ML training/serving, RAG, LLM serving, guardrails, evals, agents |
| `references/clients-mobile-embedded.md` | mobile, offline-first, sync and conflicts, version skew, IoT/firmware |
| `references/evolution-migration.md` | 10x/100x, brownfield, migrations and backfills, cells, team boundaries |
| `references/interview-mode.md` | interview mode: time boxes, level bar, interviewer script, scoring |
| `references/output-templates.md` | writing the design doc, ADRs, the trade-off table, diagrams |

## Output

Design mode writes the files with Write and revises them in place while they are `draft` /
`proposed`. A design doc or ADR that was already `accepted` before this run is never rewritten:
add a new ADR that supersedes it; the only change allowed in the old one is its Status line
(`superseded by NNNN`). Record the review in the doc's `Review log` section. Diagrams follow `references/output-templates.md`. In the
chat, keep the answer to the decisions and the open questions; the detail lives in the doc.

Ideas in this skill draw on proyecto26/system-design-skills and alirezarezvani/claude-skills
(both MIT); the text is original.
