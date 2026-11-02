---
name: commit
description: Commit and push the current change safely — runs only the checks and tests the change needs (from the repo's .claude/project-facts.md), verifies that what is staged is what was checked, commits in the repo's message style, pushes with an explicit refspec and a pinned lease, verifies the push landed, then lists other branches that touch the same files. Use when the user runs /commit or asks to "commit and push", and when /pr-upsert calls it.
argument-hint: "[commit message hint] [--no-push]"
allowed-tools: Bash, Read, Write, Edit, Grep, Glob, AskUserQuestion
---

# Commit

Create a commit **only after** the checks the change needs have passed, push it safely, then
report which other branches might conflict. Follow the steps in order.

Why the rules look the way they do:

- **Checks read the worktree; commits read the index.** A formatter may change files after you
  staged them, and CI checks the *committed* version. So: verify staged = checked.
- **A bare `git push` in a worktree** can silently do nothing (feature branches may track the
  default branch as upstream) or push to the default branch. So: explicit refspec, a guard
  against an empty branch name, a lease pinned to a SHA captured in the same call, and a
  post-push check that the remote really moved.
- **Shared machines.** Many agents run at once, so run only what the change needs; CI runs
  everything.
- **Unrelated dirty files** are not a reason to ask: stage only the relevant files.

Paths: `SCRIPTS` is `${CLAUDE_SKILL_DIR}/scripts`; `REBASE_SCRIPTS` is
`${CLAUDE_SKILL_DIR}/../rebase/scripts` (the `rebase` skill installed next to this one — for a
copy install, `~/.claude/skills/rebase/scripts`). Use absolute paths.

## Step 0: Context and facts

```bash
bash "REBASE_SCRIPTS/git-context.sh"
```

`CONTEXT_FAILED` → stop and report (several remotes: ask which). Note `branch`,
`push_remote` (written `ORIGIN` below), `base_remote`, `default_branch` (written `DEFAULT`) and
`facts`.

- Detached HEAD (`branch` empty) → stop.
- `branch` equals `DEFAULT` → **stop and ask** before committing: commit here without pushing,
  or let the user create a branch. Never push to the default branch.

Read `.claude/project-facts.md` (`## install`, `## areas`, `## checks`, `## generated`,
`## commit`). If it is missing, or lacks a section this change needs, follow
`${CLAUDE_SKILL_DIR}/../rebase/references/project-facts.md` once. Never run a command that is
neither in the facts nor confirmed by the user.

`$ARGUMENTS`: `--no-push` skips Steps 5 and 6; anything else is a hint for the message.

## Step 1: Dependencies

If dependencies are missing (common in a fresh worktree: no `node_modules`, no virtualenv),
run the `## install` command for the areas that changed.

## Step 2: Checks the change needs

List the changed files:

```bash
{ git diff --name-only HEAD; git ls-files -o --exclude-standard; } | sort -u
```

Map them to the `## areas` rows. A shared path or root dependency file counts as every area.
For each affected area, run its lint-with-autofix and its typecheck (in parallel when they are
independent). When a `.md` file changed and the facts name a markdown lint, run it. When a
migration or generated file — or the source a generator reads — changed, also run the
structural checks:

```bash
bash "REBASE_SCRIPTS/local-checks.sh"
```

Read its last line: `LOCAL_CHECKS_OK` passed; `LOCAL_CHECKS_NONE` → "no local checks
configured"; `LOCAL_CHECKS_FAILED` → fix and re-run; `NO_PROJECT_FACTS`/`NO_CHECKS_SECTION`/`MALFORMED_CHECKS` →
see Step 0. Exit 127 or "No such file" (the rebase skill is not installed) → say "local checks
did not run: the rebase skill's scripts were not found" and continue — never report them as
passed.

No area changed (docs, skills, CI config only) → skip lint, typecheck and local checks, and say
so. An area whose cell is `-` has no such step; say "none configured", not "passed".

If a check fails, fix the cause and re-run it. Never skip a check the change needs. If a check
regenerated files, they belong in the commit (Step 4.4).

## Step 3: Tests the change needs

Run only the tests covering the change: each changed test file, plus the tests of each area
with a changed source file, using the area's test command (`{files}` = those paths). Never the
whole suite — CI runs it. Keep the parallelism cap the facts give (`-n 2`, `--maxWorkers=2`).

No code changed → no tests, and say so. Tests fail → **stop and report**; never commit failing
tests.

## Step 4: Stage and commit

1. `git status` and `git diff` to review the change.
2. `git log --oneline -10` to see the repo's message style.
3. Stage only the files that belong to this change — never `git add -A`, never `.env`,
   credentials, or large binaries. Leave unrelated dirty files alone, and do not ask about them.
4. The checks read the working tree. **Stop** if this prints anything — a generated or migration
   file left unstaged means the commit differs from what was checked (paths from `## generated`;
   skip when it says `none`):
   `git diff --name-only -- <generated and migration paths>; git ls-files -o --exclude-standard -- <same paths>`
5. **Staged must equal checked.** The checks ran on the working tree, the commit holds the
   index. `git diff -- <staged files>` must print nothing (a formatter or hook rewrote a file
   after it was staged → re-stage it). Then `git diff --name-only` lists what stays unstaged:
   any of those paths inside an area whose checks ran means the checks saw code this commit
   leaves out. Stage it if it belongs to this change; otherwise say in the report that the
   checks ran with those files present. This mismatch is the classic "passes locally, fails in
   CI".
6. The message: the `## commit` style if the facts give one; otherwise match `git log` (e.g.
   Conventional Commits when the log uses them); with no clear style, Linux kernel style:
   - subject: capitalized imperative ("If applied, this change will …"), ≤ 50 characters;
   - blank line, body wrapped at 72, on the *why* rather than the what;
   - non-trivial commits end with short `-` bullets;
   - fold in the `$ARGUMENTS` hint if there is one.
   **No AI attribution**: no `Co-Authored-By: Claude`, no session links, no "Generated with" line.
7. Commit with a heredoc message. Never `--no-verify`. If a hook fails, fix the cause and make a
   **new** commit — never `--amend` unless the user asked.
8. `git status` to confirm.

## Step 5: Push

**Never a bare `git push`.** Push with an explicit refspec and verify, in the **same Bash call**
(shell variables do not survive between calls), that the remote branch moved. Substitute
`ORIGIN` and `DEFAULT` from Step 0 as literals:

```bash
BRANCH=$(git branch --show-current)
if [ -z "$BRANCH" ] || [ "$BRANCH" = "DEFAULT" ]; then
  echo "REFUSING to push: detached HEAD or the default branch (branch='$BRANCH')"; exit 1
fi
DEFAULT_BEFORE=$(git rev-parse "ORIGIN/DEFAULT" 2>/dev/null || echo none)
REMOTE_BEFORE=$(git rev-parse --verify --quiet "refs/remotes/ORIGIN/$BRANCH")
# Commits on the remote branch with no equivalent patch in HEAD would be lost by this push.
if [ -n "$REMOTE_BEFORE" ] && [ -n "$(git rev-list --cherry-pick --right-only --no-merges "HEAD...$REMOTE_BEFORE")" ]; then
  echo "REFUSING to push: ORIGIN/$BRANCH has commits HEAD does not contain:"
  git log --oneline --cherry-pick --right-only --no-merges "HEAD...$REMOTE_BEFORE"; exit 1
fi
git push --force-with-lease="refs/heads/$BRANCH:$REMOTE_BEFORE" ORIGIN "$BRANCH:$BRANCH"; echo "push_exit=$?"
echo "HEAD=$(git rev-parse HEAD)"
echo "remote=$(git rev-parse "ORIGIN/$BRANCH" 2>&1)"
echo "default_before=$DEFAULT_BEFORE"
echo "default_after=$(git rev-parse "ORIGIN/DEFAULT" 2>/dev/null || echo none)"
```

For a branch with no remote yet `REMOTE_BEFORE` is empty, and an empty expected value means
"the remote ref must not exist yet" — the right check for a first push. Do not add `-u`.

The guards matter. With no branch name, `git push ORIGIN ":"` is git's matching refspec and can
push the local default branch. The lease is pinned to a SHA captured in this same call because
a bare `--force-with-lease` re-reads `refs/remotes/*`, which any concurrent session's fetch
refreshes. That captured SHA can itself be fresher than what you built on (a fetch in `/rebase`
or another session saw a teammate's push), so the `--cherry-pick` check refuses any push that
would drop a remote commit whose change HEAD does not carry — a rebased copy of your own commits
passes, a teammate's new commit does not.

`REFUSING to push` from that check, or a rejected push (`stale info`, `fetch first`) → the remote
branch has work you do not have. **Stop and report it.** Never retry with a newly fetched SHA
and never a bare `--force`: that is exactly how a teammate's push gets overwritten. The fix is to
integrate it (`/rebase` onto the remote branch, or a pull) and run this skill again.

In a fork checkout `ORIGIN` is the fork; that is where the PR branch lives.

**Stop and report** if any of these hold — each is a failure, not a warning:

- `remote` errors (`unknown revision`): the push created nothing.
- `remote` ≠ `HEAD`: the push did not land what you committed.
- `default_after` ≠ `default_before`: the push went to the wrong branch.
- `push_exit` is non-zero: read the error first.

Never report the commit as pushed until `remote` is shown to equal `HEAD`.

## Step 6: Branches that may conflict

```bash
OVERLAP_REMOTE=BASE_REMOTE bash "SCRIPTS/overlapping-branches.sh" "BASE_REMOTE/DEFAULT"
```

(`BASE_REMOTE` is `base_remote` from Step 0 — `upstream` in a fork checkout, where the project's
branches and PRs live.)

It prints one TSV row per overlapping branch (columns in the script's header). Show every row as
a table — Branch, PR, Author, Shared files, Real conflict (`conflict_files` on `yes` rows) —
`conflict=yes` first. Use `login`, or `author` when `login` is `-`; mark drafts; `local` rows
are the user's own unpushed branches. Show `conflict=unknown` as "not checked", and every stderr
warning verbatim — a skipped branch is not a clean one. No rows (exit 0) → "No other branch
touches these files."

This is a report, not a gate: never block or undo the commit on it. Non-zero exit (no `gh`, git
older than 2.38, a failed lookup) → show the error and say the check did not run.

## Rules

- Never `--no-verify`, never skip hooks, never amend unless asked.
- Push after every successful commit (unless `--no-push`), only as in Step 5. Never a bare
  `git push` or `git push --force`; never push the default branch.
- Never ask whether to stash, commit or discard unrelated changes. Stage what belongs to this
  change; if a formatter touched other files, leave them.
- Never report a check, a test or a push as done without its output.
- Acceptance cases: `references/acceptance.md`.
