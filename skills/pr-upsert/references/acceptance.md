# pr-upsert — acceptance cases

What it expects from what it calls:

- **rebase** — takes the base branch as its argument; stops on conflicts it does not resolve;
  never pushes.
- **commit** — runs the checks the change needs, commits, pushes with a verified explicit
  refspec and a pinned lease, lists overlapping branches.
- **pr-self-reviewer**, **pr-architect** (repository `agents/`) — read-only reviewers (Read,
  Grep, Glob, Bash; no Edit/Write). `general-purpose` with the same text when not installed.
- **pr-feedback** (optional) — works the comments on the PR with the user, then pushes fixes.
- **Codex plugin**, **agy** (optional) — adversarial reviews; their absence is harmless.

| Situation | Must end with |
|---|---|
| Run on the default branch (`main` or `master`) | Refused. |
| No PR yet, `$ARGUMENTS` names a base | `BASE` is that branch for every later step; `rebase` receives it. |
| No `.claude/project-facts.md` | Facts gathered, confirmed once, written in Step 0; nothing guessed later. |
| Facts say `issues required: no` | No issue asked for; the template's issues section says exempt or is filled from any key found. |
| Branch name carries an issue key that is Done/Canceled | Not linked; the user is asked for a replacement or the housekeeping call. |
| Product-facing change, issues required, none derivable | Stops and asks; never posts. |
| No tracker MCP and not GitHub Issues | Keys shown for confirmation; Step 10 skipped silently. |
| Rebase conflicts | Stops; surfaces them; nothing reviewed. |
| Reviewer agents not installed | `general-purpose` fallback with the same text; Step 4 says so. |
| A reviewer changed the tree | Stops and surfaces the diff before triage. |
| Codex probe says ready but the review fails | Step 4 says the review did not run and why. |
| `agy-ask` not installed | agy skipped silently. |
| agy returns `AGY_QUOTA` | Flow continues; Step 4 says agy hit its quota; no retry, no upsell. |
| User replies "fix 1,2 skip 3" | 1 and 2 applied; 3 recorded in "where a reviewer should look hardest". |
| Diff touches a mapped code area | Doc edits proposed, approved, then committed in the same change. |
| Image trigger file changed and the build fails | Stops before commit. |
| Repo has no PR template | The neutral template's layout is used. |
| Fork checkout | PR found and opened on `BASE_REPO` (upstream) with `--head owner:branch`; every `gh` call passes `--repo BASE_REPO`. |
| Template without an Issues or "look hardest" section | No section added; links and skipped findings go at the end of the Summary. |
| `issues required: no`, no key in the branch | Issues section says `None`, not "housekeeping". |
| Uncommitted work present before the review | Not mistaken for a reviewer's edit (compared with the pre-review baseline). |
| Bot comments only from an earlier push | Not counted as this cycle's feedback. |
| Bot login written as `name[bot]` in the facts | Still matches the GraphQL login `name`. |
| Sticky comment beyond the first 30 comments | Found (`--paginate`). |
| Editing the sticky comment is refused | Says the re-run was NOT requested. |
| Update mode | Body reconciled to the current diff, images kept, template layout enforced, no approval gate. |
| Overlapping branch with a real conflict | Its author requested and told which file conflicts; non-conflicting files never called conflicts. |
| Repo runs no CI | Says so after 3 minutes and continues. |
| Any CI check fails | Names + URLs shown; stops; no auto-fix. |
| `pr-feedback` pushed fixes | No AI review requested this cycle. |
| Sticky review comment exists | Re-run requested by ticking its checkbox, not by a new trigger comment. |
| Any commit, body or comment | No AI attribution. |
