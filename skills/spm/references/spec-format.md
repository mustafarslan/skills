# spm pack format

A pack is one folder. Engineering receives all of it:

```text
<output-folder>/
  intent.md        the epic: problem, why, hypothesis, success measures, constraints, scope, open questions
  world.md         tenants, personas, outside systems, documents, values, glossary, accepted terms
  stories.md       user stories, each with acceptance criteria and a "Done when" line
  scenarios.md     worked examples per story: Given/When/Then, outcome table, must-not list
  design-input.md  only if the PM has UI/UX designer material; every item names the designer as source
  decisions.md     the PM's decision on every red-team finding, and their approval
  redteam-1.md     red-team pass 1 (two builds, four swaps)
  redteam-2.md     red-team pass 2 (the engineer's and the designer's view)
  inputs/          raw files as a customer would send them (CSV, .eml, HTML, PDF)
```

Outside the pack, in the render folder, and never handed over:

```text
<render-folder>/ideas-for-engineering.md   the PM's own how-ideas, in their words; never checked
```

`intent.md`, `world.md`, `stories.md`, `scenarios.md` and `design-input.md` start with this line.
The write gate checks those files whether or not the line is there (a new file with one of these
names, or one next to a marked pack file). Always write the line:

```text
<!-- spm:draft — engineering to promote -->
```

Write them in this order: `world.md` and `intent.md` first, then stories, then examples. The
gate reads personas, values and constraints from the first two.

## intent.md (the epic)

```text
<!-- spm:draft — engineering to promote -->
# <Feature> — epic

Status: draft by product; engineering promotes it. Date: <date>.

## Problem
<Who has it, what they do today, what it costs them, the evidence. The PM's words.>

## Why now, and for whom
<...>

## Hypothesis
If <persona> can <capability, in user terms>, <business outcome>.

## Success measures
| ID | Measure | Target | Early sign |
|---|---|---|---|
| M-1 | Median wait for an approval decision | under one working day | share of decisions made the same day |

## Constraints
| Constraint | Why | Source |
|---|---|---|
| email | Approvers do not sign in to the product; they read their email every day | PM, <date> |

## Out of scope
- ...

## Assumptions (confirmed by product)
- ...

## Open questions
| # | Question | Owner | Blocks |
|---|---|---|---|
```

- A Constraint is a fact about the users' world that the product has to live with, together with
  the reason. It is never a choice inside the product. Channel words (email, mobile, PDF, …) are
  allowed in the pack only when they are listed here.
- The Hypothesis names no solution and no solution category.

## world.md

```text
<!-- spm:draft — engineering to promote -->
# <Feature> — world

All names, companies and addresses are fictional. Email addresses end in .example.

## Tenants
| ID | Name | Kind of business | Currency | Notes |
|---|---|---|---|---|

## Personas
| ID | Name | Tenant | Business role | Email |
|---|---|---|---|---|

## Outside systems
| Name | What it is |
|---|---|
| Customer ERP | The customer's accounting system |

## Canonical documents
| ID | Kind | Key facts | File |
|---|---|---|---|

## Values
| Name | Value | Meaning | Source |
|---|---|---|---|
| Level-1 limit | 50.000,00 TRY | Highest amount a level-1 approver may approve, inclusive | PM <date> |

## Glossary
| Term | Meaning |
|---|---|

## Accepted terms
- <term> — <why it is the customers' own vocabulary> (PM, <date>)
```

- "Business role" holds a plain role noun, such as "Approver". The checker accepts it as an
  actor, singular or plural.
- Each name has one value. A value applies to every tenant unless the PM says it differs per tenant;
  if it does, say so in Meaning.
- Mark every boundary as inclusive or exclusive. Amounts carry their currency.
- Value names follow the same rules as the rest of the pack: no UI words.

## stories.md

```text
<!-- spm:draft — engineering to promote -->
# <Feature> — stories

### US-01 — Decide without signing in
**US-01 (P0)** As an Approver, I want to decide on an invoice from my email without signing in, so that invoices do not wait for me.
**AC-01.1** When an invoice above the Level-1 limit is waiting, the level-2 approver receives an email asking for a decision.
**AC-01.2** When the Decision time limit has passed, the approver cannot decide from that email and is told how to ask again.
**AC-01.3** Nobody can decide on an invoice from an email that was not sent to them.
**Done when:** AC-01.1 to AC-01.3 hold, examples EA-01 to EA-03 pass, and it serves M-1.
```

- The story line, each criterion, and each Done when line stay on one line apiece.
- "I want" names what the persona wants to achieve. It never names a feature, a screen or a
  control.
- When an outcome is still open, write `**AC-01.4** <actor> sees the outcome that Q-nn decides`.
  An unknown priority is `(P?)` with an open question.
- Unknown on-screen wording stays unknown. Only design input may quote exact copy.

## design-input.md (only from a UI/UX designer)

```text
<!-- spm:draft — engineering to promote -->
# <Feature> — design input

### D-01 — <what the material covers>
Source: UI/UX designer, <date>, <material: mock-up name, link or file>
<The designer's direction, in the designer's words or a faithful summary of them.>
```

- Every `D-nn` item has a `Source:` line naming the UI/UX designer. Without it the gate blocks.
- spm never writes design input of its own.

## decisions.md

This is the ledger of the PM's decision on every red-team finding. It has no draft marker, and the
leak checker doesn't read it, because it quotes the flagged words.

```text
# <Feature> — decisions

| Pack | Finding | Where | Words | Decision | Reason | Date |
|---|---|---|---|---|---|---|
| 3f9a1c0d2b7e4a51 | RT1-03 | stories.md:12 | "a list of its own for price lists" | rewrite | now AC-02.1: finance can find every valid price list | <date> |
| 3f9a1c0d2b7e4a51 | RT2-01 | scenarios.md:40 | "recalculated overnight" | move | the PM's idea; now in ideas-for-engineering.md | <date> |

## Approval
Approved by <name>, <date>
```

- Pack is the hash on the first line of the red-team report the finding came from. A new round
  numbers from RT1-01 again, so each round gets its own rows.
- Decision is exactly one of `rewrite`, `move` or `keep`. In the final round only `keep` can stand:
  a rewrite or a move changes the pack, and that needs a fresh round.

## Red-team reports

`redteam-1.md` and `redteam-2.md` hold the agent's answers verbatim. The first line of each is
`<!-- spm:redteam pack=<hash from --pack-hash> -->`.

## scenarios.md (examples)

```text
<!-- spm:draft — engineering to promote -->
# <Feature> — examples

## Story: US-01

### EA-01 — Approves from the email
Priority: P0 · MVP · Covers: US-01 · Inputs: inputs/EA-01_waiting.csv

**Given** invoice INV-0042 of 48.750,00 TRY waits for Ayşe (U-ANA-02)
**When** Ayşe approves INV-0042 from the email, without signing in
**Then** Ayşe sees INV-0042 as approved

| Who | Observes | Expected |
|---|---|---|
| Ayşe (U-ANA-02) | Invoice INV-0042 | Approved by her, decided from email |
| Customer ERP | Approved invoices | INV-0042 is among them |

**Must not:**
- Mehmet receives a second request for INV-0042
```

- IDs are unique in the pack.
- Amounts and dates in examples are data. They need no entry in Values.
- Boundary examples come in pairs: one on the boundary and one just past it (50.000,00 and
  50.000,01).
- Inputs mirror what customers really send: messy formats, local number styles, forwarded
  threads, auto-replies, scans. File names start with the example ID.
