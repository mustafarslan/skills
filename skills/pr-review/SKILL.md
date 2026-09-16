---
name: pr-review
description: Use when asked to review a PR, check or look over a PR, give a second opinion on someone's changes, or review the current branch before pushing.
argument-hint: "[PR number or URL, or nothing to review the current branch]"
allowed-tools: Bash, Read, Grep, Glob, ToolSearch, AskUserQuestion
---

# PR Review

Review as a senior engineer who maintains this codebase. Find what the author
missed — do not summarize the change.

**Target:** `$ARGUMENTS` — a PR number or URL. If empty, review the current
branch against its base and skip the fetch in §1; ask first if that isn't
obviously what was meant.

**Adapt to the repo.** This skill is a method, not a toolchain. Wherever it
says "the repo's test command", "the migration command", "the config file",
find the real one before you need it: `CLAUDE.md`, `CONTRIBUTING.md`, the
README, `package.json` scripts, `Makefile` / `justfile`, `pyproject.toml`, and
the CI workflows (`.github/workflows/`). CI is the most reliable source — it is
what actually runs. If a step has no equivalent in this repo, skip it and say
so in the report.

---

## 1. Isolate

Never review in the user's checkout — they may have uncommitted work, and
`gh pr checkout` would switch their branch. Pull the PR into its own worktree on
a temp branch.

Resolve the **main** checkout first: this may be run from inside one of the
repo's existing worktrees, where `--show-toplevel` returns the worktree, not the
repo.

```bash
N=<PR number>
MAIN="$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")"
BASE=$(gh pr view $N --json baseRefName -q .baseRefName)
WT="$MAIN/.claude/worktrees/pr-$N"

# A stale worktree from an earlier review holds the branch, blocks both commands
# below, and would review stale code. Tear it down first (§9).
[ -e "$WT" ] && echo "pr-$N worktree exists — run §9 cleanup before continuing"

git -C "$MAIN" fetch origin "$BASE" "+pull/$N/head:pr-$N"   # '+' so a force-push fast-forwards
git -C "$MAIN" worktree add "$WT" "pr-$N"
```

A fresh worktree holds only tracked files. Copy the gitignored local config the
tests need (typically `.env` files) from `$MAIN` to the same relative paths
under `$WT`. To see what is ignored without listing every dependency file:

```bash
git -C "$MAIN" ls-files --others --ignored --exclude-standard --directory | grep -i env
```

**Every path passed to a file tool must start with `$WT`.** A path beginning at
the repo root silently reads the main checkout instead of the PR — including
`CLAUDE.md` or `.claude/rules/*.md` if this PR edits one. Run commands as
`cd "$WT" && …` or `git -C "$WT" …`.

You are **read-only on the PR's content**: never edit its files, commit, or
push. The worktree, the temp branch, any scratch database or service, and any
throwaway test you write are yours to create and delete.

### Give shared services an instance of their own

A worktree isolates files, not services. If the test suite talks to a local
database, queue, or cache, every worktree hits the same instance, and the
user's config points it at their dev data. Two consequences:

- Running the PR's migrations against that instance would apply an **unmerged
  migration to the user's dev database**. Never do it.
- Any test asserting a table or queue is empty is correct only against a clean
  instance; leftover dev data makes it fail for reasons unrelated to this PR.

So whenever you intend to run such tests, and always when the PR changes the
schema or adds a migration:

1. Create a scratch instance named for the PR (e.g. a `<app>_review_pr$N`
   database on the same server). If the repo runs its services through docker
   compose, create it through the compose service — host CLI clients often
   prompt for a password and hang the shell.
2. Repoint the connection setting (e.g. `DATABASE_URL`) in the **worktree's
   copy** of the config only. With `sed`, use `-i.bak` and delete the `.bak`
   afterwards — that form works on both BSD and GNU sed.
3. Confirm which setting the app, the test runner, and the migration tool each
   read. They are not always the same one, and one you missed still points at
   dev data.

**Sanity gate — run before every test or migration invocation**, and quote the
result under Evidence: grep the connection setting out of the worktree's config
(e.g. `grep '^DATABASE_URL' "$WT/.env"`).

If it still names the dev instance, or the config file is missing, stop. A
missing env file usually fails open: the loader proceeds silently and you test
against the wrong database.

Bring up a fully separate stack only when a claim needs the **running app**, not
just tests. Check afterwards that host-run tests still go through the scratch
instance — a separate stack does not repoint them by itself.

