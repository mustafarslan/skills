# spm — design rationale

Why spm looks the way it does. Read this before changing anything; each rule exists because the
simpler version failed.

## The problem it solves

A product manager (PM) asked an AI assistant to write a build spec. The assistant read the
codebase and wrote requirements that **quoted code and chose the design** (tables, endpoints,
screens, interaction steps). Engineering then received design decisions disguised as requirements,
and the decision was never the PM's to make. spm makes the assistant write only *what* and *why*,
and leaves *how* to engineering and to the UI/UX designer.

## Decisions (each was a deliberate choice)

- **A personal skill, not a plugin.** Global for the PM, triggered by `/spm` or by the word "spm"
  through a personal `UserPromptSubmit` hook. Shipped as a zip with an installer.
  In this repository it also comes with the plugin. The word trigger stays opt-in there (a
  plugin-wide prompt hook would run for every plugin user), and the hook command uses
  `${CLAUDE_SKILL_DIR}`, so one install works from any project.
- **It asks, never assumes.** At most 4 questions per `AskUserQuestion` call, grouped by section
  (by story in the stories/examples phases). Options never carry a "recommended" mark. Whatever the
  PM skips goes to Open questions and is never filled in by the assistant.
- **No code wall, output-side gates instead.** An early idea was to forbid the assistant from
  reading the repository. Rejected: reading helps it ask better questions. Instead, the
  *output* is gated: writing rules, a checker with a cross-check against real identifiers in the
  repo, a fail-closed Write/Edit hook on spm-marked files, and a "twin implementation" red-team
  agent (it designs the feature twice, bespoke and generic, then swaps four mechanisms to expose
  wording that only one build can satisfy).
- **The standard is "no silent leak", never "zero leaks".** All reviewers agreed that zero
  leaks cannot be proven. What can be promised: nothing code-shaped, technical or UI-shaped
  reaches a pack file outside `design-input.md` (the gate fails closed), and every flagged item
  carries the PM's recorded decision.
- **Strict standard: "no leak" means no solution direction of any kind.** Technology,
  architecture, UI/interaction and suggestions are all out, in the files *and* in spm's own
  questions. The spec says four things only: the problem, what users expect, the observable
  behaviour, what done means.
- **Agile shape.** Epic in `intent.md`; user stories in `stories.md` ("As a / I want / so that");
  acceptance criteria `AC-nn.m`; a per-story "Done when"; examples in `scenarios.md`. The team's
  own Definition of Done stays with engineering.
- **Two exceptions, both explicit.** A *channel word* (email, mobile, PDF) is allowed only when it
  is declared in intent.md Constraints with the users' reason (a boundary of the users' world).
  UI/UX material is allowed only in `design-input.md`, where every item has a `Source: UI/UX
  designer` line.
- **The PM's own how-ideas are kept, but away from the spec.** They go in
  `ideas-for-engineering.md` in a separate render folder; never handed over, never checked.
- **spm's own examples must be clean.** Early versions of the skill taught the leaks themselves
  ("a page saying…", "via email reply"); those examples were rewritten in behaviour form. Audit any
  example you add with the same checker.
- **Output handling.** It always asks for the output folder. `intent.md` is a *draft* that
  engineering promotes. It writes files and stops; it never commits, branches or pushes.
- **Dummy data.** Raw inputs shaped the way customers send them (CSV, `.eml`, HTML, PDF where
  possible) plus outcome tables in business terms. All names, companies and addresses fictional;
  emails end in `.example`.
- **Styled render is optional.** Only when the `design-doc` skill exists; otherwise ask: plain
  or skip.

## Measured results of the strict version (what "good" looked like)

- 21 questions in 7 calls (was 40 in 15).
- Options that named a design: 1 of 66.
- Checker findings on the final pack: 0. Red-team findings: 13 (was 21); what remained was
  message grouping, timing and expiry anchoring.
- A constraint without a settled reason does not count.

## Known limits (say them out loud in the README)

- `--approve` cannot prove the red team ran: the PM's own session writes the reports. It proves the
  record is complete and consistent. Engineering gets a prompt in `VERIFY.md` to re-run the
  engineer's pass independently.
- The skill's hook persists for the rest of the session once the skill loads.
- The skill needs permission approval to load; if declined there is no gate, so the installer
  pre-approves `Skill(spm)`.
- Plain-words solutions are caught by the red team and by the engineer's review, not by regex.
