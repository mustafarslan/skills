# park

**Beta · macOS and Windows · Claude Code only.**

At the end of the day, run `/park`. Every Claude Code session on your computer is saved and shut down, and
Terminal quits (on Windows, their tabs close). The next morning, run `/park --resume`. Each conversation
reopens in its own Terminal window (on Windows, a tab each in one Windows Terminal window), and restarts the
watchers, background shells and scheduled jobs it was running.

## Install

Install this repo's plugin (see the [README](../../../README.md#install)), or copy the skill:
`cp -r skills/park ~/.claude/skills/`. Then run `/reload-plugins` in your open sessions. The first `/park` asks macOS to let Claude control
Terminal. Allow it once: **System Settings → Privacy & Security → Automation**.

## Use it

| You type | What happens |
|---|---|
| `/park` | Shows what it will park, asks once, then stops every session (the one you typed in goes last) and quits Terminal |
| `/park --dry-run` | Shows what it would park, and does nothing |
| `/park --only pr-payments` / `--exclude docs` | Parks only some sessions. pr-pulse and your other windows stay as they are |
| `/park --notes` | First asks each idle session to write down its next step |
| `/park --resume` | Brings back the newest park's sessions |
| `/park --resume --day yesterday` (or `2026-11-10`) | A park from that day. If there were several, it asks which |
| `/park --resume --name payments` | Just the sessions with that in their name |
| `/park --resume --pick` | You pick which sessions come back |

Parks are kept for 30 days. Change that with `park config retention_days 14`. A park with a
session you never brought back is kept until you do, so its saved work isn't lost.

## What comes back, and what doesn't

**Comes back:**
- **Each conversation, whole:** the same session, its full history, the same folder.
- **Whatever was running inside it**, started again from the beginning:
  - watchers, such as pr-pulse's inbox watcher or a PR watch;
  - background shells, such as a dev server;
  - scheduled jobs (crons).
- **Your work, untouched.** Nothing is committed, stashed or reset. Uncommitted changes are also
  saved as a patch, and each session checks its folder on resume and tells you if anything moved.

**Doesn't come back:**
- A running process can't be frozen and continued later. A turn that was half done, a test run or a
  build is cut off. `/park` warns you about these first, so you can wait for them.
- A restarted watcher begins fresh. It doesn't remember what it had already seen.

**Keeps running anyway:**
- Background services outside your sessions, such as pr-pulse's.
- pr-pulse's own review workers aren't reopened. pr-pulse is switched off while you're parked, and
  switched back on with `--resume`. It then picks up its unfinished jobs itself.

## On Windows

- **Windows Terminal, and Git Bash for Claude's Bash tool.** `/park` runs through the Bash tool, and needs
  Python 3 (`python3`, `python` or `py`) and `git`. No permission prompt: nothing like macOS Automation is needed.
- **Tabs, not windows.** `/park --resume` opens every interactive session as a tab of one Windows Terminal
  window named `park`. Each tab starts `claude --resume` itself (so the first message arrives whole, whatever it
  holds), and leaves a PowerShell prompt when the session ends, as a Terminal window leaves a shell.
- **Stopping a session** is a Ctrl+C on its console, as SIGINT is on the Mac; if it doesn't stop, it is ended.
  A session park can't send a Ctrl+C to (no console) is left running and reported.
- **Windows Terminal is never quit.** Only the parked sessions' own tabs close, and only when nothing but idle
  shells is left in them. A tab running something else stays open, like a busy shell in Terminal.
- **Fresh environment.** A tab opened from inside a session would inherit that session's `CLAUDE_CODE_*`
  markers (and stop saving its transcript). park takes them out; variables you set yourself stay.
- **PowerShell tool commands** can't be read from outside (their text isn't on the process's command line), so
  they are listed as not restarted. Bash tool commands come back as on the Mac.
- **Your data stays on your PC,** in `%USERPROFILE%\.claude\park\`.

## Good to know

- **Only Terminal.app on the Mac** (Windows Terminal on Windows). iTerm and other terminals aren't supported yet.
- **One window per interactive session on resume** (on the Mac). Restoring tabs would need macOS
  Accessibility permission, which park doesn't ask for.
- **Your data stays on your Mac,** in `~/.claude/park/`.
- **Later:** `/park` replaces the personal `/pause` skill. Its per-workstream tracker updates aren't
  part of park yet.
