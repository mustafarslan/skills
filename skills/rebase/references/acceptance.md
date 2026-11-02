# rebase — acceptance cases

Read the skill against each situation; each must end as stated.

| Situation | Must end with |
|---|---|
| On the default branch (`main`, `master`, …) or a detached HEAD | Stop; nothing to rebase. |
| Several remotes, none named `origin` | `CONTEXT_FAILED`; ask which remote. |
| Fork checkout (`origin` = fork, `upstream` = project) | Rebases on `upstream/<base>`. |
| `$ARGUMENTS` is `--tests` | Stop; never read as a branch. |
| `$ARGUMENTS` names a branch that does not exist on the remote (typo) | Stop and ask; no silent fallback. |
| `$ARGUMENTS` is `origin/main` | Read as `main`. |
| A tracked file touched but not changed | Not "dirty"; no stash, no `STASH_NOT_FOUND`. |
| A suffixed auto-stash left on **this** branch by an earlier run | Stop and ask; never apply or drop it. |
| Lockfile conflict listed as generated | `--ours` taken, generator rerun, staged, rebase continues. |
| `## checks` line with a trailing `<!-- -->` comment | The comment is stripped; never executed. |
| Malformed line under `### quick`/`### full` | `MALFORMED_CHECKS`; only those lines fixed, the file is not rewritten. |
| Base branch deleted on the remote | Says so, rebases on the default branch. |
| Dirty tree, clean rebase | Stash tagged, rebase, `git stash apply <sha>`, drop by tag; tree as before plus the new base. |
| Another session's stash on top during the run | Yours is restored and dropped; theirs untouched. |
| Entry named exactly `rebase-skill-autostash` already in the stack | Stop and ask; never apply or drop it. |
| Conflict only in a generated file listed in the facts | Regenerated, staged, rebase continues; reported in Step 6. |
| Conflict in a generated file **and** a source file | Stop; report both; stash stays on the stack. |
| Conflict inside the hand-written part of a mixed file | Stop (`PROSE_CONFLICT`). |
| Conflict, and the repo lists no generated files | Stop with the conflict report; nothing regenerated. |
| Rebase stops with no conflicted files | Stop; never skip the step. |
| No `.claude/project-facts.md` | Facts gathered, confirmed once, written; checks then run. Declined → "checks did not run". |
| Facts say `## checks` `none` | "No local checks configured"; no question asked. |
| Local checks fail after a clean rebase | Report `LOCAL_CHECKS_FAILED`; rebase stays done. |