### Run tests and migrations the right way

Use the repo's own entry points (the scripts CI runs), not bare tool
invocations. A wrapper script often loads env files or sets config that a bare
`pytest` / `jest` / `go test` skips — and the skipped config is usually the
connection setting you just repointed, so a bare run silently falls back to the
shared instance. Read how the wrapper loads config before trusting it.

Migrations have the same trap: find where the migration tool gets its connection
(shell environment, config file, env file) and use the documented invocation —
sourcing the worktree's env file first if that is what the tool needs.

A fresh worktree has no installed dependencies (`node_modules`, virtualenvs,
build output). Run the repo's install command first. If you skip this, say so
and run no tests rather than reporting install errors.

## 2. Baseline before you blame

Before trusting any failure at PR head, run the same suite at the merge base —
**migrating at each checkout** if the repo has migrations, so each side's tests
meet their own schema. A migration that renames or drops something otherwise
produces spurious base failures and the delta reads backwards.

```bash
MB=$(git -C "$WT" merge-base "origin/$BASE" "pr-$N")

git -C "$WT" checkout --detach "$MB"
# migrate the scratch instance, then run the suite — record failures

git -C "$WT" checkout "pr-$N"
# migrate again, then run the same suite — compare
```

If the lockfile differs between the two, reinstall dependencies at each
checkout. Migrating at both checkouts also makes the PR's migration forward-path
a tested step rather than an assumed one.

**Only the head-minus-base delta is a finding.** Failures present in both runs
are pre-existing — dev-data pollution, schema drift, or a known flake. Same rule
for flakes generally: fails once, passes on rerun, and the test file is absent
from the diff → note it under Evidence, do not report it.

## 3. Load the context that governs this diff

Do all four of these **before** forming an opinion on the diff.

### The linked issue — the acceptance criteria

Find the issue the PR addresses: a closing keyword in the PR body (`Fixes #123`,
`Closes #123`), or a tracker key (`PROJ-123`) in the body, title, or branch
name. Then read it:

- GitHub issue → `gh issue view <number>`.
- Another tracker → `ToolSearch` for a connected issue-tracker MCP server and
  fetch the issue with it. Its issue-fetch tool must be allowed: add it to
  `allowed-tools` in this file's frontmatter (e.g. `mcp__<server>__get_issue`).
- Neither available → work from `gh pr view $N --json body`, and say so in the
  report.

**No issue and no stated criteria — ask before spending the run.** When there
is no linked issue *and* the PR body names no acceptance criteria, what you are
judging the diff against is undefined, and that choice governs every lens
below. Ask (`AskUserQuestion`): review against the description as written, or
against a requirement the user states now? One question, before §4.

**"Does it do what was asked" outranks every other lens.** Judge the diff against
the issue's stated requirement, not against what the code appears to intend. A
requirement in the issue that the diff doesn't meet is Critical even when every
line is correct. Conversely, scope in the diff that the issue never asked for is
a finding too — name it, don't assume it's wanted.

### Prior review comments — don't repeat them

```bash
gh pr view $N --comments
gh api "repos/{owner}/{repo}/pulls/$N/comments" --jq '.[] | "\(.path):\(.line) \(.user.login): \(.body)"'
```

Review bots, a previous Claude review, and human reviewers have often been here
already. **A finding someone already raised is noise** — drop it, whether or not
the author acted on it. If an earlier finding was raised and explicitly dismissed
by the author, that is settled: do not relitigate it. Only re-raise a prior
finding if you have new evidence (a reproduction, a failing test) that the
earlier comment lacked, and say what's new.

Read the author's replies too — they are the cheapest source of intent (§4.3).

### Related PRs — keep the scope to this one

```bash
git -C "$WT" diff --name-only "origin/$BASE...pr-$N" | sort > "/tmp/pr-$N-files"
gh pr list --state open --limit 30 --json number --jq '.[].number' | while read -r M; do
  [ "$M" = "$N" ] && continue
  OVERLAP=$(gh pr view "$M" --json files --jq '.files[].path' | sort | comm -12 - "/tmp/pr-$N-files")
  [ -n "$OVERLAP" ] && printf 'PR #%s also touches:\n%s\n' "$M" "$OVERLAP"
done
```

An open PR touching the same files can mean a merge-order dependency or a
conflict — surface it as an Improvement with both PR numbers, and check whether
the finding you're about to file actually belongs to the *other* PR. **Findings
must be scoped to this PR's diff.** Work the sibling PR leaves undone is not this
PR's defect.

