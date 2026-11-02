---
name: pr-upsert
description: Take the current branch to a shippable GitHub PR in one flow — rebase, parallel self-review (two read-only reviewer agents, plus Codex and agy adversarial reviews when available), triage with the user, fixes, docs check, commit and push, create or reconcile the PR from the repo's template with its issues linked, request reviews from authors of overlapping work, sync the tracker, watch CI, work review-bot comments, and request an AI review. Works for new PRs and updates. Slash command only (/pr-upsert).
argument-hint: "[base branch, PR title or context hint]"
disable-model-invocation: true
allowed-tools: Bash, Read, Grep, Glob, Edit, Write, Agent, Skill, ToolSearch, AskUserQuestion
---

# pr-upsert — create or update a PR

rebase → parallel self-review → triage with the user → fix → docs check → (image build, local
check) → commit and push → create or reconcile the PR → overlap reviewers → tracker sync → CI
watch → review-bot feedback → AI review.

It orchestrates other skills: `rebase` and `commit` (required, installed next to this one) and
`pr-feedback` (optional). Invoke them with the `Skill` tool by name — `rebase`, `commit`,
`pr-feedback`, or `skills:rebase` etc. when installed as the plugin. It needs `gh`, logged in.

Design rules:

- **Fresh-context review.** Reviewers are **subagents**, never `Skill(...)` calls: a skill
  injects its instructions into this conversation, and two at once overlay competing
  instructions and stall the flow.
- **Reviewers must not edit.** They hold no Edit/Write tool, but `Bash` is a shell, so the tree
  is re-checked after they return.
- **The user triages.** Every finding gets a source tag and a fix/skip recommendation; nothing
  is applied until the user answers.
- **No gate on the PR description.** The body is generated from the template and posted; the
  user sees it afterwards.
- **Never claim what was not run.** A skipped check says "not run" and why. A failed review is
  never reported as a clean one.
- **One watch cycle per invocation.** Never loop fix → review → fix automatically.
- **Best-effort extras** (Codex, agy, tracker sync, overlap reviewers) never block the flow.

`REBASE_SCRIPTS` is `${CLAUDE_SKILL_DIR}/../rebase/scripts` and `COMMIT_SCRIPTS` is
`${CLAUDE_SKILL_DIR}/../commit/scripts` (absolute paths; for a copy install,
`~/.claude/skills/<name>/scripts`). `REFS` is `${CLAUDE_SKILL_DIR}/references`.

## Step 0: Mode, context, base, facts

```bash
bash "REBASE_SCRIPTS/git-context.sh"
```

`CONTEXT_FAILED` or `gh=no` → stop and report. Note `branch`, `push_remote` (`ORIGIN`),
`base_remote` (`REMOTE`), `default_branch` (`DEFAULT`) and `base_repo` (`BASE_REPO`; when empty,
read it with `gh repo view --json nameWithOwner -q .nameWithOwner` and confirm it with the user).
Refuse a detached HEAD or `branch == DEFAULT`. Then `git fetch --prune REMOTE` (and `ORIGIN`
when different), so every `REMOTE/BASE` below exists and is current.

**Every `gh` call targets `BASE_REPO`**: `--repo BASE_REPO` on `gh pr` / `gh issue` / `gh repo`
commands, `repos/BASE_REPO/…` in `gh api` paths. In a fork checkout `gh`'s own default may be
the fork, or unset. Find this branch's PR:

```bash
gh pr list --repo BASE_REPO --head "BRANCH" --state open \
  --json number,title,body,baseRefName,state,url,headRepositoryOwner \
  -q '.[] | {number, title, body, baseRefName, state, url, owner: .headRepositoryOwner.login}'
```

Keep the PR whose `owner` is the owner of `ORIGIN`'s repository (in a plain checkout, the same
as `BASE_REPO`'s owner); several or none match → create mode only when none match, otherwise
ask.

- An open PR from this branch → **update mode** (keep number, title, body, URL).
- Otherwise → **create mode**.

**Resolve the base once** as `BASE` and reuse it everywhere: update mode → the PR's
`baseRefName`; create mode → a branch named in `$ARGUMENTS` if it exists on `REMOTE`, else
`DEFAULT`. Never re-derive it later.

Read `.claude/project-facts.md`. This skill uses `## pr` (and, through `commit`, `## areas`,
`## checks`, `## generated`). Missing file or section → follow
`${CLAUDE_SKILL_DIR}/../rebase/references/project-facts.md` once, now, so no later step guesses.

## Step 1: Issues

