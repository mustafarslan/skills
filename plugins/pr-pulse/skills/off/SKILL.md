---
description: Turn pr-pulse off for this session (and for this worktree, if worktree mode was on).
disable-model-invocation: true
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/scripts/toggle.sh *)
---

The pr-pulse hook normally answers this command before it reaches you. You are
reading this because the hook did not run. Run this command once, then reply
with its output and nothing else:

${CLAUDE_PLUGIN_ROOT}/scripts/toggle.sh off ${CLAUDE_SESSION_ID}
