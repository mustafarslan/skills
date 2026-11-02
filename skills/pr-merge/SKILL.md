---
name: pr-merge
description: Take an approved GitHub PR the rest of the way — add it to the base branch's merge queue and watch it until it merges, or, on a base with no queue, rebase, wait for CI and merge with the repo's method — never bypassing branch protection. Slash command only (/pr-merge [PR]).
argument-hint: "[PR number or URL; default: the current branch's PR]"
disable-model-invocation: true
allowed-tools: Bash, Read, Skill, AskUserQuestion
---

# PR merge

Take an approved PR the rest of the way. When the base has a **merge queue**, add the PR to the
queue and watch it until it merges: the queue tests the PR on top of the current base, so this
skill never rebases just because the base moved. On a base with no queue, use the fallback:
rebase, wait for CI, then merge. Follow the steps strictly and **never bypass branch
protection**.

Needs `gh` (logged in, with access to the repo) and the `rebase` skill installed next to this
one. GitHub only.

Design rules:

- **Hard gates, re-checked at the last moment** (open, not a draft, approved, no conflict,
  required checks green), because each can change while CI runs.
- **Fail loud.** A failed lookup (rules API, queue query, push verification) stops the skill
  with the exact output. Never turn a failed call into an assumption such as "no queue".
- **Fix only conflicts.** CI failures are surfaced, never repaired.
- **Long waits are one backgrounded Bash call** (`run_in_background: true`) with an
  `until … sleep` loop and a cap, so you are notified on exit instead of polling every turn.
- **Bounded retries.** Re-enqueue after a conflict (at most 2 times) or after one CI
  infrastructure failure; never after a failed check, a timeout, or a manual removal.

**Which repository.** Every `gh` call targets the PR's repository, `BASE_REPO` (from Step 0):
`repos/BASE_REPO/…` in `gh api` paths, `-F owner=… -F repo=…` split from it in GraphQL, and
`--repo BASE_REPO` on every `gh pr` / `gh repo` command. Do not rely on `gh`'s own choice: in a
fork checkout it may resolve to the fork, or refuse until `gh repo set-default` is run.
`REBASE_SCRIPTS` is `${CLAUDE_SKILL_DIR}/../rebase/scripts` (absolute).

## Step 0: Context and the target PR

```bash
bash "REBASE_SCRIPTS/git-context.sh"
```

`CONTEXT_FAILED` or `gh=no` → stop and report (this skill needs `gh`). Note `push_remote`
(written `ORIGIN`: where the PR branch lives) and `base_remote` (written `UPSTREAM`: where the
base branch lives; the same remote unless this is a fork checkout), and `base_repo` (written
`BASE_REPO`). An empty `base_repo` (the remote is not a GitHub URL, e.g. an SSH alias) → read it
with `gh repo view --json nameWithOwner -q .nameWithOwner` and confirm it with the user. Then
`git fetch --prune UPSTREAM` (and `ORIGIN`, when different).

**Validate `$ARGUMENTS` before it reaches `gh`.** It must be empty, or a **single token** that
is a bare PR number (`778`) or a PR URL (`https://github.com/<owner>/<repo>/pull/778`).
Whitespace, a leading `-` (a flag to `gh`), or more than one token → **stop and ask** for one PR
number or URL. Use the validated value as `SELECTOR` (empty = the current branch's PR):

```bash
gh pr view SELECTOR --repo BASE_REPO --json number,title,url,headRefName,baseRefName,state,isDraft,mergeable,mergeStateStatus,reviewDecision,isCrossRepository \
  -q '{number, title, url, headRefName, baseRefName, state, isDraft, mergeable, mergeStateStatus, reviewDecision, isCrossRepository}'
```

Capture `number`, `title`, `headRefName` (written `HEAD_BRANCH`), `baseRefName` (written
`BASE`). **Stop and report** if `state` is not `OPEN`, or `isDraft` is `true`. A conflict is
handled in Step 3.

`isCrossRepository: true` — the PR's branch lives in someone's fork, so this skill cannot push
to it. It can still merge: skip Step 2, never run F1/F1a or a Q1 rebase, and if the PR is
`CONFLICTING`, or `BEHIND` on a base with no queue, **stop** and say the author has to update
the branch.

Read `## pr-merge` in `.claude/project-facts.md` if it exists (`method`, `approval`). It is
optional; the defaults are below.

## Step 1: Approval

- `reviewDecision` is `APPROVED` → continue.
- `REVIEW_REQUIRED` or `CHANGES_REQUESTED` → **stop and report** the decision; the PR needs an
  approving review first.
- Empty or null → the base does not require a review. If the facts say `approval: yes`, stop as
  above. Otherwise (`ask`, or no facts) **ask the user once** whether to merge without an
  approving review, and stop unless they say yes. Remember the answer for the re-checks below.

## Step 2: Be on the PR branch (same-repository PRs)

```bash
git branch --show-current
```

Not `HEAD_BRANCH` → stop and tell the user to run `/pr-merge` from the PR's branch (or its
worktree). Never check out or create branches yourself.

