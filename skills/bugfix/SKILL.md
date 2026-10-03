---
name: bugfix
description: Use when a tracker issue (Jira, Linear, GitHub Issues, or similar) describes a bug to fix and ship as a PR — invoked as /bugfix 1234 or /bugfix PROJ-1234.
argument-hint: "<issue key or number> [--codex] [--agy] [--boost]"
disable-model-invocation: true
allowed-tools: Bash, Read, Grep, Glob, Edit, Write, Agent, Skill, ToolSearch, AskUserQuestion
---

# Bugfix

Take one tracked bug from "reported" to "PR through CI and review":

1. Prove it still happens on the latest default branch.
2. Find the root cause, and get a second opinion on it.
3. Fix it with a test that fails before the fix and passes after.
4. Open the PR, through the repo's own PR skill if it has one.
5. Fix the CI failures the change caused.
6. Answer the review output (CodeRabbit, Claude, Copilot, or any other review tool), then stop.

**Target:** `$ARGUMENTS`. The first word is the issue: a full key (`PROJ-1234`, `#1234`) or a
bare number (`1234`). The rest are optional flags: `--agy` and `--boost` (§4), `--codex` (§5).

**Adapt to the repo.** This skill is a method, not a toolchain. Wherever it says "the repo's
test command", "the lint command" or "the config file", find the real one before you need it.
Look in `CLAUDE.md`, `CONTRIBUTING.md`, the README, `package.json` scripts, `Makefile` /
`justfile`, `pyproject.toml`, and the CI workflows (`.github/workflows/`). CI is the most
reliable source, because it is what actually runs. If a step has no equivalent in this repo,
skip it and say so in the report.

**Three rules govern the whole run:**

1. **No fix without a reproduction.** A bug you cannot make happen is a bug you cannot prove
   you fixed.
2. **Existing tests are read-only.** The new test is yours to write. Every test that was
   already there is the spec you are held to.
3. **Ask only where this skill says to.** Posting review replies (§8) always waits for the
   user's word. Otherwise you ask only at a stop-exit (§9), or at a judgment call this skill
   names: an ambiguous key prefix, or a contested or design-level review item. Everything else
   — opening the PR, pushing CI fixes — proceeds without asking.

**Done** means CI has finished on the PR **and** every review item, from a bot or an agentic
reviewer, has a verdict and was either fixed or answered. Then stop — not before, nothing after.

Copy this checklist into your first message and tick it as you go:

```text
- [ ] §1 issue read, key resolved, no duplicate PR
- [ ] §2 worktree on latest origin/<default>, env copied, services isolated, sanity gate passes
- [ ] §3 red test at base, failure signature recorded, red 3/3
- [ ] §4 root-cause statement, sibling sweep, second opinion back
- [ ] §5 green, revert check re-red with the same signature, green 3/3, CI suites clean, diff reviewed
- [ ] §6 PR open (ready, not draft)
- [ ] §7 CI finished; every red check fixed, pre-existing, or flaky
- [ ] §8 every review item answered; replies posted with the user's OK
- [ ] §9 final report
```

---

## 1. Read the issue

### Resolve the key

- **A full key** (`PROJ-1234`, `#1234`, a tracker URL) is used as given.
- **A bare number** needs a prefix. Infer it from what the repo already links to:

  ```bash
  { git log -200 --format=%s; git branch -r --format='%(refname:short)'; \
    gh pr list --state all --limit 50 --json title,headRefName --jq '.[] | .title, .headRefName'; } \
    | grep -oE '[A-Z][A-Z0-9]+-[0-9]+' | sed 's/-[0-9]*$//' | sort | uniq -c | sort -rn | head
  ```

  One prefix dominates → use it. None → the repo probably tracks bugs as GitHub issues, so
  try `#<number>`. Several in real use → ask which one (`AskUserQuestion`).

