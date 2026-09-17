---
name: pr-feedback
description: Use when your own PR has review comments, change requests, CodeRabbit or other bot findings, or reviewer questions waiting on an answer, and you need to work through them and respond.
argument-hint: "[PR number, or nothing to use the current branch's PR]"
allowed-tools: Bash, Read, Grep, Glob, Edit, Write, Agent, Skill, ToolSearch, AskUserQuestion, mcp__linear-server__get_issue
---

# PR Feedback

Your PR got reviewed. Work the feedback: verify each claim, fix what survives,
reply to every thread. This is the counterpart to `/pr-review` — that one
reviews *someone else's* PR, this one answers *yours*.

**Target:** `$ARGUMENTS` — a PR number. If empty, resolve it from the current
branch (`gh pr view --json number -q .number`); if there is none, stop.

**Adapt to the repo.** This skill is a method, not a toolchain. Wherever it
says "the repo's test command", "the lint command", "the config file", find the
real one before you need it: `CLAUDE.md`, `CONTRIBUTING.md`, the README,
`package.json` scripts, `Makefile` / `justfile`, `pyproject.toml`, and the CI
workflows (`.github/workflows/`). CI is the most reliable source — it is what
actually runs. If a step has no equivalent in this repo, skip it and say so.

**Two rules that govern the whole run:**

1. **A reviewer's claim is a claim, not a fact.** You verify it the same way
   `/pr-review` verifies a PR description's claims. Performative agreement —
   "good catch!" then changing code that was already correct — is the failure
   mode this skill exists to prevent.
2. **Nothing outward happens without the user's word.** Fixes are yours to
   apply; replies land on someone else's thread under the user's name. Print,
   ask, then post.

---

## 1. Locate and position yourself

```bash
N=<PR number>
gh pr view $N --json number,title,author,headRefName,baseRefName,state,url
gh api user --jq .login
BASE=$(gh pr view $N --json baseRefName -q .baseRefName)   # used in §3, §4, §7
```

**Ownership gate.** If the PR's author is not the current user, stop: this is
the wrong skill. Point them at `/pr-review`. (Working someone else's feedback
under their name is not something to guess at.)

**Position.** Compare `headRefName` to the current branch.

- **Same branch** → work in place. Run `git status --porcelain`; if the tree is
  dirty, **say so before touching anything** — §8 stages only the files it
  means to, but the user should know unrelated WIP is sitting there.
- **Different branch** → make a worktree. Never switch the user's checkout.

```bash
MAIN="$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")"
HEAD_REF=$(gh pr view $N --json headRefName -q .headRefName)
WT="$MAIN/.claude/worktrees/$HEAD_REF"

[ -e "$WT" ] && echo "worktree exists — reuse it, and pull first"
git -C "$MAIN" fetch origin "$HEAD_REF"
git -C "$MAIN" worktree add "$WT" "$HEAD_REF"          # tracks the real branch, so you can push
```

A fresh worktree holds only tracked files and no installed dependencies. Copy
the gitignored local config the tests need (typically `.env` files) from
`$MAIN` to the same relative paths under `$WT`. To see what is ignored without
listing every dependency file:

```bash
git -C "$MAIN" ls-files --others --ignored --exclude-standard --directory | grep -i env
```

Then run the repo's install command in `$WT`.

**Never `gh pr checkout`** to get onto the branch — it switches the user's
checkout out from under them. The worktree above is the supported way. Nor
should you hand the judging to another skill: a Skill overlays the *current*
conversation, so it cannot give you the fresh context a claim needs. Use §4,
and where you need breadth, the fix agents in §6.

**Every absolute path passed to a file tool must start with `$WT`.** A path
beginning at the repo root silently edits the main checkout, and the fix never
lands on the branch. Run everything as `cd "$WT" && …` or `git -C "$WT" …`.

Pull before you start either way — the branch may have moved since you last
looked:

```bash
git -C "$WT" pull --ff-only
```

Do **not** rebase yet. Rebasing now rewrites the commits the review comments
are anchored to and marks half the threads outdated before you have read them.
If the branch needs a rebase, do it after §10, as a separate step.

### Know which database you are testing against

A worktree isolates files, not services. If the test suite talks to a local
database, find out which setting points it there (e.g. `DATABASE_URL`) and
which entry point actually loads that setting. A wrapper script (the one CI
runs) often loads env files that a bare `pytest` / `jest` / `go test` skips —
and a bare run then silently falls back to a default, often the user's own dev
database. **Use the repo's entry points, not bare tool invocations.**