### The rules

Read `CLAUDE.md` if it isn't already in context, plus any nested `CLAUDE.md` in
directories the diff touches. Path-scoped rules are a separate matter:
`.claude/rules/*.md` files load when a matching file is *opened*, and a diff
opens nothing. **For every area the diff touches, open the matching rule files
yourself** (under `$WT`) — match each rule's `paths` frontmatter, or the mapping
in `CLAUDE.md` if the repo keeps one. A finding that contradicts a rule you
never read is the most common miss.

Read `CONTRIBUTING.md` too, and the feature's design doc or spec when the repo
keeps them — it is the source of truth for how the feature should work.

Apply the rules; don't restate them in the report.

## 4. Method — in order

1. Record every factual claim the PR description makes (lens C).
2. Read the diff in full before judging anything. Skim-flagging is worse than silence.
3. For each candidate finding, try to disprove it first: is it actually
   reachable, or am I inferring from a name? Is it already handled elsewhere in
   the diff, or by a caller? Is it pre-existing rather than introduced here?
   **Did the author do this on purpose?** A code comment, the PR description, the
   linked issue, a design doc, or a reply to an earlier review saying so makes it
   a deliberate choice, not a defect — drop it. Question a deliberate choice only
   when it breaks a stated invariant or a requirement, and then argue against
   the stated reason rather than pretending it wasn't given.
   Has a previous reviewer already raised it (§3)? Then drop it.
4. If you cannot cite the `file:line` that makes it true, drop it. Never report a
   finding whose evidence is "this looks like it might".
5. Where you can settle it by running something, run it — §1 gave you a safe
   place to. A reproduced failure outranks an argument.
6. Run the mechanical checks the diff triggers, then the docs-drift pass.
7. Rank what survives. Clean up (§9). Print the full report to the terminal
   (§11) — that is free and always happens, and it is the evidence the user
   triages from. Then §13: ask what goes out, and post it.

**Where to ask, and where not to.** Three questions, each on an observable
predicate — not a running commentary:

| Ask | When | §  |
|---|---|---|
| What are we reviewing against? | No linked issue **and** the PR body states no acceptance criteria | §3 |
| The one open question | A real ambiguity would change the verdict — ask it live, while you can still act on the answer | §11 |
| What goes out, and as what event? | Always, before posting | §13 |

Do **not** ask per finding while reviewing. Step 3 above is the mechanism for
a doubtful finding — disprove it or drop it. Triage happens once, in §13,
against the printed report.

## 5. Two findings that are always Critical

Do not file either as an Improvement until you have traced the call stack and the
user-visible effect.

- **Fail-open.** Any new path that swallows a failure, treats an error as
  success, or falls back to a default with no log and no error. The safe
  direction is fail-closed.
- **A guard that does not guard.** A check or a test that can never fail. A test
  passing for the wrong reason is worse than no test.

## 6. Lenses

Apply all five. Use the tag in brackets when reporting.

**A. [arch] Architecture & design**
- Does the change hold the invariants in the rules you loaded? Name the rule when
  it doesn't.
- Data-model and migration rules: a model or schema change with no migration, or
  an edit to a migration that has already shipped, is Critical.
- Boundaries the codebase defines — layers, pipeline stages, modules, services:
  logic belonging to one leaking into another.
- A second, parallel way to do something the codebase already solves. An
  abstraction that is indirection with one caller.
- **Integration points.** For every contract the diff changes — a function
  signature, a return shape, an API response, a message or event type, an enum,
  a config key, a DB column — grep the tree under `$WT` for its consumers and
  check each one still holds. Name the ones you checked in Evidence. A caller
  the diff forgot is Critical; changed backend types with stale generated client
  types is the frontend case of the same defect (§7).
- **Changed flows, read end to end.** When the diff alters a multi-step flow —
  a pipeline stage sequence, a state machine transition, a request path, a
  retry/ack loop — stop reviewing lines and read the flow as it now stands, from
  entry to terminal state. Ask what the new shape does on each branch, not what
  each hunk does. Defects here (an unreachable state, a step that can now run
  twice, an ordering that only holds by accident) are invisible at line level and
  are the reason this pass exists. Say in Evidence which flow you traced.
- Failure behavior under timeout, partial failure, retry, concurrency.
- Scale: the query/loop/allocation that is fine at today's N and not at 100×.
- A load-bearing choice between real alternatives with no recorded decision
  (ADR, design doc) in a repo that keeps them — Improvement, but say it.