## Step 3: Does the base have a merge queue?

```bash
gh api "repos/BASE_REPO/rules/branches/BASE" \
  --jq '[.[] | select(.type == "merge_queue")] | length'; echo "rules_exit=$?"
```

- `rules_exit` non-zero, or no number → **stop and report** the output. Never assume "no queue":
  the fallback would rebase and try a direct merge, which a queue rejects.
- `1` or more → queue: **Steps Q1–Q4**.
- `0` → no queue. If `mergeable` is `CONFLICTING`, **stop**: the user resolves the conflict
  first. Otherwise the **fallback, Steps F1–F3**.

### Required checks (both flows need the list)

Collect the required contexts from rulesets **and** classic branch protection. In these paths
write `BASE` URL-encoded (`release/1.0` → `release%2F1.0`):

```bash
gh api "repos/BASE_REPO/rules/branches/BASE" \
  --jq '[.[] | select(.type == "required_status_checks") | .parameters.required_status_checks[].context]'; echo "rules_exit=$?"
gh api "repos/BASE_REPO/branches/BASE" \
  --jq '[(.protection.required_status_checks.contexts // [])[], (.protection.required_status_checks.checks // [])[].context] | unique'; echo "branch_exit=$?"
```

Either call failing → stop and report the output. The union is `REQUIRED`. When `REQUIRED` is empty the
base requires no check: wait instead for **every check the PR has**. If the rollup is still empty
2 minutes after the head commit was pushed, the wait loops below exit (`NO_CI`): tell the user
the repo runs no CI on this PR and ask before merging. Never call an empty rollup "green" on your
own.

A required context matches a rollup entry by its `name` (check runs, status contexts) or by
`<workflowName> / <name>` (how some rulesets name Actions jobs).

## Queue flow

### Q1: The PR's own checks are green

The queue builds a merge group (the PR on top of the base and the PRs ahead of it) and runs the
required checks on it; it does **not** need the PR up to date, so `BEHIND` is no reason to
rebase. No local test run replaces CI here. If GitHub CI is down (every check finished and none
passed, e.g. a billing block), **stop**: do not add the PR, and do not push to re-trigger CI.

Rebase **only** when:

- `mergeable` is `CONFLICTING` (no group can be built, and GitHub runs no `pull_request` CI on a
  branch it cannot merge); or
- a PR check failed because of the **old base**, and the current base has the fix. Show the
  evidence: the failing log line and the base commit that fixes it.

To rebase, run F1 (rebase + F1a push), then continue here. Any other failing check → surface it
as in F2 and **stop**.

Wait for the checks — no base-moved test in this loop. Poll, reading the head SHA in the same call
as the rollup so "green" belongs to a known commit:

```bash
gh pr view NUMBER --repo BASE_REPO --json headRefOid,statusCheckRollup \
  -q '{head: .headRefOid,
       checks: [.statusCheckRollup[] | {n:(.name // .context), w:(.workflowName // ""), s:(.status // .state), c:(.conclusion // .state)}]}'
```