**Slug.** Keys like `#1234` are not valid in paths, branch names, or compose project names.
Derive one slug and use it everywhere this skill says `<slug>`:
`SLUG=$(printf '%s' "$KEY" | tr '[:upper:]' '[:lower:]' | tr -cs 'a-z0-9-' '-' | sed 's/^-*//;s/-*$//')`
gives `proj-1234` for `PROJ-1234` and `1234` for `#1234`.

### Fetch it

1. **A connected tracker.** `ToolSearch` for the tracker's issue-fetch tool (search "issue",
   "get issue", or the tracker's name). Load it and fetch the key.
2. **GitHub Issues.** `gh issue view <number> --comments`.
3. **Neither works.** Ask the user to paste the issue. Nothing pasted → stop-exit.

Write down, in your own words, before going further:

- **Expected vs actual behaviour.**
- **Reproduction recipe** — steps, inputs, the version the reporter runs.
- **Evidence** — stack trace, logs, screenshots, error IDs.
- **Acceptance criteria**, stated or implied.

A missing recipe is not a reason to guess. Building one is the first job of §3.

### Duplicate guard

```bash
gh pr list --state all --search "<KEY>" --json number,state,title,headRefName
git ls-remote --heads origin | cut -f2 | grep -iw -- "<slug>"
```

- **An open PR or a live branch for this issue** → stop-exit: someone may already be on it.
- **Unless it is this skill's own earlier run**: the branch is checked out in
  `$MAIN/.claude/worktrees/bugfix-<slug>`, and the PR's author is you (`gh api user --jq .login`).
  Then resume: reuse the worktree, `git -C "$WT" pull --ff-only` (never rebase), and start where
  the PR's state says — no PR: §5; CI red or pending: §7, counting earlier attempts toward the
  cap from `git log`; CI green: §8.
- **A merged PR** → read it. The bug may be a regression of that fix, which is the strongest
  lead you will get.

## 2. Isolate on the latest default branch

Never fix in the user's checkout, and never branch from their local `main`, which may be days
stale. The worktree, env copy, container isolation and sanity gate are all in
[references/environment.md](references/environment.md). Follow it now.

In short: a worktree at `$MAIN/.claude/worktrees/bugfix-<slug>`, branched from a fresh
`origin/<default>`; the gitignored config (`.env` and friends) copied in; dependencies
installed; services run in the repo's containers as a compose project of their own, not on bare
metal and never against the user's dev data. **Every path you touch starts with `$WT`.**

## 3. Prove the bug still happens

### Build the recipe if the issue lacks one

Agents fix bugs that come with a reproduction recipe several times more often than bugs that
don't. If the issue has no recipe, build one before writing any code:

1. Mine the issue for a stack trace, a log line, an input, a version.
2. Find the code that produces that error or that output.
3. Write the smallest input or script that drives execution there.

Still cannot trigger it → stop-exit. Ask for the missing piece: the input, the account state,
the exact version. Do not guess-fix.

### Reproduce at `origin/<default>`, as a test

Encode the recipe as an automated test, at the **lowest layer that shows the bug**: a unit test
if a function returns the wrong value, an integration test if the bug lives in the wiring.

**The test may use only what already exists at base.** It exercises the broken behaviour
through the existing interface. A test that imports a helper your fix will add can only fail
with an import error before the fix, and that proves nothing about the bug.

Run it with the repo's own test entry point (sanity gate first, per the environment
reference). It must fail. Then **record the failure signature** — the exception type and the
assertion message — and quote it:

```text
FAILED tests/billing/test_export.py::test_zero_quantity_line
ZeroDivisionError: division by zero   (billing/export.py:88)
```

**The signature must name the issue's symptom.** An `ImportError`, a fixture error, a syntax
error or a missing-file error is a broken test, not a reproduction. Fix the test until it fails
for the reason the issue describes.

Run it **3 times**. It must fail every time. A test that fails intermittently is reproducing a
race or a flake, and §5's gate cannot trust it.