Two consequences for §4 and §7:

- If you are on a shared dev database, a test asserting a table or queue is
  globally empty can fail on leftover dev data. That is not evidence the
  reviewer is right, nor that your fix broke something — check the merge base
  too.
- Never run an unmerged migration without first checking which database the
  migration tool will connect to. Migration tools often read the connection
  from the shell environment rather than the env file, so find the documented
  invocation (sourcing the env file first if that is what it needs).

## 2. Fetch every piece of feedback, grouped by thread

Three sources. Miss one and you leave a reviewer unanswered.

**Inline review threads** — via GraphQL, because REST gives you comments
without their thread state. Ask for `isResolved` and `isOutdated`, and for all
comments in the thread, so you can see replies you already made.

GraphQL variables are not auto-filled the way REST's `{owner}/{repo}` is, so
derive them once:

```bash
read -r OWNER REPO < <(gh repo view --json owner,name -q '"\(.owner.login) \(.name)"')

gh api graphql -f query='query($o:String!,$r:String!,$n:Int!){
  repository(owner:$o,name:$r){ pullRequest(number:$n){
    reviewThreads(first:100){ nodes{
      id isResolved isOutdated
      comments(first:50){ nodes{ databaseId author{login} path line originalLine body createdAt } }
    } } } }
}' -f o="$OWNER" -f r="$REPO" -F n=$N
```

Keep, per thread: the node `id` (`PRRT_…`, needed to resolve) and the **first
comment's** `databaseId` (needed to reply).

**Review bodies** — top-level review text not tied to a line:

```bash
gh api repos/{owner}/{repo}/pulls/$N/reviews --jq '.[] | select(.body != "") | "\(.user.login) [\(.state)]: \(.body)"'
```

**Issue comments** — plain PR comments:

```bash
gh api repos/{owner}/{repo}/issues/$N/comments --jq '.[] | "\(.user.login): \(.body)"'
```

### Know what the bots post, and where they hide it

Most repos have a few automated voices, and each has a fixed shape, so
filtering is mechanical once you've learned them. Look at a couple of recent
PRs to learn them if you haven't. The common shapes:

| Source | Where it lands | What to do |
|---|---|---|
| Issue-tracker mirror bot (e.g. `linear[bot]`) | issue comment | **Drop always.** Issue mirror, never feedback. |
| Bot walkthrough / summary (e.g. CodeRabbit's) | issue comment | **Drop.** Summary of the diff, not a finding. |
| Bot review body (e.g. CodeRabbit's `**Actionable comments posted: N**`) | review | **Read it** — see below. |
| Bot inline comments | review threads | Keep, verify, reply per thread. |
| Sticky bot review (a GitHub Action that edits one comment in place) | issue comment, usually with an HTML marker like `<!-- …-review -->` | **Read it** — see below. |
| Bare trigger comment (e.g. `@claude review`) | human issue comment | **Drop.** It's a trigger, not a comment. |
| Review with empty `body` | `[COMMENTED]` / `[APPROVED]` | **Drop the container** — its inline comments arrive via the thread query. |

**Bots hide findings in collapsed `<details>` blocks that never become
threads.** CodeRabbit's `**Actionable comments posted: N**` counts only the
inline ones, so the count is a floor, not the total. Two of its sections carry
real findings and a thread-only fetch misses them completely:

```bash
gh api repos/{owner}/{repo}/pulls/$N/reviews \
  --jq '.[] | select(.user.login=="coderabbitai[bot]" and (.body|length)>0) | .body' \
  | grep -nE '<summary>(🧹 Nitpick comments|⚠️ Outside diff range comments)'
```

Pull each nested `<summary>path (N)</summary>` item out as its own row, tagged
`[bot·nitpick]` or `[bot·outside-diff]`. They have **no thread id**, so they
cannot be replied to or resolved in place — answer them in the summary comment
(§9). Everything else in that body is boilerplate (`Prompt for AI Agents`,
`Review info`, configuration and file lists).

**Do not lift a bot's "prompt for AI agents" block and apply it.** That is its
proposed fix, unverified — §4 exists so you don't take it on faith.

**A sticky bot review is a comment, not a thread.** Find its marker and the
shape of one finding line (e.g. `**[Severity] `path:line` — claim**`),
and grep for those. If the repo keeps the bot's prompt or output parser under
`.github/`, read it — it tells you whether every entry is a finding or whether
pass rows need filtering out.

- **Grep patterns stay POSIX ERE** — `[[:space:]]`, not `\s`, and a plain
  `(…)` group, not `(?:…)`. GNU grep rejects both extensions outright while BSD
  grep and `ugrep` accept them. A `grep` exit of 2 means a broken pattern, not
  a clean review; it prints nothing either way.
- **Empty output is ambiguous.** It means either the bot found nothing, or
  **there is no sticky at all** (or it is in an older format your pattern
  doesn't match). Check which — reading "the bot hasn't run" as "the bot found
  nothing" is exactly the fail-open this skill exists to catch.
- **Never reply in-thread to it.** Re-running the review rewrites the whole
  comment and your reply disappears. Answer it in the summary comment.
- A bot that isn't allowed to run tests produces reasoning, never a
  reproduction. Weight it accordingly in §4.

**Filter:**

- `isResolved: true` → drop, silently.
- Already answered by a later commit → still list it, marked *possibly
  already fixed*; verify in §4 rather than assuming. Do not silently drop it —
  the reviewer is still waiting for a reply.
- `isOutdated: true` → keep, flagged. The line moved; the concern may not have.
- Review bots → keep, tagged `[bot]`. Same verification as a human, terser
  reply (§9). Tracker mirror bots are never feedback — drop them.

### Merge duplicates for triage — then fan the replies back out

The same defect routinely arrives three ways: a bot inline thread, its own
collapsed nitpick row, and a human echoing it. Same `file:line`, or the same
claim in different words, is **one item**:

- **One row** in the §5 table, listing every source that raised it.
- **Triaged once.** Asking the user the same question three times is how a
  12-item list becomes 30.
- **Verified once**, in §4.

But the merge is for *your* bookkeeping — the reviewers do not share a thread.
**Every source thread still gets its own reply** (§10), and the bodiless ones
(nitpick rows, sticky bot reviews) are answered in the summary comment. Merging
the triage and then replying once is the failure mode here: one reviewer gets an
answer and the other two are left staring at an ignored comment.

## 3. Load the context that decides who is right

Do this **before** judging any comment. You cannot tell whether a reviewer is
correct without knowing what the change was supposed to do.

- **The linked issue.** Find it from a closing keyword in the PR body
  (`Fixes #123`) or a tracker key (`PROJ-123`) in the body, title, or branch
  name. Tracker key → `ToolSearch("select:mcp__linear-server__get_issue")` and
  `get_issue` (for another tracker, find its MCP server's issue-fetch tool and
  add it to `allowed-tools` in this file's frontmatter). GitHub issue →
  `gh issue view <number>`. A reviewer asking for something the issue
  explicitly excluded is a *scope* conversation, not a fix.
- **The rules.** `CLAUDE.md` (and nested ones in touched directories), plus
  every `.claude/rules/*.md` whose paths match a file in the diff — they load
  on file open, and reading a diff opens nothing. Open them under `$WT`. A
  reviewer's suggestion that violates a rule is a finding *against the
  reviewer*, and you need the rule text to say so kindly.
- **The spec.** The feature's design doc, when the repo keeps one.
- **The diff itself**, in full: `git -C "$WT" diff "origin/$BASE...HEAD"`.

## 4. Verify every comment as a claim

For each item, assign exactly one verdict. This is the heart of the skill.

| Verdict | Means | Bar |
|---|---|---|
| **Confirmed** | The reviewer is right | You can cite the `file:line` that makes it true, or you reproduced it |
| **Confirmed-partly** | Real problem, wrong proposed fix | Cite both: the defect, and why their fix doesn't hold |
| **Unconfirmed** | Can't tell from here | Name exactly what would settle it |
| **Contradicted** | The reviewer is wrong | Cite the `file:line`, rule, or test run that shows it |
| **Preference** | No correctness content | Style, naming, structure — a judgment call, not a defect |
| **Contested** | Two reviewers disagree, or one contradicts their own earlier round | Verify *each side* and carry both evidences — **you do not pick** (§5) |

Rules for getting there:

- **Try to reproduce before you agree.** "This breaks when X" → write a
  throwaway test in `$WT` with X's literal values and run it. Passes → the
  claim is Contradicted, and the passing test is the evidence you quote back.
  Fails → Confirmed, and you have the regression test to add. Delete throwaway
  tests; keep the ones that belong in the suite.
- **Baseline before you blame.** If a claimed failure also fails at the merge
  base, it is pre-existing, not this PR's. Run it both ways before calling it
  Confirmed.
- **Check the reviewer read the current code.** On an `isOutdated` thread, the
  code may already have changed. Re-read the line as it stands now.
- **A bot's confidence is not evidence.** Review bots state everything in the
  same assured tone. Verify identically; their hit rate is mixed.
- **Suspected false positive:** a reviewer — often a bot working from a stale
  model of the repo — claiming your diff broke a table, column, or module.
  Check the models or schema for each name in the claim. If it doesn't exist,
  Contradicted — reply with the fact, kindly. **Verify before you dismiss,
  though:** a name that sits next to a stale one in the same claim is often
  real. Dismissing a real finding as a known false positive is the worse error
  of the two.
- **Known half-truth:** `except A, B:` flagged as a syntax error. It is valid
  PEP 758 on Python 3.14, so the *severity* is wrong — but if the repo uses
  `ruff format`, adding an `as _` clause keeps the parentheses. That makes it
  **Confirmed-partly**, not Contradicted: correct the claim, make the change.
- **Don't inflate Preference into Confirmed** to be agreeable, and don't deflate
  Confirmed into Preference to avoid work. Both are the same failure.
- **A contradiction is never yours to settle quietly.** Two reviewers asking for
  opposite things, a bot contradicting a human, or a reviewer reversing their
  own earlier round — verify both sides and mark it **Contested**. Picking one
  silently means telling the other their review was ignored, which is a
  relationship call, not a technical one. It goes to the user at §5.

## 5. Print the table, then triage with the user

Print this to the terminal first — it is free, and it is what the user triages
from. Number every item continuously.

```text
#  source            file:line                verdict            claim (one line)         proposed action
1  @alice            src/billing/invoice.py:44  Confirmed        guard misses None        fix: add the None branch
2  coderabbitai[bot] src/billing/invoice.py:91  Contradicted     "fails on empty set"     skip: test at §4 passes
```

Then ask. **Use `AskUserQuestion`** — one question per item, options
**Fix** / **Skip** / **Discuss**. The §4 verdict picks the recommended one, and
it goes **first in the option list** with `(Recommended)` in its label. The
tool caps at 4 questions per call and 4 options each, so batch four items per
call and keep going.

**More than 8 items** → ask one framing question first, to avoid ten rounds of
prompts:

> Triage all 12 one by one, or take the recommendation (fix the 5 Confirmed,
> skip the rest) and only discuss the exceptions?

Resolve every **Discuss** item before you fix anything. A Skip is final: don't
fix it anyway "since it was quick", and don't re-raise it in the reply.

**Two item types are never a plain Fix option:**

- **Contested** (§4). Present both sides with their evidence and ask which one
  to follow. State the cost of each. Do not recommend the reviewer with more
  seniority — recommend the one with better evidence, and say which is which.
- **A change that is a design decision.** If honouring the comment would change
  a subsystem's shape, add a pipeline stage, swap a data model or library, or
  move a tenancy or concurrency boundary, it deserves a recorded decision (an
  ADR, if the repo keeps them) before the code. A reviewer asking for it does
  not shortcut that — their request is the *trigger* for the decision, not the
  decision. Give it its own `AskUserQuestion`: **implement + draft the design
  record** / **reply and defer it to a follow-up** / **skip**. Never just build
  it because a reviewer asked.

**When an item is both**, run them in order: settle **Contested** first, then —
if the side that won is a design change — apply the design gate to it. Two
questions in sequence, never one merged question; "which reviewer, and should we
do it at all" is unanswerable as a single choice.

The rule underneath both: **you do not make decisions here, you surface them.**
When you cannot tell which way to go, that is an `AskUserQuestion`, not a
judgment call — it is the user's PR, their reviewers, and their architecture.

## 6. Apply the fixes

- Different files → dispatch one agent each (the repo's own implementation
  agent if `.claude/agents/` defines one, otherwise `general-purpose`), in a
  single message, pinned to its files. Concurrent editors must never share a
  file. Tell each one the tree is at `$WT` and every path it touches must start
  with it.
  **Do not stall after dispatching.** Agent results come back as ordinary tool
  outputs, not as prompts — when they return, continue to §7 in the same turn.
  A long agent report looks like a natural stopping point and is not one.
  Give each one this report shape, or you get paragraphs you have to re-read:

  > Report what you changed: `` `file:line` `` + one sentence each. No preamble,
  > no restatement of the comment, no closing summary. Quote any command you ran
  > and its output verbatim — exact error strings, test counts, numbers. Never
  > drop a negation. If you did not make a change, say which and why in one line.
- Same file or overlapping lines → apply sequentially yourself.
- **Fix the defect, not the sentence.** A reviewer's suggested patch is a
  suggestion. If the real fix is elsewhere or larger, do that and say so in the
  reply — that is more useful to them than a literal application.
- Keep each fix scoped to its comment. A review is not an invitation to
  refactor; unrelated changes make the reviewer re-review everything.
- A Confirmed bug that had no test now gets one, built from the §4 reproduction.

## 7. Run the checks the changes trigger

From `$WT`, using the commands CI runs, and **report the real output, not the
claim that it passed**:

- Behavior changed in a tested area → the relevant tests
- Inputs to code generation changed (API schema, models, config definitions) →
  the repo's codegen or staleness check
- Models or schema changed → the migration exists; no shipped migration edited
- Any `.md` changed → the docs/markdown lint, if CI has a job for it — local
  commit hooks often don't run it
- Lint, format check, type check

A test that fails identically at the merge base is pre-existing; say so and move
on. A flake that passes on rerun is a flake — note it, don't chase it.

## 8. Commit and push, then draft replies

**If you are in a worktree, plant the shell there first.** Commit hooks and any
commit skill run bare `git` and test commands against the shell's cwd — they
cannot see your `git -C "$WT"` discipline, and the cwd resets between calls.
Run this as its **own** Bash call and stop if it prints anything but `$WT`:

```bash
cd "$WT" && git rev-parse --show-toplevel
```

Then commit the way the repo commits: if it has a commit skill or script that
runs lint, format, typecheck, and tests, use it; otherwise run those checks
yourself, stage **only** the files you changed (by name, never `git add -A`),
and commit. If a check fails, fix and re-run — never bypass hooks with
`--no-verify`.

Confirm it landed where you meant:

```bash
git -C "$WT" log -1 --oneline          # the fix commit, on the PR branch
git -C "$MAIN" status --porcelain      # main checkout untouched
```

**Push with an explicit refspec.** A worktree branch often tracks
`origin/main` rather than itself, so a bare `git push` either silently no-ops —
nothing reaches the PR branch — or targets `main`. Name the branch:

```bash
BRANCH=$(git -C "$WT" branch --show-current)
git -C "$WT" push origin "HEAD:refs/heads/$BRANCH"
```

A fix commit on top of the pulled branch fast-forwards. If the push is
rejected, someone else pushed in the meantime — pull, re-verify, and push
again. Never force.

Capture the sha the replies will cite, and confirm the remote actually moved:

```bash
SHA=$(git -C "$WT" rev-parse --short HEAD)
git -C "$WT" fetch origin "$BRANCH"
git -C "$WT" rev-parse HEAD "origin/$BRANCH"    # must match; if not, the push did not land
```

Commit *before* replying. A reply saying "fixed in abc1234" that points at
nothing is worse than no reply.

## 9. Write the replies

**Short, warm, specific, done.** Each reply is **at most two sentences** and
leads with the outcome. That cap is the whole style; everything below is how to
spend it.

**Fixed:**

> Fixed in `abc1234` — the guard now short-circuits on `None` before the
> lookup.

**Fixed differently than suggested:**

> Fixed in `abc1234`, though one layer up: `save_orders` was the one
> dropping the row, so the dedup check moved there instead.

**Confirmed-partly — right that something should change, wrong about why:**

> Fixed in `abc1234` — not a syntax error (valid PEP 758 on 3.14), but added
> `as _` so `ruff format` keeps the parentheses.

**Skipped — the reviewer is wrong:**

> Checked this one — the API client already scopes by `tenant_id` upstream, so
> the extra filter would be a no-op here. Happy to add it defensively if you'd
> rather have it stated at the call site.

**Skipped — a real point, deliberately not doing it:**

> Good point, but the `CLAUDE.md` rule that `order_id` is the durable key
> means changing it here would break the dedup guard. Leaving it — shout if you
> disagree.

**Skipped — scope:**

> Agreed this is worth doing, but it's outside PROJ-1234; filed for a follow-up
> rather than growing this PR.

**Rules:**

- Lead with the outcome word: *Fixed* / *Checked* / *Agreed* / *Good point*.
- Every skip ends with one clause handing the call back — "happy to change it",
  "shout if you disagree". It makes it a decision, not a dismissal.
- Every disagreement carries its evidence: the rule name, the test you ran, the
  `file:line`. Disagreeing without evidence is what makes a thread go long.
- **Thank once per reviewer**, in the summary comment, never per thread. Ten
  "thanks!"s read as filler.
- **Never restate their comment back to them.** They wrote it.
- **Bots get one line, no thanks, no warmth:** `Fixed in abc1234.` /
  `Not applicable — valid PEP 758 syntax on 3.14.`
- No emoji unless the reviewer used them first. No sign-off. No apology. No
  "great catch, I should have seen that".

**Summary comment**, one per run, posted as a PR comment. It is also the only
place to answer feedback that has no thread: bots' collapsed nitpick and
outside-diff items, and sticky bot review entries.

**It is exactly three lines, and each line has a job:**

1. Thanks, named, plus the sha.
2. What you fixed — **named, not explained.** The thing, not how it works.
3. What you left, and where the reasoning is. Omit if you fixed everything.

> Thanks @alice — pushed `abc1234`. Fixed 4 of the 6 (None guard, dedup,
> the missing tenant scope, and a test for the empty-set case). Left two,
> with reasoning in the threads.

**Mechanism belongs in the commit message, not here.** Fixtures, assertions,
which connection a query runs on, what the test does when you revert the fix —
the reviewer can read the commit, and will if they care. A summary that recites
the implementation is a commit message pasted into a comment.

Compare, on a one-item run — same information reachable either way:

> **Yes.** Thanks @alice — pushed `abc1234`. Added the missing
> multi-currency coverage on the batch path; it fails at `def5678`.

> **No.** Thanks @alice — pushed `abc1234`. Added the batch-path
> multi-currency test: a parent/child invoice fixture (the existing
> `batch_account` seeds flat invoices, no line items) plus one test that runs
> the batch worker twice — lines agree → `EUR` on the invoice and in the
> summary view, one line flips to `USD` → cleared from both, with the lines
> still attached and still in the export.

The second makes the reviewer read 80 words to learn what the first says in 20,
and every detail in it is already in the commit message.

### Gate: print all drafts, then ask

Print every reply next to its thread, then one `AskUserQuestion`:
**post all** / **edit first** / **don't post**.

Ask about the follow-up actions in the same call — they are outward too, so
they are offers, never automatic:

- **Re-request review** from any human who left `CHANGES_REQUESTED`.
- **Re-trigger the review bot**, if the repo's bot supports a re-run trigger.

**Post nothing until the user answers.** This is the only irreversible step in
the run, it lands under their name, and they are the one who has to live with
the thread. "Don't post" is a complete answer — the fixes are already pushed
and the terminal output already did the work.

## 10. Post, and resolve only what you fixed

```bash
# reply in-thread (use the FIRST comment's databaseId)
gh api repos/{owner}/{repo}/pulls/$N/comments/<comment_id>/replies -f body="$BODY"

# summary comment
gh api repos/{owner}/{repo}/issues/$N/comments -f body="$SUMMARY"
```

**Before you post, check the fan-out.** For every merged item from §2, count the
source threads and confirm you have one reply per thread — not one reply for the
item. A merged item with three sources needs three replies.

**Resolve the threads you fixed. Leave the threads you skipped open.**

```bash
gh api graphql -f query='mutation($t:ID!){ resolveReviewThread(input:{threadId:$t}){ thread{ id isResolved } } }' -f t=<PRRT_…>
```

A skipped thread stays open on purpose: the reviewer raised it, they get to
decide whether your answer settles it. Resolving your own disagreement closes a
conversation the other person is still in.

Verify nothing was missed, and report the count — re-run the §2 thread query
with this filter:

```bash
gh api graphql -f query='…' -f o="$OWNER" -f r="$REPO" -F n=$N \
  --jq '[.data.repository.pullRequest.reviewThreads.nodes[] | select(.isResolved==false)] | length'
```

### Follow-up actions, only if the user approved them at §9

**Re-request review from a human who blocked.** A `CHANGES_REQUESTED` review
keeps blocking until that person reviews again — pushing a fix does not clear
it:

```bash
gh pr view $N --json reviews -q '[.reviews[] | select(.state=="CHANGES_REQUESTED") | .author.login] | unique[]'
gh pr edit $N --add-reviewer <login>
```

**Re-trigger the review bot** the way it is designed to be re-triggered. If a
sticky review exposes a re-run checkbox, tick it rather than posting another
trigger comment, which just piles up a second trigger against the same state —
and tick it only when it is currently unticked; `[x]` means a re-run is already
queued. For example, for a sticky whose body carries `- [ ] Re-run review`:

```bash
sticky_id=$(gh api "repos/{owner}/{repo}/issues/$N/comments" \
  --jq '.[] | select(.body|contains("<!-- review-bot -->")) | .id' | head -1)   # replace with your bot's marker
if [ -n "$sticky_id" ]; then
  body=$(gh api "repos/{owner}/{repo}/issues/comments/$sticky_id" --jq '.body')
  if printf '%s' "$body" | grep -qF -- '- [ ] Re-run review'; then
    gh api "repos/{owner}/{repo}/issues/comments/$sticky_id" -X PATCH \
      -f body="$(printf '%s' "$body" | sed 's/- \[ \] Re-run review/- [x] Re-run review/')"
  else
    echo "re-run already pending"
  fi
fi
```

Then confirm in the terminal: replies posted, threads resolved, threads left
open by design, follow-up actions taken, and — if you used one — that the
worktree still exists and the user's checkout was never touched.

**Say what happens next**, in one line: the push re-triggers CI and any review
bots, so new feedback is likely within a few minutes. Do **not** poll for it or
loop — one cycle per invocation. The user re-invokes `/pr-feedback $N` for the
next round.

## Output discipline

**Three channels, three rules.** Each names the section that governs it:

| Channel | Shape |
|---|---|
| Subagent → you (§6) | Compressed. The report shape in §6 is the contract. |
| You → terminal (§5 table, printed drafts) | Concise. Tables over prose; no narration of what you are about to do. |
| You → GitHub (§9, §10) | **Human-facing.** §9's two-sentence cap and its warmth rules govern it. Terse-register compression reads as cold on a colleague's review thread — which is the opposite of the job here. |

Four things never compress, in any channel:

- **Verbatim:** `file:line`, commands, exact error strings, test counts, the
  commit sha, numbers and units. A paraphrased traceback is not evidence.
- **Negations:** `not` / `never` / `no` / `only` / `except`. "does **not** scope
  to the tenant" shortened to "scopes to the tenant" inverts the finding.
- **One word, one meaning.** `Confirmed` / `Confirmed-partly` / `Unconfirmed` /
  `Contradicted` / `Preference` / `Contested` are the verdict vocabulary — never
  a synonym, anywhere.
- **Full sentences resume** for a security finding, at the §5 and §9 gates, and
  inside any `AskUserQuestion`. That is where ambiguity costs a wrong decision
  or an irreversible post.

## Do not

- **Agree without verifying.** The single most damaging thing this skill can do
  is change correct code because a reviewer sounded sure.
- **Argue at length.** Two sentences and evidence. If it needs more, it needs a
  call, not a comment thread.
- **Fix something the user said to skip**, or soften it into a partial fix.
- **Relitigate a thread already settled** in an earlier round.
- **Rebase or force-push mid-run** — it detaches every comment from its lines.
- **Leave a reviewer unanswered.** Every unresolved thread gets a reply, even
  the ones you skip.
- **Resolve a thread you disagreed with.**
- **Post anything before the §9 gate.**

## Red flags — stop

| Thought | Reality |
|---|---|
| "Reviewer's senior, just make the change" | Seniority isn't evidence. Cite the `file:line` or reproduce it. |
| "It's a small change, skip the test run" | Small changes break CI the same as large ones. §7. |
| "I'll resolve it to keep the PR tidy" | Tidy PR, closed conversation. Skipped threads stay open. |
| "The bot found it, so it's real" | Bots are confident about everything. Verify. |
| "Let me explain my reasoning properly" | Two sentences. The long version is a call. |
| "They'll obviously want this posted" | They said what they wanted at §5 and §9. Ask. |
| "This one's clearly fine to fix too" | A Skip is final. |
| "Reviewers disagree, I'll take the sensible one" | Contested. Both sides, with evidence, to the user. |
| "They asked for it, so it's decided" | A request is a trigger, not a design record. Ask. |
| "Same bug three times, one reply covers it" | One reply per thread. Merge triage, never replies. |