Read entries as in F2. Wait only for `REQUIRED` (or every check, per the rule above). A required
context with no entry is **pending**. A non-required check still running (e.g. an optional bot
status) does not hold the wait; name it in the report. One backgrounded Bash call
(`run_in_background: true` — it is not bound by the foreground timeout): `until <every awaited
context has an entry and none is running, OR any awaited check finished failing, OR NO_CI>; do
sleep 30; done`, ~20 min cap; print `head` and the exit reason from the last poll. Exit on the
first awaited failure: a job that `needs:` a failed one never registers, and waiting for it only
burns the cap.

- All awaited contexts green → record `head` as `GREEN_SHA`; go to Q2.
- An awaited check failed → surface names and URLs (F2 query) and **stop**.
- A check that is **not** required failed while every required one passed → name it and ask the
  user whether to go on; GitHub would merge, but someone wired that check up for a reason.
- `NO_CI` → ask as above.
- Cap reached with a context running or missing → stop and name them.

### Q2: Add the PR to the queue

Re-check the gates just before:

```bash
gh pr view NUMBER --repo BASE_REPO --json id,headRefOid,state,mergeable,reviewDecision \
  -q '{id, headRefOid, state, mergeable, reviewDecision}'
```

`state` `OPEN`; `reviewDecision` still as accepted in Step 1; `mergeable` not `CONFLICTING` —
else stop. `headRefOid` must equal `GREEN_SHA`; if not, someone pushed after the checks passed:
back to the Q1 wait once, and stop if it differs again.

Enqueue with the `enqueuePullRequest` mutation (the "Merge when ready" button), passing `id` and
`headRefOid` as literals; `expectedHeadOid` makes GitHub refuse if the head moved:

```bash
gh api graphql -f id='<id>' -f oid='<headRefOid>' -f query='
  mutation($id: ID!, $oid: GitObjectID!) {
    enqueuePullRequest(input: {pullRequestId: $id, expectedHeadOid: $oid}) {
      mergeQueueEntry { position state }
    }
  }'; echo "enqueue_exit=$?"
```

Not `gh pr merge`: on a queue-protected base it calls `enablePullRequestAutoMerge`, which fails
when the repo disallows auto-merge. `gh pr merge --admin` skips the queue: **never.**
`enqueue_exit` non-zero or `errors` in the output → **stop and report it exactly**; try no other
command.

Confirm it **is in the queue** (the API can lag: up to 6 checks, 10 s apart):

```bash
gh api graphql -F owner='<owner of BASE_REPO>' -F repo='<name of BASE_REPO>' -F n=NUMBER -f query='
  query($owner: String!, $repo: String!, $n: Int!) {
    repository(owner: $owner, name: $repo) {
      pullRequest(number: $n) {
        state isInMergeQueue
        mergeQueueEntry { state position headCommit { oid } }
      }
    }
  }' --jq '.data.repository.pullRequest'
```

`isInMergeQueue` true → Q3. `state` `MERGED` → Step 4. Neither after the last check → stop and
report both outputs.

### Q3: Watch the entry until it merges or leaves

One backgrounded Bash call; every 60 s run the Q2 query. Whenever
`mergeQueueEntry.headCommit.oid` is non-null, write it to a file in the scratchpad (the
merge-group commit, needed in Q4 after the entry is gone); never overwrite it with null. Exit
when `state` is `MERGED`; when `isInMergeQueue` is false; when the query failed 3 times in a row
(print the error — a failed query is not a removal); or after 120 min.

- `MERGED` → Step 4. Removed → Q4. Query failures or the cap → stop and report; do not re-add.

### Q4: The queue removed the PR

```bash
gh api graphql -F owner='<owner of BASE_REPO>' -F repo='<name of BASE_REPO>' -F n=NUMBER -f query='
  query($owner: String!, $repo: String!, $n: Int!) {
    repository(owner: $owner, name: $repo) {
      pullRequest(number: $n) {
        state mergeable
        timelineItems(last: 5, itemTypes: [REMOVED_FROM_MERGE_QUEUE_EVENT]) {
          nodes { ... on RemovedFromMergeQueueEvent { createdAt reason actor { login } } }
        }
      }
    }
  }' --jq '.data.repository.pullRequest'
```