### If it is a regression

When the issue names a version that worked, or a merged PR looks like the cause, find the
introducing commit: `git -C "$WT" bisect start origin/<default> <good-ref>`, then
`git -C "$WT" bisect run <script>` (exit 0 good, 1 bad, 125 skip), then `bisect reset`. Keep the
script outside the tree, or bisect checks it out from under itself. The commit goes in the
root-cause statement. Optional; worth it whenever a good ref exists.

### It does not reproduce

The test passes at `origin/<default>`. Do not fix anything. Find out which of two things is
true:

- **Already fixed.** Run the same test on the version the reporter runs. Fetch the tag, add a
  second worktree at `bugfix-<slug>-<tag>` the same way (env copy, install, sanity gate), and
  remove it when done. Red there and green on the default branch means a later commit fixed it. Find which one (`git log -S`, `git blame` on the guarding line, or bisect for the
  fixing commit). The answer is an upgrade or a backport, not a new fix.
- **Not reproduced.** Green on both means your recipe is not the reporter's. Ask for what is
  missing.

Either way it is a stop-exit, with the evidence.

## 4. Root cause, and a second opinion

### Localize, then explain

Narrow from file, to function, to line. Use the failing test as the probe, `git blame` and
`git log -L` on the guilty lines, and bisect if you ran it. Then keep asking **why** until the
answer is a line of code, not a symptom. "It divides by zero" is a symptom. "Quantity is
nullable since migration 0042, and the exporter was never updated" is a cause.

Write a **root-cause statement** — four lines, and the second opinion and the PR body both
reuse it:

1. **Mechanism** — what the code does wrong, at `file:line`.
2. **Origin** — the commit or change that introduced it, if known.
3. **Why the test fails** — how the mechanism produces the recorded signature.
4. **Fix location** — where the change belongs, and why there rather than where the symptom
   surfaces.

### Sibling sweep

The same mistake is often made more than once — copied code, a parallel handler, the same call
in another module. Grep for the pattern the root cause names (the call, the unguarded access,
the copied block). For each hit:

- **Same cause, in scope** → fix it in this PR, with a test.
- **Same pattern, different owner or risk** → list it in the PR body as a follow-up. Do not
  grow the PR.

### Second opinion: a fresh context that tries to break the diagnosis

A model re-reading its own reasoning does not catch its own mistakes. A fresh context holding
the evidence does. **Always** dispatch one `general-purpose` subagent (or the repo's own
reviewer agent if `.claude/agents/` defines one). It does not see this conversation, so the
prompt is self-contained:

> Read-only — do not modify anything. A bug is reproduced in the tree at `<$WT>`.
> **Issue:** <expected vs actual, one paragraph>. **Failing test:** `<path>`, which fails with
> `<signature>`. **Proposed root cause:** <the four-line statement>.
> Try to refute it. Is there a different cause that also explains the signature? Does the
> proposed fix location treat the cause, or just where the symptom surfaces? Are there other
> places with the same defect? Cite `file:line` for every claim.
> Lead with the verdict: **Agree** / **Disagree** / **Partly**. Then at most five findings, one
> line each. Under 300 words. No preamble, no restatement.

**Flagged reviewers** join in the same message, best-effort, never blocking. (`--codex` joins
at §5 instead: it reviews a diff, and there is none yet.)

| Flag | Runs | When it is missing |
|---|---|---|
| `--agy` | `agy-ask "<the same brief>"`, run from `$WT`. | Exit 127 (`AGY_UNAVAILABLE` or command not found) → skip silently. |
| `--boost` | `agy-ask --boost "<brief>"`. Implies `--agy`, and takes minutes, so run it in the background. | As `--agy`. |

For agy, `AGY_FAILED` (2), `AGY_QUOTA` (3) and `AGY_AUTH` (4) mean carry on without it, but **say
which one happened** in the report. Never retry them, and never report a failed review as a clean
one.

