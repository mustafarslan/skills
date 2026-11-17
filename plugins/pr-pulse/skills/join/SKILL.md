---
description: Make this Claude session take pr-pulse PR work (reviews, feedback, merges) for its repo whenever it is idle. Use when the user says "/pr-pulse:join", "make this the PR session", or when a pr-pulse spawn prompt asks for it.
argument-hint: "[--for session-name[,session-name]] [--general] [--repo owner/name]"
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/scripts/pr-pulse *), Bash(${CLAUDE_PLUGIN_ROOT}/scripts/inbox-watch.sh *), Monitor, ToolSearch
---

# pr-pulse join

1. Run `${CLAUDE_PLUGIN_ROOT}/scripts/pr-pulse join $ARGUMENTS`.
   - `--for contracts` makes this the PR session of the `contracts` session: it handles only the
     PRs that session opened, and those PRs wait for it. Several names: `--for a,b`.
   - With no `--for`, it is a general PR session: reviews of others' PRs, and PRs whose session
     has no PR session of its own. A plain re-join keeps an earlier `--for`; `--general` clears it.
2. If its output has a `NEXT:` line, start that inbox watcher with the **Monitor** tool. Load
   it with ToolSearch (`select:Monitor`) if it is deferred. Make the watch persistent (no
   timeout), with the exact command from the output. Don't start a second one if the output
   says a watcher is already running.
3. Reply in two lines: the role line from the output (which PRs this session takes), and that a
   job never interrupts: it is picked up after whatever the session is doing.

**When a watcher line says `pr-pulse: job N …`:**
- Run `${CLAUDE_PLUGIN_ROOT}/scripts/pr-pulse job show N` and follow it exactly. That covers
  `job start` first, the architecture-intent reminder, parking outward text in the outbox, and
  finishing with `job done` or `job fail`.
- If the user is in the middle of something in this session, finish their request first. The
  job waits.