`state` `MERGED` → Step 4. Otherwise find the failing check on the merge-group commit saved in Q3
(no saved SHA → the queue never built a group; say so and skip this query):

```bash
gh api "repos/BASE_REPO/commits/GROUP_OID/check-runs" --paginate \
  --jq '.check_runs[] | select(.conclusion != null and (.conclusion | test("failure|timed_out|cancelled|action_required")))
        | "\(.name): \(.conclusion) \(.html_url)"'
```

Report the reason, the failing checks and URLs, then:

- **Conflict** → rebase as in Q1, wait for checks, back to Q2. At most 2 times per run; a third
  conflict removal → stop.
- **GitHub CI is down** (jobs ran no steps; the annotation names billing or a spending limit) →
  **stop**; do not re-add.
- **CI infrastructure failure** (the log shows the job never ran the code: a service container
  did not start, the runner was lost) → re-add once (Q2). A second one → stop and report both.
  Quote the log line that proves it; if you cannot, treat it as a check failure.
- **A check failed or timed out** → **stop**; do not fix, do not re-add. Name the merge-group
  commit: the failure may come from a PR ahead of this one.
- **Removed by a person** → stop; never re-add against their decision.
- **No event, or an unclear reason** → stop and report what you have.

## Fallback flow (no merge queue)

### F1: Rebase on the base

Invoke the `rebase` skill (`skills:rebase` when installed as the plugin) with `BASE` as its
argument. If it reports conflicts or failed checks, stop and surface them.

Then compare local HEAD with the PR's **remote** head — not HEAD before/after the rebase: a no-op
rebase still leaves unpushed local commits, and merging would land a stale remote SHA.

```bash
git rev-parse HEAD
git rev-parse "ORIGIN/HEAD_BRANCH"
```

Equal → nothing to push; continue (F2, or back in Q1). Different → F1a.

### F1a: Push the branch

A rebase rewrote history, so force-with-lease, with an explicit refspec, pinned to a SHA captured
in **this same call**, verified in the same call:

```bash
BASE_BEFORE=$(git rev-parse "UPSTREAM/BASE")
REMOTE_BEFORE=$(git rev-parse --verify --quiet "refs/remotes/ORIGIN/HEAD_BRANCH")
if [ -n "$REMOTE_BEFORE" ] && [ -n "$(git rev-list --cherry-pick --right-only --no-merges "HEAD...$REMOTE_BEFORE")" ]; then
  echo "REFUSING to push: ORIGIN/HEAD_BRANCH has commits HEAD does not contain:"
  git log --oneline --cherry-pick --right-only --no-merges "HEAD...$REMOTE_BEFORE"; exit 1
fi
git push --force-with-lease="refs/heads/HEAD_BRANCH:$REMOTE_BEFORE" ORIGIN "HEAD_BRANCH:HEAD_BRANCH"; echo "push_exit=$?"
echo "HEAD=$(git rev-parse HEAD)"
echo "remote=$(git rev-parse "ORIGIN/HEAD_BRANCH" 2>&1)"
echo "base_before=$BASE_BEFORE"
echo "base_after=$(git rev-parse "UPSTREAM/BASE")"
```

`REFUSING to push` or a rejected lease means the PR branch has commits you do not have (a
teammate pushed): **stop and report**; never retry with a newly fetched SHA. **Stop and report**
too if `remote` errors, `remote` ≠ `HEAD`, `push_exit` is non-zero, or
`base_after` ≠ `base_before` (compare the two printed values; never assert "unchanged" without
both): the push went to the wrong branch (e.g. the parent of a stacked PR).

### F2: Wait for CI

Poll the JSON rollup (robust where wrappers turn `gh pr checks --watch` into a snapshot):

```bash
gh pr view NUMBER --repo BASE_REPO --json statusCheckRollup \
  -q '[.statusCheckRollup[] | {n:(.name // .context), s:(.status // .state), c:(.conclusion // .state)}]'
```

