---
description: Suggest which Claude session should be the PR session for each repo, from the sessions running right now, and save the mapping pr-pulse uses across all repos. Use when the user says "/pr-pulse:map", "map my repos", or asks which session handles PRs for a repo.
argument-hint: "[set <slug|path> --session <name>] [rm <slug>]"
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/scripts/pr-pulse *), AskUserQuestion
---

# pr-pulse map

pr-pulse knows every live Claude session (from `claude agents --json`) and which GitHub
repo each one sits in. The mapping says which repos pr-pulse watches, and which session
should get PR work for each one.

If `$ARGUMENTS` starts with `set` or `rm`, run
`${CLAUDE_PLUGIN_ROOT}/scripts/pr-pulse map $ARGUMENTS`, reply with its output, and stop.

Otherwise:

1. Run `${CLAUDE_PLUGIN_ROOT}/scripts/pr-pulse map`. It groups the live sessions by repo and
   marks the suggested PR session with →.
2. Ask the user once, with one AskUserQuestion that has a question for each repo that is NOT
   mapped yet (at most 4; mention any others in one line). Options: the suggested session
   (Recommended), up to 2 other sessions in that repo, and "Watch, no PR session". Put the
   session's status and branch in each option's description.
3. For each answer, run `${CLAUDE_PLUGIN_ROOT}/scripts/pr-pulse map set <slug> --session <name>`,
   or without `--session` for "Watch, no PR session".
4. Ask once, for all newly mapped repos together, whether PRs opened there should be announced
   in Slack without `/pr-pulse:on`. For each yes, run
   `${CLAUDE_PLUGIN_ROOT}/scripts/pr-pulse map set <slug> --announce`.
5. Ask once, for all newly mapped repos together (multiSelect), whether to set PR rules for any
   of them now: per-repo settings such as auto-review on/off or merge auto/ask/never, and plain
   rules every job there follows. For each pick, follow `/pr-pulse:rules <slug>`.
6. Reply with the `pr-pulse status` mapped-repos section, plus one line saying that a mapped
   session gets work only after it runs `/pr-pulse:join`, and that a repo with no live session
   can get one from `/pr-pulse:spawn <slug>`.

Never map a repo the user did not pick, and never register a session from here.
