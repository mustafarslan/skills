---
description: Explain what pr-pulse does and list its commands, in one screen. Use when the user says "/pr-pulse:help" or asks how pr-pulse works.
disable-model-invocation: true
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/scripts/pr-pulse help)
---

The pr-pulse hook normally answers this command before it reaches you. You are
reading this because the hook did not run. Run this command once, then reply
with its output and nothing else:

${CLAUDE_PLUGIN_ROOT}/scripts/pr-pulse help