- Running: `s` in `QUEUED` / `IN_PROGRESS` / `PENDING` / `WAITING` / `REQUESTED`.
- Done: classify by `c` — `SUCCESS` / `SKIPPED` / `NEUTRAL` pass; `FAILURE` / `ERROR` /
  `TIMED_OUT` / `CANCELLED` / `ACTION_REQUIRED` / `STARTUP_FAILURE` fail.

On every poll also check the base:

```bash
BASE_NOW=$(git ls-remote UPSTREAM "refs/heads/BASE" | cut -f1)
if [ -z "$BASE_NOW" ]; then echo "base=unknown"
elif git merge-base --is-ancestor "$BASE_NOW" HEAD 2>/dev/null; then echo "base=same"
else echo "base=moved"; fi
```

(`base=moved` also prints when the new base commit is not fetched yet — that is still a move.)

Wait as in Q1 (awaited contexts; a missing required context is pending; an empty rollup right
after a push means CI has not registered). One backgrounded call: `until <base=moved or
base=unknown, or every awaited context has an entry and none is running, or any awaited check
finished failing, or NO_CI>; do sleep 30; done`, ~20 min cap. On exit:

- `base=unknown` → stop and report (network, auth, or the base is gone — a rebase fixes neither).
- `base=moved` → back to F1 now.
- All awaited green, nothing finished failing → F3.
- `NO_CI` → ask the user; on yes, F3.
- A non-required check failed, every required one green → name it and ask whether to go on.
- An awaited check failed → list them and **stop**; never fix CI, never merge:

  ```bash
  gh pr view NUMBER --repo BASE_REPO --json statusCheckRollup \
    -q '.statusCheckRollup[] | select((.conclusion // .state) | test("FAILURE|ERROR|TIMED_OUT|CANCELLED|ACTION_REQUIRED|STARTUP_FAILURE")) | "\(.name // .context): \(.detailsUrl // .targetUrl)"'
  ```
- Cap reached with an awaited context running or missing → stop; never merge on an unfinished
  required check.

### F3: Confirm, then merge

```bash
gh pr view NUMBER --repo BASE_REPO --json mergeable,mergeStateStatus,reviewDecision \
  -q '{mergeable, mergeStateStatus, reviewDecision}'
gh repo view BASE_REPO --json squashMergeAllowed,mergeCommitAllowed,rebaseMergeAllowed
```

- `reviewDecision` must still be what Step 1 accepted; if it regressed, stop.
- `mergeable` must not be `CONFLICTING`.
- `BEHIND` → back to F1 (rebase, push, CI again). Never force it with `--admin`.
- `BLOCKED` with an accepted review → a required check is missing, pending or failed (a late
  workflow can appear after F2 exits). Re-read the F2 rollup: failed → stop; empty or running →
  back to F2; all green → re-check this every 30 s for up to 5 min, then stop and report that a
  required check never registered. Never loop back to F2 on an all-green rollup.

The method: `## pr-merge` `method` from the facts; otherwise the first the repo allows of
squash → merge → rebase. A facts method the repo disallows → stop and say so. Pass the subject explicitly so it runs non-interactively; for
squash use the repo's usual `<title> (#<number>)`:

```bash
gh pr merge NUMBER --repo BASE_REPO --squash --subject "<title> (#<number>)" --body ""     # or --merge / --rebase (no subject)
```

Never `--admin`. Never `--delete-branch` (the branch is checked out here; let the repo's
auto-delete handle the remote).

## Step 4: Confirm

```bash
gh pr view NUMBER --repo BASE_REPO --json state,mergedAt,url -q '{state, mergedAt, url}'
```

Report the merge with the URL. Issues linked with a closing keyword (`Fixes …`) close through
the tracker's GitHub integration.

## Rules

- **Never bypass branch protection**: no `--admin`, no merging a `BEHIND` or unapproved PR
  (unless the base requires no review and the user said yes in Step 1). With a queue, enqueue
  only with `enqueuePullRequest`.
- **With a queue, never rebase because the base moved.** Only for a conflict, or a check that
  failed because of the old base.
- Merge only on green awaited checks; never fix CI; surface and stop.
- Pushes: explicit refspec, lease pinned to a captured SHA, verified in the same call.
- Never create or check out branches.
- Acceptance cases: `references/acceptance.md`.