If the facts say `issues required: no`, never ask for an issue: link only a key that the branch
name or `$ARGUMENTS` names and that validates (sub-step 3), else leave `ISSUES` empty; go to
Step 2.

Otherwise every **product-facing** PR links at least one issue; **housekeeping** (the facts'
list; anything changing product behaviour is not housekeeping) is exempt.

1. Candidates are the **union** of: the branch name (`abc-123-…` → `ABC-123`, `123-…` or
   `issue-123` → `#123`, per the facts' key format), `$ARGUMENTS`, issue references in the
   current body (update mode), and commit subjects (`git log --format=%s "REMOTE/BASE"..HEAD`).
   Commit-derived ones may be stale until Step 2's rebase; re-confirm them afterwards.
2. No candidates and the change is clearly housekeeping → `ISSUES` empty; tell the user (they
   can override); go to Step 2.
3. Validate each candidate:
   - a tracker MCP server is connected → load its tools by searching
     (`ToolSearch("+<tracker> get issue")`, plus update/attach tools for Step 10); fetch each;
   - else, with GitHub Issues → `gh issue view <n> --repo BASE_REPO --json number,title,state`;
   - else the keys cannot be checked → show them and get explicit confirmation.
   Exclude terminal issues (Done, Canceled, Duplicate, closed): surface them and ask for a
   replacement or the housekeeping call.
4. For each, `Fixes <KEY>` when this PR completes it, `Part of <KEY>` when it contributes (or the
   facts' link words).
5. No usable issue for a product-facing change → stop and ask which issue(s) it addresses; offer
   to search by title or to create one. Never continue without one.

Record `ISSUES` (key + relationship); Steps 9 and 10 use it.

## Step 2: Rebase

Invoke the `rebase` skill with `BASE` as its argument (without it, create mode would fall back to
`DEFAULT` and diverge from `BASE`). If it lands on another base (the target was deleted), update
`BASE`. Conflicts or failed checks → stop and surface them; review nothing.

Afterwards, re-run the commit-subject scan and drop from `ISSUES` any candidate that came only
from commits and no longer appears (it came from already-merged work); tell the user.

## Step 3: Self-review, in parallel

All reviewers read the **same** change set: committed on the branch + uncommitted + untracked.
Prompts, report format, fallbacks and failure handling are in `REFS/reviewers.md` — read it now.

1. Before the dispatch message: the Codex probe (one Bash call), `command -v agy-ask` (if agy is
   there, write its brief to a file outside the repo), and the **baseline** of the tree, saved
   outside the repo:

   ```bash
   { git status --porcelain; git diff HEAD | git hash-object --stdin; } > <scratch>/pre-review.txt
   ```
2. **One message** with: `Agent` A (`pr-self-reviewer`), `Agent` B (`pr-architect`), the Codex
   Bash call when the probe said `true`, and the agy Bash call when `agy-ask` exists. Never use
   `Skill(...)` for review.
3. When they return, **check the tree was left alone** — compare with the baseline (uncommitted
   work from before the review is expected; a change to it is not):

   ```bash
   { git status --porcelain; git diff HEAD | git hash-object --stdin; } | diff <scratch>/pre-review.txt - && echo TREE_UNCHANGED
   ```

   Any difference → stop and surface it (`git status`, `git diff --stat HEAD`).
4. **Do not end the turn here.** Merge and de-duplicate the findings, tagged by source
   (`reviewer`, `architect`, `Codex adversarial`, `agy adversarial`, or the combination). The
   same `file:line` from several reviewers is one entry, listed first — agreement is the strongest
   signal. Design challenges without a line stay their own entries. Say which reviewers did not
   run and why (fallback agent, Codex failed, `AGY_FAILED` / `AGY_QUOTA` / `AGY_AUTH`).

## Step 4: Triage with the user

One numbered list; each item: `file:line` (or "design"), a one-line summary, the source tag, and
your recommendation (fix / skip + reason). Check every cited line before you list it. Then:
"Reply with fix/skip per item, or shortcuts like 'fix all', 'fix 1,2 skip 3'." Apply nothing
until the user answers. Skipped items go into the PR body's "Where a reviewer should look
hardest".

## Step 5: Apply fixes

Every "fix" item: non-overlapping files → parallel `Agent` subagents (one per file or group);
same file or overlapping lines → sequentially, yourself.

## Step 6: Docs

The change set is committed (`git diff "REMOTE/BASE...HEAD" --stat`) plus uncommitted
(`git diff HEAD --stat`) plus untracked. If it touches an area in the facts' docs table, review
and update those docs in the **same** change. With no table, still check the obvious: new
scripts, env vars, endpoints, dependencies, setup steps, CI changes → the README or the doc that
covers them. Code is the source of truth; a stale doc lies confidently. Propose each doc edit and
get the user's go-ahead before writing it.

## Step 7: Image build (only when triggered)

When the change set touches the facts' `container build triggers`, build each affected image
with the command given there. A failed build → **stop** before committing. `none` or no match →
skip silently.

## Step 7b: Local check (when it tells you something)

When the facts name a local environment, run **this branch** in it and try the path the change
touches end to end. Make sure it really runs this branch (rebuild, restart, wait until ready).
Never run an option that deletes local data without asking. Record what you ran and what
happened for the template's manual-check row. Skip it for docs, comments, tests only, CI or
skill files, or when no environment is configured, and say why in one line. If the environment
cannot come up, say so; never report the change as tested.

## Step 8: Commit and push

Invoke the `commit` skill. It runs the checks the change needs, commits, pushes with a pinned
lease, and lists overlapping branches. It stops on a failure → fix and re-run; never bypass a
check.

## Step 9: Create or update the PR

**The template:** the repo's own (`.github/pull_request_template.md`, or
`.github/PULL_REQUEST_TEMPLATE.md`, `docs/…`, the root, or one file under
`.github/PULL_REQUEST_TEMPLATE/` — ask which if there are several); with none, the neutral
`REFS/pull_request_template.md`. Fill it by the rules in `REFS/pr-body.md` — read it now: summary
for a zero-context reader, the flow diagram for process changes, config changes from the diff,
the verification section with only what this run executed, the issues with exact link words.
Incorporate a hint from `$ARGUMENTS`. Title ≤ 70 characters. No AI attribution anywhere.

**Create mode** — post directly, no approval gate. Head is `ORIGIN`'s branch; in a fork checkout
(`ORIGIN` ≠ `REMOTE`) pass `--head <fork owner>:<branch>` and `--repo` the upstream:

```bash
gh pr create --repo BASE_REPO --base "BASE" --title "<title>" --body-file <body file>
```

**Update mode** — reconcile the body to the current diff (`REFS/pr-body.md`, "Update mode"), keep
every existing image, then `gh pr edit NUMBER --repo BASE_REPO --body-file <body file>`; update the title too if
it is now wrong.

Write the body file outside the repo. Show the user the posted title, body and URL
(informational).

## Step 9a: Screenshots

Only when this conversation produced screenshot or recording **files** for the change: upload
them into the template's screenshots row (with a screenshot-upload skill if one is installed;
otherwise say where the files are and leave the row for the user). Take no new screenshots. A UI
change without files keeps the row and says why; anything else skips silently.

