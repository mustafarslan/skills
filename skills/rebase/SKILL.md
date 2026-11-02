---
name: rebase
description: Rebase the current git branch onto its base (the PR's base, or the repo's default branch when the base was merged and deleted) without asking — auto-stashes uncommitted work safely, regenerates conflicts that are only in generated files, then runs the repo's local checks. Use when the user asks to rebase, update or sync a branch with main/master, and when /commit, /pr-merge or /pr-upsert call it. Never pushes.
argument-hint: "[target branch] [--test]"
allowed-tools: Bash, Read, Write, AskUserQuestion
---

# Rebase

Rebase the current branch onto its base. A naive `git rebase` in a busy multi-worktree,
multi-agent setup loses work in four ways; each rule below closes one:

1. **A dirty tree blocks the rebase** → auto-stash, never ask.
2. **The stash stack is shared** by the main checkout, every worktree and every concurrent
   agent session, so `git stash pop` may take someone else's work → tag the entry, capture its
   SHA, restore with `git stash apply <sha>`, drop by re-finding the tag.
3. **The base branch may have been merged and deleted** → fall back to the default branch and
   say so.
4. **A clean rebase can still break the build** → run the repo's local checks afterwards.

A rebase step whose **only** conflicts are in generated files is resolved by regenerating them.
Any other conflict stops the skill. This skill never pushes; the caller does (`/commit`,
`/pr-merge`).

`SCRIPTS` below is `${CLAUDE_SKILL_DIR}/scripts` as an absolute path (for a copy install,
`~/.claude/skills/rebase/scripts`).

## Step 1: Context

```bash
bash "SCRIPTS/git-context.sh"
```

On `CONTEXT_FAILED`, stop and report the reason (with several remotes, ask which to use).
Otherwise note `branch`, `base_remote` (written `REMOTE` below — usually `origin`, `upstream` in
a fork checkout) and `default_branch` (written `DEFAULT`), and whether `gh=yes`.

- `branch` is empty (detached HEAD) → stop: nothing to rebase.
- `branch` equals `DEFAULT` → stop: nothing to rebase.

Then:

```bash
git fetch --prune REMOTE
```

(and `git fetch --prune origin` too when `REMOTE` is `upstream`, so the branch's own remote ref
is current).

## Step 2: The base branch

`$ARGUMENTS` may hold a target branch and the `--test` flag (Step 5). Take the flag out first;
what remains, if anything, is the target. **Stop** on any other `--` token (a typo like
`--tests`) — never read it as a branch name.

- A target was given → that is the base. Strip a leading `REMOTE/` (`origin/main` → `main`).
- Otherwise, when `gh=yes`: `gh pr view --json baseRefName -q .baseRefName 2>/dev/null` — the
  PR's base, if the branch has a PR.
- Otherwise → `DEFAULT`.

## Step 3: Does the base still exist?

```bash
git rev-parse --verify --quiet "refs/remotes/REMOTE/<base>"
```

If it prints nothing:

- the base was **given in `$ARGUMENTS`** → **stop**: it may be a typo; name the branch and ask.
  Never fall back silently from a branch the user (or a calling skill) named;
- the base came from the PR or the default → it was merged and deleted: say "Base branch
  `<base>` no longer exists on REMOTE (merged and deleted?). Rebasing on `DEFAULT` instead." and
  use `DEFAULT`.

## Step 4: Rebase

If the worktree is dirty (staged or unstaged changes to tracked files), auto-stash them — **do
not ask** whether to stash or commit first.

**Never `git stash pop`, and never address a stash by position.** Tag your entry, capture its
commit SHA, restore with `git stash apply <sha>`, then drop it by re-finding its tag.

Shell variables do not survive between Bash calls, so each call below **prints** what the next
needs; substitute the printed values literally.

