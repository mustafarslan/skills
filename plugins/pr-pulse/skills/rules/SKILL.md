---
description: Show or change pr-pulse's PR rules for one repo - per-repo settings pr-pulse enforces (auto-review on/off, merge auto/ask/never, feedback and bot rounds, review bots, ignored authors) and plain-language rules every job for that repo follows. Use when the user says "/pr-pulse:rules", "pr rules for this repo", "change how pr-pulse handles a repo", or right after a new repo is mapped.
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/scripts/pr-pulse *), AskUserQuestion
---

# pr-pulse rules

`P` is `${CLAUDE_PLUGIN_ROOT}/scripts/pr-pulse`. Be friendly and brief.

The repo is `$ARGUMENTS` (owner/name or a path); with no argument, use the current folder's
repo. `P rules list` shows which repos have rules.

1. Run `P rules <repo>` and show its output as it is.
2. Ask with **one AskUserQuestion** (multiSelect) what to change:
   - **Auto-review**: "Whether pr-pulse reviews others' PRs here on its own (on / off)"
   - **Merging**: "auto (merge when your rules pass) / ask (ask you first) / never"
   - **Rounds**: "Automatic feedback rounds and review-bot rounds (0–10)"
   - **Plain rules**: "Sentences every job for this repo follows, e.g. 'Run the bank-rule tests before approving'"

   Then one AskUserQuestion per picked item, at most 4 per call, with the current value marked.
   For plain rules: options **Add a rule** (they type it in Other, word for word), **Remove a
   rule** (list the numbered rules in the question; they type the number), and **Keep as is**.
   For review bots and ignored authors, they type the logins in Other, comma-separated.
3. Apply each answer with exactly one command:
   - `P rules set <repo> <key> <value>`: keys `auto_review`, `merge`, `feedback_rounds`,
     `bot_rounds`, `review_bots`, `ignore_authors`
   - `P rules unset <repo> <key>` to go back to the global value
   - `P rules add <repo> <the rule exactly as they typed it>` / `P rules rm <repo> <n>`
4. Reply with the final `P rules <repo>` output and one line: "New jobs for <repo> follow these
   from the next check (within a minute)."

Never write a rule they did not type or pick, never reword their rule, and never change
another repo.