## Step 9b: Ask the authors of overlapping work to review

```bash
bash "COMMIT_SCRIPTS/overlapping-branches.sh" "REMOTE/BASE"
```

From `pr` and `branch` rows, group by `login` (one reviewer, requested and commented on once).
Skip a login that is `-`; the PR author (`gh pr view NUMBER --repo BASE_REPO --json author -q .author.login`);
you (`gh api user -q .login`); already requested or reviewed
(`gh pr view NUMBER --repo BASE_REPO --json reviewRequests,reviews`); or removed as a reviewer before
(`gh api "repos/BASE_REPO/issues/NUMBER/timeline" --paginate -q '.[] | select(.event == "review_request_removed") | .requested_reviewer.login'`).

Request each remaining login in its own call (one invalid login fails a batched request with
422):

```bash
gh api -X POST "repos/BASE_REPO/pulls/NUMBER/requested_reviewers" -f 'reviewers[]=<login>'
```

When at least one succeeded, post one comment naming only this run's reviewers, one line each,
joining that reviewer's items with `;`. An item with `conflict=yes` reads "`<PR #n | branch
`b`>` has a merge conflict with this PR in `<conflict_files>`"; otherwise "`<…>` changes the same
files as this PR: `<files>`". Never call a non-conflicting file conflicting. Post with
`gh pr comment NUMBER --repo BASE_REPO --body-file <file>`.

Show a table: Reviewer, their PRs or branches, Shared files, Real conflict (`none` for `no`, the
files for `yes`, `not checked` for `unknown` — the script prints `-` for both `no` and
`unknown`, so never copy it), Requested (yes / skipped and why), plus stderr warnings. Script
exits non-zero → show stderr, say the check did not run and nobody was requested. No rows → "No
open PR or branch touches these files." Failed requests or comments are reported and never
block.

## Step 10: Tracker sync (best-effort)

Skip when `ISSUES` is empty. With a tracker MCP server (tools from Step 1): for each issue,
re-fetch; Backlog / Ready / Todo / In Progress → **In Review**; Done / Canceled / Duplicate →
leave it and tell the user (an open PR on a closed issue usually means the wrong link); attach the
PR URL if the integration has not within a minute; if the tracker requires a project and the
issue has none, tell the user — never guess one. GitHub Issues → nothing to do (the link words
do it). Nothing connected → skip silently. Never block the flow here.

## Step 11: CI, review bot, AI review

Do **not** end the turn here; this runs to completion.

### 11a. Watch CI

```bash
gh pr view NUMBER --repo BASE_REPO --json statusCheckRollup \
  -q '[.statusCheckRollup[] | {n:(.name // .context), s:(.status // .state), c:(.conclusion // .state)}]'