0. **Report any stale auto-stash from an aborted run.**

   ```bash
   git stash list --format='%gd %gs' | grep -E ': rebase-skill-autostash$' || echo 'NO_STALE_AUTOSTASH'
   ```

   The match is anchored and narrow: git records the subject as `On <branch>: <message>`, and
   the bare name is the fixed message older runs used, so such an entry is unrecovered work.
   **Stop and ask the user**: restore it first (`git stash apply <its stash@{n}>`) or proceed.
   Never apply or drop it yourself.

   A suffixed entry (`rebase-skill-autostash-<timestamp>-<pid>`) on **this** branch
   (`On <branch>: rebase-skill-autostash-…`) is left from an earlier run here that stopped on a
   conflict — one branch is checked out in one worktree at a time, so no live session owns it.
   **Stop and ask** as above. A suffixed entry on another branch may belong to a session still
   running there: mention it, but do not stop — entries are uniquely tagged and addressed by
   SHA, so it cannot be confused with yours.

   ```bash
   git stash list --format='%gd %gs' | grep -F "On $(git branch --show-current): rebase-skill-autostash-" || echo 'NONE_ON_THIS_BRANCH'
   ```

1. **Stash if dirty, under a unique tag, and capture the SHA:**

   ```bash
   TAG="rebase-skill-autostash-$(date +%s)-$$"
   git update-index -q --refresh   # a touched-but-unchanged file must not read as dirty
   if git diff-index --quiet HEAD --; then
     echo "CLEAN no-stash"
   else
     git stash push -m "$TAG" || { echo "STASH_FAILED"; exit 1; }
     git stash list --format='%H %gs' | grep -F "$TAG" || { echo "STASH_NOT_FOUND"; exit 1; }
   fi
   ```

   Record the tag and the 40-character SHA on the matching line. `CLEAN no-stash` → skip
   sub-steps 3 and 4. `STASH_FAILED` or `STASH_NOT_FOUND` → **stop and report**; never rebase
   over changes you failed to set aside.

   Untracked files are deliberately **not** stashed: they rarely conflict with a rebase, and
   sweeping them up disturbs unrelated scratch work. If the rebase fails on an untracked-file
   collision, report it.

2. **Rebase:**

   ```bash
   git rebase "REMOTE/<base>"
   ```

3. **Restore by SHA — only if sub-step 2 succeeded and sub-step 1 stashed.** Never apply on
   top of an in-progress rebase.

   ```bash
   git stash apply <SHA from sub-step 1>
   ```

4. **Drop your entry — only after sub-step 3 succeeded**, re-finding it by tag:

   ```bash
   n=$(git stash list --format='%gd %gs' | grep -F '<TAG from sub-step 1>' | head -1 | cut -d' ' -f1)
   if [ -n "$n" ]; then git stash drop "$n"; else echo "TAG_GONE — nothing dropped"; fi
   ```

   If sub-step 3 conflicted, do not drop: the entry stays until the user has kept the changes.

### 2a. A conflict only in generated files: regenerate, then continue

If sub-step 2 stops on conflicts, first try this. It needs the repo's generated files, from the
`## generated` section of `.claude/project-facts.md`. If that section is missing, gather it
once as in `${CLAUDE_SKILL_DIR}/references/project-facts.md`; if it says `none`, or the repo
has no generators, skip 2a and use the conflict report below.

Repeat for each rebase step that stops, until the rebase finishes or a check fails.

1. List the conflicted files: `git diff --name-only --diff-filter=U`. **Stop** if the list is
   empty: the rebase stopped for another reason (a failed `exec`, an unwritable file).

2. Every listed path must be a generated file from the facts (a listed folder covers the files
   under it). Any other path → **stop**, conflict report.

3. A **mixed file** (hand-written prose around a generated block) is regenerated only inside the
   block, so every conflict marker must sit inside it. With the file's markers from the facts:

   ```bash
   awk -v S='<start marker>' -v E='<end marker>' '
     $0==S {s++; inb=1; next}
     $0==E {e++; inb=0; next}
     /^(<<<<<<<|\|\|\|\|\|\|\||=======|>>>>>>>)( |$)/ && !inb {bad++}
     END {if (s!=1 || e!=1 || bad) {print "PROSE_CONFLICT"; exit 1} else print "BLOCK_ONLY"}' <file>
   ```

   `PROSE_CONFLICT`, no output, or a non-zero exit (e.g. one side deleted the file) → **stop**.

