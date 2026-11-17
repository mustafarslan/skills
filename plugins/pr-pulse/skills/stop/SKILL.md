---
description: Shut pr-pulse down in one step: stop the daemon (stays off after reboot), every inbox watcher, the background sessions pr-pulse started, and announcements. Nothing is uninstalled. Add --keep-workers to leave running workers alone.
argument-hint: "[--keep-workers]"
disable-model-invocation: true
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/scripts/toggle.sh *)
---

The pr-pulse hook normally answers this command before it reaches you. You are
reading this because the hook did not run. Run this command once, then reply
with its output and nothing else:

${CLAUDE_PLUGIN_ROOT}/scripts/toggle.sh stop ${CLAUDE_SESSION_ID} $ARGUMENTS
