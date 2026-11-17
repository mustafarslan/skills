---
description: Bring pr-pulse back after /pr-pulse:stop: daemon on, dispatching, announcements on.
disable-model-invocation: true
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/scripts/toggle.sh *)
---

The pr-pulse hook normally answers this command before it reaches you. You are
reading this because the hook did not run. Run this command once, then reply
with its output and nothing else:

${CLAUDE_PLUGIN_ROOT}/scripts/toggle.sh start ${CLAUDE_SESSION_ID} $ARGUMENTS