### When the opinions disagree

Do not average them, and do not side with the more confident one. A disagreement is a claim
about the code, so **settle it by running something**: a second test, a log line, a bisect. When
the evidence settles it, update the statement and move on. When it stays open, that is a
stop-exit. Ask the user, stating both sides with their evidence, before writing the fix.

## 5. Fix, behind the test gate

Make the **smallest change at the fix location** the statement names. Do not special-case the
test's inputs, do not refactor along the way, and do not "improve" neighbouring code. A passing
patch that changes more behaviour than the bug needed is the most common way a "fixed" bug is
still wrong.

### The gate

Run these in order. Quote each command and the decisive lines of its output; the PR body and
the final report use them.

1. **Green.** The new test passes with the fix.
2. **Commit the fix alone.** Stage only the source files the fix changed or added, and commit.
   Hooks run as usual; never `--no-verify`. **The test stays unstaged** until step 6:
   `revert --abort` resets the index, so a staged test file is deleted and a staged test edit
   is lost.
3. **Revert check.** Un-apply the fix with the test still in the tree, and watch the test fail
   again for the original reason:

   First, as its own Bash call — it must halt, not just warn:

   ```bash
   git -C "$WT" diff --cached --quiet || { echo "STOP: staged changes — unstage the test first"; exit 1; }
   ```

   Only when that exits 0:

   ```bash
   git -C "$WT" revert --no-commit HEAD       # also removes files the fix added
   # run the new test → must fail with the SAME signature recorded in §3
   git -C "$WT" revert --abort                # restores the fix; the unstaged test is untouched
   git -C "$WT" status --porcelain            # only the test changes remain
   ```

   A different failure — an import error, a missing file, a fixture error — **fails the gate**.
   It means the test is coupled to the fix rather than to the bug. Rewrite it against the
   existing interface and repeat from 1.
4. **Stable.** The new test passes 3 times in a row.
5. **The suites CI runs.** Lint, format, type check, and the tests for every area the fix
   touches, through the repo's own entry points. A failure that also happens at
   `origin/<default>` is pre-existing. Note it and move on.
6. **Commit the test** — stage the test files by name, nothing else. The fix-then-test pair,
   plus the quoted revert output, is the evidence the PR carries.

### Existing tests are read-only

Never edit, delete, skip, `xfail`, or loosen an existing test or assertion to get to green.

If the right fix makes an existing test fail, that test is stating a rule. Find out why it
exists (`git log -S '<test name>'`, then read the commit and any linked issue). Then look for a
narrower fix that satisfies both the issue and the test — often the fix belongs one layer up or
down. If there isn't one, the issue and the test disagree about how the system should behave.
That is the user's call, not yours: stop-exit, with the test, its origin, and both options.

### Fresh-context review of the diff

Before opening the PR, dispatch one more `general-purpose` subagent, read-only, with the diff
(`git -C "<$WT>" diff origin/<default>...HEAD`), the root-cause statement, and the acceptance
criteria. Ask only three things:

- Does the diff change behaviour beyond what the root cause requires?
- Does it touch anything unrelated?
- Does it miss an acceptance criterion?

Tell it to report only those, with `file:line`, under 200 words. A reviewer asked for findings
will invent some, so a style note is out of scope. A real finding goes back through the gate.

With `--codex`, run Codex's adversarial review of the same diff in the same message, if the
`openai-codex` plugin is ready (probe and command in
[references/ci-and-reviews.md](references/ci-and-reviews.md) §5). It challenges the approach:
whether the fix treats the root cause or the symptom. `no-codex` or `false` → skip silently.

### Red flags — stop and re-read this section

- "The old test was wrong anyway."
- "The revert check failed with an import error, but that's close enough."
- "It reproduces in spirit."
- "The fix is obvious, skip the revert check."
- "I'll `skip` the flaky one and mention it."
- "While I'm here, I'll tidy this up."

