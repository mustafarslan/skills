# Step 3 reviewers — prompts and commands

Substitute `BASE` (the resolved base branch) and `REMOTE` (the base remote from
git-context.sh) as literals everywhere below. Reviewers see none of this conversation.

## The change set every reviewer reads

> Review the **complete change set** on this branch. `git diff HEAD` alone is empty once work is
> committed and never shows untracked files, so read all three sources:
> - `git diff "REMOTE/BASE...HEAD"` — everything already committed on the branch
> - `git diff HEAD` — uncommitted work, staged and unstaged
> - `git status --porcelain` — then open each untracked (`??`) file directly; a new file is part
>   of the change set and no diff command shows its contents
>
> The repository is the current working directory. Do not fetch remote PRs, and change nothing.

## Report format (A and B)

> Report findings in this exact format, which overrides any format in your instructions:
>
> **Critical** (bugs, security, breaking changes):
> - `file:line` — one-line summary + brief why
>
> **Improvement**:
> - `file:line` — one-line summary + brief why
>
> **Nit**:
> - `file:line` — one-line summary
>
> Write "none" for an empty group. Under 500 words. End with one line: "Approve" or
> "Request changes".

## Agent A — correctness and test coverage

`Agent` with `subagent_type: pr-self-reviewer`, description `Local branch review (correctness +
coverage)`, prompt: the change-set block, then

> Cover correctness, edge cases and error handling, testability, efficiency. Name any test that
> should exist and does not, but do not write it.

then the report format. The agent definition carries the fail-open lens; do not restate it.

## Agent B — conventions, architecture and invariants

`Agent` with `subagent_type: pr-architect`, description `Local branch review (conventions +
architecture)`, prompt: the change-set block, then

> This is a diff review, not a pre-code design review: apply your lens to what the diff does.
> Read the project rule for every subsystem the diff touches — the diff may not open a file that
> loads it. Check the change against those invariants, any tenancy or isolation boundaries, and
> whether it needs a decision record that is missing. Also cover performance and security.

then the report format.

## When the agent types are not installed

If `Agent` rejects `pr-self-reviewer` or `pr-architect` (the skill was copied without the
repository's `agents/` folder), dispatch `general-purpose` instead, putting the agent file's
body in front of the prompt. The files are `${CLAUDE_SKILL_DIR}/../../agents/<name>.md` in a
plugin install; if they cannot be found, prepend: "You are a read-only reviewer. Do not edit,
write, stage, stash, commit, fetch or push; read-only commands only. Flag only what affects
correctness or the change's goal." Say in Step 4 which reviewers ran as fallbacks.

## Reviewer C — Codex adversarial review (optional)

Probe first, in its own Bash call before the dispatch message:

```bash
CODEX_COMPANION=$(ls -d ~/.claude/plugins/cache/openai-codex/codex/*/scripts/codex-companion.mjs 2>/dev/null | sort -V | tail -1)
if [ -n "$CODEX_COMPANION" ]; then node "$CODEX_COMPANION" setup --json 2>/dev/null | jq -r '.ready // false'; else echo "no-codex"; fi
```

`no-codex` or `false` → skip C silently; never suggest installing or logging in. `true` → in the
dispatch message, a foreground Bash call:

```bash
CODEX_COMPANION=$(ls -d ~/.claude/plugins/cache/openai-codex/codex/*/scripts/codex-companion.mjs 2>/dev/null | sort -V | tail -1)
if [ -z "$CODEX_COMPANION" ]; then echo "Codex companion not found — skipping adversarial review"
elif ! git diff --quiet HEAD || [ -n "$(git ls-files --others --exclude-standard)" ]; then
  node "$CODEX_COMPANION" adversarial-review --wait
else
  node "$CODEX_COMPANION" adversarial-review --base "REMOTE/BASE" --wait
fi
```

Pick the base explicitly on a clean tree: Codex's default diffs against the *local* base ref,
which is stale in a worktree, and would review already-merged files. A probe that said ready and
a review that then fails (usage limit, expired auth, no output) is not a silent skip: Step 4 says
the Codex review did not run, and why.

## Reviewer D — agy adversarial review (optional)

agy is the Antigravity CLI, a second opinion from another model family, reached through
`agy-ask`, read-only (see the `agy` skill). Never pass `--boost`, `--allow-write` or
`--allow-delete` here.

Before the dispatch message, `command -v agy-ask`. Not found → skip D silently and never suggest
installing it. Found → write the brief to a file **outside the repository** (the session's
scratchpad, or `mktemp`), so no reviewer sees it as an untracked file:

> You are an adversarial reviewer of a pull request in the repository at the workspace root.
> Read the change set with read-only commands: `git diff "REMOTE/BASE...HEAD"`, `git diff HEAD`,
> `git status --porcelain` and the untracked files it lists. Change nothing.
>
> Goal of the change: <one or two sentences from the branch, the issues and the commits>.
>
> Challenge the **approach and design**, not the lines: the assumptions it makes, the trade-offs
> it picks, where it breaks under real conditions (load, concurrency, partial failure, bad
> input, upgrades of existing installs). Flag only what affects correctness or the goal above;
> an empty answer is fine. Ranked, most serious first, each with `file:line` where there is one,
> under 400 words.

Then, in the **same message** as A, B and C, a foreground Bash call:

```bash
agy-ask --cwd "$(git rev-parse --show-toplevel)" -f <brief file>; echo "agy_exit=$?"
```

Read the outcome:

| Result | Do |
|---|---|
| exit 0 with text | Findings go into the Step 3 merge tagged `agy adversarial`. |
| `AGY_UNAVAILABLE` (127) | Skip silently. |
| `AGY_FAILED` (2), `AGY_QUOTA` (3), `AGY_AUTH` (4) | Carry on without it, and **say which one happened** in Step 4. Never retry a quota or auth failure; never suggest upgrading a plan or logging in. |
| `AGY_TREE_MODIFIED` on stderr | Stop the flow and tell the user at once, with the paths. |

Never report a failed agy review as a clean one, and never apply a fix from it without the
user's Step 4 decision. Check every `file:line` it cites before you present it.
