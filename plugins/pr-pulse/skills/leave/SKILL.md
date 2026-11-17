---
description: Stop this session from taking new pr-pulse PR work, and stop its inbox watcher.
disable-model-invocation: true
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/scripts/pr-pulse *)
---

Run `${CLAUDE_PLUGIN_ROOT}/scripts/pr-pulse leave` once and reply with its output and nothing else.