## 6. Open the PR

**Plant the shell first**, as its own Bash call. Commit hooks and any PR skill run bare `git`
against the shell's cwd. Stop if this prints anything but `$WT`:

```bash
cd "$WT" && git rev-parse --show-toplevel
```

### Use the repo's PR skill if it has one

Look for a skill or command whose purpose is **opening** a PR — not reviewing one:

```bash
grep -liE '(open(s|ing)?|creat(e|es|ing)) (a )?(pull request|PR)' \
  "$WT"/.claude/skills/*/SKILL.md "$WT"/.claude/commands/*.md 2>/dev/null
```

Also check the available-skills listing in your context: user and plugin skills do not live in
the repo. Read the candidate's description before using it.

- **Found** → invoke it with `Skill`. Give it the PR body material below as its arguments or
  context, and follow its gates. It may run its own checks or reviewers; that is its business.
  If the call is refused — a skill marked slash-only cannot be invoked by Claude — read its
  `SKILL.md` and follow its steps directly instead.
- **Not found** → do it directly:
  1. Commit the repo's way. The two commits from §5 are the minimum, and the repo may want
     them squashed or its own message format.
  2. Push with an explicit refspec — a worktree branch may track `origin/<default>`, and a bare
     `git push` would then no-op or target the wrong branch:

     ```bash
     BRANCH=$(git -C "$WT" branch --show-current)
     git -C "$WT" push -u origin "HEAD:refs/heads/$BRANCH"
     ```

  3. `gh pr create --base <default> --head "$BRANCH"`, filling
     `.github/pull_request_template.md` if the repo has one, row by row.

**Open it ready for review, not as a draft.** Some review bots skip draft PRs, which would leave
§8 with nothing to answer.

### The PR body

- **The issue link**, the way the repo links them — a closing keyword (`Fixes #123`) or the
  tracker key in the title or body.
- **Root cause** — the four-line statement, trimmed.
- **Reproduction** — the test, the red signature before the fix, and green after.
- **Revert check** — one line: reverted the fix, test failed with the same signature, restored.
- **Siblings** — fixed here, or listed as follow-ups.
- **Out of scope** — what you deliberately did not change, and pre-existing failures you saw.

No question to the user here. They chose to let the PR open without one.

## 7. Get CI green

Waiting for checks, classifying a red one, and the commands for each are in
[references/ci-and-reviews.md](references/ci-and-reviews.md) §1–§2. The rules:

- **Checks take time to appear.** Straight after a push, `gh pr checks` reports nothing.
  "No checks" is not green. Wait for checks to register (at most 3 minutes), then watch them to
  completion. Nothing ever registers → "CI did not start", a stop-exit, never a pass.
- **Classify every red check before touching it** as one of three:

  | Class | Means | Action |
  |---|---|---|
  | **pre-existing** | It is also red on the default branch's latest runs | Note it. Do not fix it here. |
  | **flaky** | It passes when the failed job is rerun once | Note it. One rerun, never more. |
  | **caused by the change** | Neither of the above | Fix it. |

- **At most 2 attempts per distinct failure.** An attempt that did not work is undone with
  `git revert` before the next one. Stacked guesses make the second attempt impossible to
  reason about. The cap is reached → stop-exit.
- **Fix the cause, in the code.** Never by skipping, loosening or deleting a test, never with
  `--no-verify`, never with a force-push. A fix to CI is still a fix: it goes through the §5
  gate when it changes behaviour.

## 8. Answer the reviews

### Know who is expected to review

Before reading anything, list who should review this PR. A reviewer that never ran must not
look like a clean review. Find them in
[references/ci-and-reviews.md](references/ci-and-reviews.md) §3: review-bot check runs,
workflows that run an AI review on `pull_request`, and bot config files in the repo.

