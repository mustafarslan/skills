# pr-merge — acceptance cases

The `rebase` contract pr-merge relies on: given a target branch, fetch and rebase the current
branch onto it; regenerate conflicts that are only in the project's generated files; stop on any
other conflict, leaving the rebase state for the user; never push; say whether it rebased, was a
no-op, or stopped.

| Situation | Must end with |
|---|---|
| `$ARGUMENTS` is `12 --admin` | Stop and ask for a single PR number or URL. |
| PR is a draft, closed or merged | Stop and report; nothing is merged. |
| `reviewDecision` is `REVIEW_REQUIRED` or `CHANGES_REQUESTED` | Stop and report. |
| `reviewDecision` empty (base requires no review), no facts | Ask once; merge only on yes. |
| `reviewDecision` empty and facts say `approval: yes` | Stop and report. |
| Local branch is not `headRefName` | Stop; tell the user to run from the PR's branch. |
| Rules API call fails | Stop and report the output; never fall to "no queue". |
| Base requires no checks and the PR has none | Says the repo runs no CI on it; asks before merging. |
| Base has a queue, `mergeStateStatus` is `BEHIND`, no conflict | No rebase; wait for checks, enqueue. |
| Base has a queue, checks all red because GitHub CI is down | Stop; do not enqueue; do not push to re-trigger. |
| Head SHA changed between "green" and enqueue | Back to the Q1 wait once; second change → stop. |
| `enqueuePullRequest` returns errors | Stop and print them; never fall back to `gh pr merge`. |
| Queue removes the PR for a conflict, third time | Stop and report. |
| Queue removes the PR for a failed check | Stop; report the merge-group commit; never re-enqueue. |
| Queue removal reason is a person | Stop; do not add it back. |
| No queue, base moves while CI runs | Back to F1 (rebase, push, wait again). |
| No queue, `mergeStateStatus` is `BLOCKED` with an all-green rollup | Re-check every 30 s for up to 5 min, then stop. |
| No queue, repo allows only merge commits | Merges with `--merge`; facts not needed. |
| Default branch is `master` | Nothing assumes `main`. |
| F1a: the PR branch has a teammate's commit HEAD lacks | `REFUSING to push`; stop. |
| PR from a contributor's fork (`isCrossRepository`), up to date, green | Merged without checking out or pushing its branch. |
| Fork PR that is `CONFLICTING`, or `BEHIND` with no queue | Stop; the author must update it. |
| Run from a fork checkout | Every `gh` call targets `BASE_REPO`, not the fork. |
| Base branch with a slash (`release/1.0`) | URL-encoded in API paths. |
| A required job's dependency fails, so the job never registers | Loop exits on the first failure; no wait to the cap. |
| A non-required check fails, all required ones green | Named; the user decides. |
| Repo allows merge commits and rebase, not squash, no facts | Merge commit (`squash → merge → rebase`). |
| Any path | `--admin` is never passed. |
