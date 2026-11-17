---
description: Resume pr-pulse after /pr-pulse:pause, so the daemon dispatches PR work again.
disable-model-invocation: true
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/scripts/toggle.sh *)
---

The pr-pulse hook normally answers this command before it reaches you. You are
reading this because the hook did not run. Run this command once, then reply
with its output and nothing else:

${CLAUDE_PLUGIN_ROOT}/scripts/toggle.sh resume ${CLAUDE_SESSION_ID}