```

Running: `s` in `QUEUED` / `IN_PROGRESS` / `PENDING` / `WAITING` / `REQUESTED`. Done: non-empty
and nothing running (an empty rollup right after a push means CI has not registered). Pass:
`SUCCESS` / `SKIPPED` / `NEUTRAL`; fail: `FAILURE` / `ERROR` / `TIMED_OUT` / `CANCELLED` /
`ACTION_REQUIRED` / `STARTUP_FAILURE`. Poll in one backgrounded Bash call (`until …; do sleep
30; done`, ~20 min cap), exiting as soon as any check finishes failing (a job that `needs:` it
would never register). Still empty after 3 minutes → the repo runs no CI on this PR: say so and
continue.

- All green → 11b.
- Any failed → list names and URLs
  (`gh pr view NUMBER --repo BASE_REPO --json statusCheckRollup -q '.statusCheckRollup[] | select((.conclusion // .state) | test("FAILURE|ERROR|TIMED_OUT|CANCELLED|ACTION_REQUIRED|STARTUP_FAILURE")) | "\(.name // .context): \(.detailsUrl // .targetUrl)"'`),
  **stop** and ask how to proceed. Never fix CI on your own.
- Cap reached → say CI did not finish; stop.

### 11b. Review bot

Only when the facts name a `review bot login`; `none` → go to 11c. `BOT` is that login **without**
a trailing `[bot]` (GraphQL reports `coderabbitai`, the REST API `coderabbitai[bot]`). Count only
activity newer than the head commit, so feedback on an earlier push does not count as this
cycle's. Poll every ~2 min, up to ~10 min, in one backgrounded call:

```bash
since=$(TZ=UTC git log -1 --date=format-local:'%Y-%m-%dT%H:%M:%SZ' --format=%cd HEAD)
gh pr view NUMBER --repo BASE_REPO --json reviews,comments \
  -q '[.reviews[], .comments[]] | map(select((.author.login | rtrimstr("[bot]")) == "BOT" and (.submittedAt // .createdAt) > "'"$since"'")) | length'
```

- Bot comments → invoke the `pr-feedback` skill for this PR (it triages each comment with the
  user). If it is not installed, show the bot's comments and ask what to do.
  - It pushed fixes → CI and the bot will re-run: **no** AI review this cycle. Tell the user
    they can re-invoke this skill to watch the next cycle. Never loop on your own.
  - Nothing actionable → clean; 11c.
- Nothing by the timeout → say the bot did not report this cycle; 11c.

### 11c. AI review

Only when CI is green and no bot feedback is outstanding this cycle, and the facts name an
`AI review trigger`. Follow `REFS/ai-review.md` (re-run by ticking the sticky comment's
checkbox; post a fresh trigger only when there is no sticky comment and none is in flight for the
current commit). Do not poll for the review.

## Report

PR URL, mode, base; reviewers that ran / did not run and why; findings fixed and skipped; docs
touched; checks run with results (from `commit`); reviewers requested; tracker changes; CI and
bot outcome; AI review requested or not, and why. Once the PR is approved and green, the
`pr-merge` skill (`/pr-merge`, slash command only) lands it — say so; never merge from here.

## Rules

- Never skip rebase, review, the commit checks, or a triggered image build.
- Never post a product-facing PR without an issue link when the facts require one; housekeeping
  says so explicitly. Tracker sync never blocks.
- Codex and agy are optional: skip silently when absent; say so when they ran and failed;
  never auto-fix from them; never report a failed review as clean.
- PR descriptions are posted without a confirmation gate and shown afterwards.
- Docs go in the same change as the code that needs them.
- Never create a new branch; commit on the current one.
- If `rebase`, a reviewer agent or `commit` fails, stop and surface it.
- No AI attribution in commits, PR bodies or comments.
- Acceptance cases: `REFS/acceptance.md`.
