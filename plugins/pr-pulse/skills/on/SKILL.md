---
description: Turn pr-pulse on for this session, so pull requests opened here are announced in Slack #pr-review. Add "worktree" to keep it on for this git worktree across /clear and new sessions.
argument-hint: "[worktree]"
disable-model-invocation: true
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/scripts/toggle.sh *)
---

The pr-pulse hook normally answers this command before it reaches you. You are
reading this because the hook did not run. Run this command once, then reply
with its output and nothing else:

${CLAUDE_PLUGIN_ROOT}/scripts/toggle.sh on ${CLAUDE_SESSION_ID} $ARGUMENTS