**B. [sec] Security**
- **Tenancy** — in a multi-tenant system, cross-tenant leakage is Critical,
  always. Every new query scopes to the tenant. If the codebase has a standard
  way to resolve the tenant (a dependency, middleware, a base query), new entry
  points use it rather than hand-rolling it; admin or internal routes may be
  deliberate exceptions. Read the repo's auth rules before calling any of this a
  finding.
- Authz on every new entry point — object-level ownership, not just "is logged in".
- Untrusted input: injection, path traversal, deserialization, SSRF, unbounded sizes.
- Secrets and PII in logs, error messages, or client-visible payloads.
- Over-broad API responses, missing field filtering, IDOR, missing rate limits.
- New dependencies: what do they pull in, maintained, pinned?
- Code that calls an LLM or runs an agent: prompt injection via untrusted content
  (user data, documents, emails, web pages), tool-call blast radius, model output
  trusted where it shouldn't be.

**C. [claim] Verifiable claims**
Extract every checkable assertion from the description, commit messages, and code
comments — "reduces latency ~40%", "backward compatible", "no schema change
needed", "covered by tests", "no behavior change". Mark each:
- **Tested** — you ran something that settles it. Show the command and output.
- **Supported** — the diff shows it. Cite `file:line`.
- **Unsupported** — the diff neither shows nor contradicts it. State exactly what
  would settle it.
- **Contradicted** — the diff or a run shows otherwise. Cite `file:line`. Critical.

You have a worktree and a scratch instance, so prefer **Tested** over Supported
wherever the claim admits it:
- *Performance* → time the same operation at `$MB` and at head. An untimed perf
  claim is Unsupported, never Supported.
- *"Backward compatible"* → restore the base's tests onto head's code and run
  them: `git -C "$WT" checkout "$MB" -- <test paths>`, run, then
  `git -C "$WT" checkout "pr-$N" -- <test paths>` to restore.
- *"No schema change needed"* → run the ORM or migration tool's autogenerate /
  check command against the scratch instance; a non-empty diff contradicts it.
- *"Covered by tests"* → name the test, then revert the fix hunk
  (`git -C "$WT" checkout "$MB" -- <source path>`), confirm the test now fails,
  and restore. A test that still passes with the fix reverted covers nothing.

Mechanical rows for the conventions the repo requires, if it has any (check
`CONTRIBUTING.md` and the PR template) — e.g. a linked issue in the description,
a changelog entry for user-facing changes, the template's checklist.

**D. [edge] Edge cases**
Hunt these specifically, then add the ones this codebase's domain implies (read
the data model — money, units, quotas, state machines):
- `None` / `null`, empty collection, single element, boundary values.
- Numbers: zero, negative, overflow, float precision, rounding, unit or currency
  mismatch.
- Dates: timezone and DST boundaries, month/year ends, leap days.
- Duplicates: the same row inserted twice; re-importing the same file or
  replaying the same event.
- Idempotency: does re-running the operation change the result?
- Concurrency: two workers or requests on the same row; lock, lease, and retry
  paths.
- Cross-tenant: the same id in another tenant.
- Strings: unicode, empty, length limits, injection-shaped content.
- Today's N vs 100×.

**Do not report an edge case you only reasoned about.** Write a throwaway test
for it in the worktree and run it. Passes → drop the finding. Fails → that is a
finding with evidence. Delete the test afterwards and never commit it.

**Report every edge case you generated, passing ones included**, as a table in
Evidence — concrete values, never prose:

| Case | Input | Expected | Actual |
|---|---|---|---|
| empty batch | `items=[]` | returns `0`, no write | `IndexError` |

The passing rows are what lets the author trust the failing ones, and they are
the test cases they should add. Give literal values: the author must be able to
paste them into a test without asking you what you meant.

**E. [ux] UI/UX** — only if the diff touches frontend code, CLI output, API
error shapes, emails, or copy.
- Read the repo's frontend rules if it has them and check the contracts they
  name — typing rules, the API client wrapper, data-fetching conventions,
  design-system and token usage, shared table and form components.
- Missing states: loading, empty, error, zero-results, partial data.
- Does a failure surface as something actionable, or as an endless spinner / raw
  exception string?
- Destructive or irreversible actions without confirmation or undo.
- Accessibility: keyboard reachability, focus after navigation or modal close,
  labels on controls, contrast, touch targets.
