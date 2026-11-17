---
description: Turn pr-pulse's automatic reviews of other people's PRs off or on (off when you need the Mac for your own work). Requests are still queued; your own PRs carry on.
disable-model-invocation: true
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/scripts/toggle.sh *)
---

The pr-pulse hook normally answers this command before it reaches you. You are
reading this because the hook did not run. Run this command once, then reply
with its output and nothing else:

${CLAUDE_PLUGIN_ROOT}/scripts/toggle.sh auto-review ${CLAUDE_SESSION_ID} $ARGUMENTS
