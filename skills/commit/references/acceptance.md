# commit — acceptance cases

| Situation | Must end with |
|---|---|
| On the default branch (`main` or `master`) | Stop and ask before committing; never pushed. |
| No `.claude/project-facts.md` | Facts gathered from the repo, confirmed once, written; no guessed command runs. |
| Repo with no checks (`## checks` `none`, areas `-`) | Commit proceeds; report says "none configured", not "passed". |
| Only `.md` or CI config changed | Lint, typecheck, local checks and tests skipped, and the report says so. |
| Formatter rewrites a file after staging | Step 4.5 shows a diff → re-stage → committed version equals the worktree. |
| A regenerated file is left unstaged | Step 4.4 prints it → stop. |
| Tests fail | Stop; nothing committed. |
| Push from a detached HEAD or the default branch | Refused with the guard message. |
| Another session fetched during the push | The pinned lease still protects a teammate's push. |
| The remote branch has a teammate's commit HEAD lacks (even after a fetch refreshed the baseline) | `REFUSING to push`; stop; never retried with a new SHA. |
| Push rejected (`stale info`) | Stop and report; never retried with a newly fetched SHA, never `--force`. |
| Fork checkout | Pushes to the fork (`origin`); overlap scan uses `upstream`. |
| Unstaged edits left in an area whose checks ran | Staged if they belong; otherwise the report says the checks saw them. |
| `remote` ≠ local HEAD after the push | Reported as a failure; never "pushed". |
| Rebase skill not installed (local-checks.sh missing) | Says the checks did not run; never "passed". |
| Overlap script fails (no gh, old git) | The user is told the check did not run; the commit stands. |
| `--no-push` | Committed; Steps 5 and 6 skipped and said so. |
| Commit message | No AI attribution trailer or line. |