- Copy: jargon, blame-the-user phrasing, inconsistency with existing wording.
- Overflow for long strings, large numbers, small viewports.

## 7. Mechanical checks

Run the ones this diff triggers, from `$WT`, and **report the real output, not
the claim that it passed**:
- Inputs to code generation changed (API schema, models, config definitions) →
  run the repo's codegen or staleness check; a diff in generated output is a CI
  failure.
- Models or schema changed → the migration exists, and no shipped migration was
  edited.
- Lint, format check, type check → run the ones CI runs over the changed files,
  including docs/markdown lint if CI has a job for it.
- Behavior changed in a tested area → the relevant tests, at base and at head (§2).

If you run nothing, say "No checks run" — don't imply coverage you don't have.

## 8. Docs drift

One line each; Improvement unless the code contradicts a doc that is the source
of truth:
- Implementation diverges from the feature's design doc or spec with no update.
- New env var, script, command, or endpoint missing from the README, runbook, or
  setup docs.
- A new invariant that belongs in `CLAUDE.md` or a `.claude/rules/*.md` file,
  left only in prose or in the author's head.

## 9. Clean up

```bash
git -C "$MAIN" worktree remove "$WT" --force
git -C "$MAIN" branch -D "pr-$N"
```

Drop the scratch database or service if you created one. Confirm in the report
that the user's checkout was never touched.

## 10. Do not report

- Formatting, import order, naming style — anything the repo's formatter,
  linter, or type checker already enforces.
- Generated files as *content*: never review generated clients, generated docs,
  or similar output line by line. Do flag them stale or missing — that belongs
  under §7. Same for lockfiles, vendored code, snapshots.
- `except A, B:` as a syntax error. It is valid PEP 758 on Python 3.14 and a
  recurring false positive. The only finding it warrants is a Nit: add an `as _`
  clause so `ruff format` keeps the parentheses.
- Test failures that also fail at the merge base, or that pass on rerun (§2).
- Anything a previous reviewer already raised, or the author explicitly justified
  as deliberate (§3, §4.3). Both are settled unless you have new evidence.
- Defects that belong to a sibling PR rather than this diff (§3).
- Pre-existing issues the PR merely moves or touches — unless this change makes
  them materially worse, in which case say so and file it as an Improvement.
- Restatement of what the PR does, or "consider adding tests" with no specific
  case in mind. Name the untested case or skip it.
- Speculative refactors with no defect behind them.

## 11. Output format

Match this exactly. If a section is empty, write `None.` on one line. Do not pad.

**Verdict:** Approve / Request changes — <one clause why>
**Tally:** N critical · M improvements · K nits · J claims unverified
**Environment:** worktree `<path>` · scratch DB `<name>` or none · baseline `<sha>` · cleaned up: yes/no
**Rules read:** <rule files opened, or "none — diff touches no covered area">
**Context:** issue `<key>` <one clause: requirement met / not met> · prior reviews: N comments read, M findings skipped as already-raised · related PRs: <numbers, or none>

### Critical
Bugs, security, breaking changes, broken invariants. Max 7, most severe first.

1. **[tag] `path/file.ext:LINE`** — <one sentence: what is wrong>
   *Breaks when:* <concrete trigger → concrete wrong outcome>
   *Fix:* <one line, or ≤5 lines of code>

### Improvement
Worth fixing, not a merge stopper. Max 5, one line each. If more, append
"plus N similar".

- **[tag] `path/file.ext:LINE`** — <one sentence including the fix>

### Nit
Max 3, and each must clear the bar: **would you actually implement this?** If the
fix costs more than the defect, or you'd wave it through on a re-review, it isn't
a Nit — it's noise. Omit the section entirely if nothing clears the bar; that is
the normal case.

- **[tag] `path/file.ext:LINE`** — <one line>

### Claims
Only if the PR made checkable claims. One row each, no prose.

| Claim | Verdict | Evidence / what would settle it |
|---|---|---|

### Evidence
Commands run and their actual output, trimmed to the decisive lines — base vs
head where you compared. Include the config sanity gate. Name any throwaway test
you wrote and deleted. Or `No checks run.`

### Open question
At most one, only if a real ambiguity changes the verdict. Otherwise omit.
**Ask it live rather than filing it** — if it would change the verdict, you
need the answer before you have a verdict, so put it to the user with
`AskUserQuestion` when you hit it, and record the answer here.

## 12. Tone and style

Constructive and professional. **Explain why** a change is requested — the
*Breaks when* line is that explanation, not a courtesy. On an Approve, name the
specific thing the change gets right in one clause in the verdict; don't pad it
into a paragraph.

