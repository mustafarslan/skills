# park

**Beta · macOS · Claude Code only.**

At the end of the day, run `/park`. Every Claude Code session on your Mac is saved and shut down, and
Terminal quits. The next morning, run `/park --resume`. Each conversation reopens in its own Terminal
window, and restarts the watchers, background shells and scheduled jobs it was running.

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

## Good to know

- **Only Terminal.app.** iTerm and other terminals aren't supported yet.
- **One window per interactive session on resume.** Restoring tabs would need macOS Accessibility
  permission, which park doesn't ask for.
- **Your data stays on your Mac,** in `~/.claude/park/`.
- **Later:** `/park` replaces the personal `/pause` skill. Its per-workstream tracker updates aren't
  part of park yet.
