---
description: Start a named background Claude session that becomes the pr-pulse PR session for a mapped repo. Use when the user says "/pr-pulse:spawn owner/repo" or accepts a spawn offered by /pr-pulse:map.
argument-hint: "<owner/name>"
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/scripts/pr-pulse *)
---

Run `${CLAUDE_PLUGIN_ROOT}/scripts/pr-pulse spawn $ARGUMENTS` once and reply with its output.
If no repo was given, run `${CLAUDE_PLUGIN_ROOT}/scripts/pr-pulse status` and ask which mapped
repo to use.