- Every finding: one sentence for the problem, one for the trigger, one for the
  fix. No paragraphs.
- Assert plainly. No "it might be worth considering possibly".
- If the change is clean, say so in the verdict and report nothing. A short
  review is a valid result; never manufacture findings to look thorough.
- Keep the whole report under 400 words unless Critical findings genuinely
  require more. Length lives in Evidence, not in prose.

Friendly is a shape, not an adjective — four concrete moves, all of which fit
inside the word cap:

- **Second person for the author's code.** "your `parser.py` guard", not "the
  author's guard" and not the passive "the guard was not wired".
- **The Approve verdict names what the change gets right**, specifically — the
  thing you checked, not "looks good".
- **An Arguable claim ends with one clause handing the call back** — "your
  call; flagging it so it's a decision rather than an oversight."
- **No sign-off, no thanks-for-the-patch, no apology.** One sentence naming the
  worktree and baseline is all the process narration the author needs.

## 13. Triage with the user, then post

**Only when the target was a PR.** Reviewing the current branch produces no
review to post — say that in the terminal and stop here.

### 13a. Ask, once

The §11 report is already printed. Number every finding across `Critical` /
`Improvement` / `Nit` in that printout (1, 2, 3 … continuing across the
sections) so the user can answer by number, then ask — one message, two
decisions:

> Reply **keep/drop per item** (or "all", "keep 1,2 drop 3"), and the event:
> **approve** / **request-changes** / **comment** / **don't post**.

Use `AskUserQuestion` for the event when you want the choice structured;
findings stay prose, because §11 allows up to 15 of them and the tool caps at
four options. Recommend an event — the verdict already is one — but do not
assume it.

**Post nothing until the user answers.** This is the only irreversible step in
the whole review, it lands on someone else's PR under the user's name, and
they are the one who has to live with the thread. A finding the user drops is
dropped: don't re-raise it in a softened form, don't append it as a PS.
"Don't post" is a complete answer — the terminal report already did the work.

Waiting is not optional and not conditional on how clean the result looks. An
Approve with zero findings still asks, because posting an approval is itself
the outward act.

### 13b. Post what they approved

The posted body is the kept findings plus the §11 report **minus** the
reviewer's own bookkeeping.
Drop `Environment`, `Rules read`, `Context`, the config sanity gate, and raw
command output. Keep, in this order:

1. The verdict line, with its one-clause reason.
2. `Critical` / `Improvement` / `Nit`, unchanged.
3. The `Claims` table.
4. The edge-case table from §6D — the passing rows are the tests the author
   should add, so they are the most useful thing in the comment.
5. One line of base-vs-head numbers, and any command whose result a finding
   rests on.
6. Anything cross-PR: merge-order conflicts, a sibling PR that owns the work.

**The posted body is a subset of the terminal report, never an expansion.** If
the comment is longer than what you printed, you added padding — cut back to
the subset.

Two budgets, because the tables are the useful part and a single cap squeezes
the wrong half:

- **Prose: 250 words.** Verdict line, findings, the closing numbers, the
  cross-PR note. A finding is three sentences — problem, trigger, fix — and a
  `file:line`; over that, you are re-explaining the diff to its author.
- **Tables: 12 rows total** across Claims and edge cases. Past that, keep the
  rows a finding rests on and the failing edge cases, and drop the rest.

Write it with a Bash heredoc into a temp file (this skill has no `Write`
tool), then post and confirm:

```bash
BODY=$(mktemp)
cat > "$BODY" <<'EOF'
<review body>
EOF
gh pr review $N --approve --body-file "$BODY"          # or --request-changes
gh pr view $N --json reviewDecision --jq .reviewDecision
```

The event is the user's answer from 13a, not the verdict: approve →
`--approve`, request-changes → `--request-changes`, comment → `--comment`.
**GitHub refuses the first two on your own PR** — check
`gh api user --jq .login` against `gh pr view $N --json author --jq
.author.login` and fall back to `--comment` when they match.

Quote the confirmation when you hand back, so the user sees the event landed:
`reviewDecision` for `--approve` / `--request-changes`. **Not for
`--comment`** — a COMMENTED review leaves `reviewDecision` at whatever it
already was, so quoting it there reports someone else's decision as yours;
quote the review URL `gh pr review` prints instead.

`gh pr review` posts a review event, not a PR description — it carries no
generated-with footer.