After CI is green, wait **at most 10 minutes** for each expected reviewer to post on the
current head. Then each one is **reviewed** (it posted findings), **ran, no findings** (its check
completed, or it posted a summary saying so), or **did not run** (no check, no post). Never
report a reviewer that did not run as clean.

### Hand off to `pr-feedback` when it is installed

Check the available skills for `pr-feedback` (or `skills:pr-feedback`, when installed as a
plugin). If it is there:

1. **Plant the shell in `$WT`**, on the PR's head branch, as its own call (as in §6). That way
   pr-feedback sees "same branch" and works in place. It does not try to create a second
   worktree for a branch this one already has checked out.
2. Invoke it with `Skill`: `pr-feedback <PR number> --auto-triage`.

pr-feedback owns the rest: fetching every review source (inline threads, review bodies with
collapsed bot sections, sticky bot comments), verifying each claim, fixing, pushing, and
replying. `--auto-triage` takes the verdict's recommendation without a per-item question, and
still asks about unconfirmed, contested and design-level items. Its reply-posting gate is
unchanged — the one question every run asks.

### Otherwise, the inline fallback

Follow [references/ci-and-reviews.md](references/ci-and-reviews.md) §4. It is the same method
in short form: fetch all three sources, verify each claim before agreeing, fix the confirmed
ones with a test, push, draft short replies, **ask before posting**, and resolve only the
threads you fixed.

### One round

After the review round's push, wait for CI once more, as in §7. The bots will re-review that
push. **Their new findings are listed in the report, not worked.** One round per invocation;
the user runs `/pr-feedback` for the next. This is what keeps bot-on-bot loops from running
forever.

## 9. Done, and the report

### Stop-exits

Each of these ends the run early. Print the report with what you have, and say which exit fired
and what would unblock it:

| Exit | Fires when | Ask for |
|---|---|---|
| Issue unreachable | No tracker tool, no GitHub issue, nothing pasted | The issue text |
| Already in progress | An open PR or a live branch for this issue | Whether to take it over |
| No recipe | §3 cannot trigger the bug from what the issue gives | The missing input, state or version |
| Does not reproduce | Green at `origin/<default>` | Already fixed (with the commit), or what the reporter has that you don't |
| Environment won't run | Services or dependencies fail before any test runs | The setup step that is missing |
| Root cause contested | §4's opinions disagree and evidence does not settle it | Which diagnosis to fix, both stated |
| Fix contradicts a test | §5: the right fix breaks an existing test, and no narrower fix exists | Which rule wins |
| CI cap reached | 2 attempts on one failure did not clear it | A look at the failure |
| CI did not start | No checks registered on the PR | Why the workflows did not trigger |

### Clean up

Stop the containers you started for this worktree (see the environment reference). **Keep the
worktree.** The PR may need another review round, and it holds the branch. Print the command
that removes it when the PR merges:

```bash
git -C "$MAIN" worktree remove "$WT" && git -C "$MAIN" branch -D <branch>
```

### Final report

Match this shape. One line per row; detail lives in the PR, not here.

```text
Issue:        <key> — <one-line summary>
Reproduced:   <test path> at <base sha> — <signature> (red 3/3)
Root cause:   <one line> — second opinion: <Agree/Disagree/Partly> (subagent), <codex/agy verdicts or "not run">
Fix:          <files> — <one line>
Test gate:    green → revert re-red (same signature) → green 3/3
PR:           #<n> <url> — opened via <repo PR skill | gh>
CI:           <n> checks — fixed: <…> · pre-existing: <…> · flaky: <…>
Reviews:      <reviewer: n items> … — fixed <n> · answered <n> · contested <n> · did not run: <…>
New after re-review (not worked): <n, or none>
Status:       DONE | NOT DONE — <the stop-exit, or what is left>
```

**DONE** requires both halves of the definition at the top: CI finished, with every red check
fixed or classified as pre-existing or flaky, **and** every review item answered. Anything less
is **NOT DONE**, with the reason. Never round up.