4. A whole generated file (not a mixed one) still holds conflict markers, which can break a
   generator that reads its own output (a lockfile). Take one side first —
   `git checkout --ours -- <whole generated files>` — the generator rewrites it anyway.
   Then snapshot the untracked files and run the generator for each conflicted file (a
   generator reading code in the tree needs its sources merged — check 2 guarantees that):

   ```bash
   git ls-files --others --exclude-standard | sort > "${TMPDIR:-/tmp}/rebase-untracked-before"
   ```

   then each generator command from the facts. A non-zero exit → **stop** and show its output.

5. Check the result before staging:

   ```bash
   git diff --name-only --diff-filter=U
   git diff --name-only
   git ls-files --others --exclude-standard | sort | comm -13 "${TMPDIR:-/tmp}/rebase-untracked-before" -
   git grep -n -E '^(<<<<<<<|[|]{7}|=======|>>>>>>>)( |$)' -- <conflicted files> && echo MARKERS_LEFT
   ```

   **Stop** if `MARKERS_LEFT` prints, or if the second or third list holds a path that is not in
   the first: the generator rewrote a file this step did not conflict on, so the tree was
   already stale. Report it; do not stage or revert it. (Not `git status`: it also lists files
   that merged cleanly.)

6. Stage and continue:

   ```bash
   git add <conflicted files>
   GIT_EDITOR=true git rebase --continue
   ```

   - Rebase finished (exit 0, no rebase in progress) → sub-step 2 succeeded; go on to 3 and 4.
   - The next step stopped on conflicts → run 2a again for it.
   - Anything else (non-zero, no conflicted files, e.g. an empty step) → **stop** and report.
     Never skip a step.

   Record each step resolved this way (commit subject and files) for Step 6.

### A conflict 2a does not resolve

- Stop and report the conflicting files, and which 2a check failed, if any.
- Never auto-resolve. Do **not** run sub-steps 3 or 4: the auto-stash stays on the stack under
  your tag; after resolving or aborting, recover it with `git stash apply <SHA>`.
- Suggest `git rebase --abort` if the user wants to bail out.

If `git stash apply` (sub-step 3) conflicts, report the files and let the user resolve; the
entry is still on the stack, so nothing is lost.

## Step 5: Check the rebased tree

Only when Step 4 finished (rebase done, auto-stash restored):

```bash
bash "SCRIPTS/local-checks.sh"            # default: the repo's quick checks
bash "SCRIPTS/local-checks.sh" --full     # with --test: quick + full
```

The last line says what happened:

- `LOCAL_CHECKS_OK` → passed.
- `LOCAL_CHECKS_NONE` → say "no local checks configured".
- `MALFORMED_CHECKS` → show the lines it named, fix just those (with the user's OK), re-run.
- `NO_PROJECT_FACTS` / `NO_CHECKS_SECTION` → the repo's checks are not written down yet. Follow
  `${CLAUDE_SKILL_DIR}/references/project-facts.md` once (find, confirm, write), then re-run.
  If the user declines to write a file, say the checks did not run — never that they passed.
- `LOCAL_CHECKS_FAILED: <names>` → **stop** and show the failing checks with their output. The
  rebase stays done; do not abort or undo it.

The checks read the working tree, so a restored auto-stash is included. If a check regenerated
files, leave them unstaged and say so.

## Step 6: Report

`git log --oneline -10`, then: the base you rebased on (and that it was a fallback, if so), the
Step 5 result, and every step 2a resolved by regenerating. Say whether the rebase was a no-op.

If the branch moved onto a new base (the old one was deleted) and has a PR, say its base may
need updating: `gh pr edit --base DEFAULT`.

## Rules

- Never `git stash pop`; never address a stash by position; never apply or drop an entry that
  is not yours.
- Never auto-resolve a conflict outside the generated files the project lists.
- Never push. Callers push with a pinned lease.
- Acceptance cases this text must satisfy: `references/acceptance.md`.
