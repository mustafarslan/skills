---
name: park
description: Park every Claude Code session on this computer (a Mac with Terminal, or Windows with Windows Terminal) at the end of the day - snapshot each one (its folder and branch, uncommitted work as a patch, the watchers, background shells and crons running inside it), shut them all down and quit Terminal (on Windows, close their tabs) - then bring them back later with /park --resume, each in its own Terminal window (on Windows, a tab each in one window), restarting what was running. Use when the user says "/park", "park everything", "park my sessions", "shut everything down for today", "/park --resume", "bring my sessions back", "resume yesterday's sessions", or asks to resume a park from another day or a session by name. Flags --dry-run, --only NAME, --exclude NAME, --notes, --label TEXT; for resume --day DATE, --name PART, --pick, --unresumed.
allowed-tools: Bash(${CLAUDE_SKILL_DIR}/scripts/park *), AskUserQuestion, SendMessage, ListAgents, TaskStop
---

# park — put the day's sessions to rest, bring them back tomorrow

Be friendly, positive, concise and brief, with no chitchat.

`P` below means `${CLAUDE_SKILL_DIR}/scripts/park`. Every command prints JSON or one line per item.

**What "as they were" means**, said once when it matters: each conversation comes back whole (same
session, same history, same folder). Work running *inside* a session (watchers, background shells,
subagents, crons) ends when it stops; park writes it down and starts it again on resume, from the
beginning. A turn mid-way, a long build or a test run is cut off. pr-pulse's background service and
other launchd agents keep running.

**On Windows** (Windows Terminal, Git Bash for the Bash tool): "quit Terminal" below means closing the parked
sessions' own tabs (Windows Terminal itself is never quit), and resumed sessions open as tabs of one Windows
Terminal window named `park`. A tab whose shell still runs something other than the session stays open. Commands
the PowerShell tool runs can't be read from outside, so they are listed as not restarted.

## /park

1. **Can we?** Run `P doctor`. If `ok` is false, say each problem in one line (the Automation
   permission one, and on Windows the Windows Terminal one, tells the user exactly where to click) and stop.
   Nothing is touched yet.
2. **Snapshot.** Run `P plan` with the user's flags (`--only X`, `--exclude X`, `--label "…"`). It
   creates a planned park and stops nothing. From its JSON:
   - `parked`: sessions that will be parked (with branch, changed files, untracked files, and in
     `restart` / `cron_prompts` the exact commands and crons that will be started again on resume:
     only watchers and servers; in `not_restarted` the one-off waits and scripts that end by
     themselves, and anything it could not read whole, none of which comes back);
   - `skipped`: left alone, with the reason (pr-pulse's own workers: pr-pulse requeues their jobs);
   - `busy`: sessions in the middle of a turn;
   - `long_running`: test runs, builds, ship and deploy scripts that parking would cut off. These
     are never started again on resume; the session is told they were cut off.
3. **--notes only.** For each idle session in `parked` (not this one), SendMessage it: "We're parking
   for the day. In one or two sentences, what's your next step? Save it with
   `P note --park <id> --sid <its sid>` (text on stdin), then stop." Give them a minute; don't wait
   for busy ones. Say which ones answered. (Write `P` out as its full path in the message: the other
   session doesn't know it.)
4. **Ask once** (AskUserQuestion), with the counts in the question: "Park N sessions (skip M:
   pr-pulse workers…), switch pr-pulse off and quit Terminal?" (on Windows: "…and close their tabs?") Before it, list every `restart`
   command and cron prompt under its session, so nothing is started again on resume unseen, and say
   how many `not_restarted` commands each has (show them if the user asks). Options:
   - **Park now (Recommended)**
   - **Wait for busy ones** — only when `busy` or `long_running` is not empty; name them. Then wait
     (check `P plan` again later, or ask the user to come back), and ask again.
   - **Cancel** → `P cancel --park <id>`.
   With `--only`/`--exclude` the question says instead: "Park these N sessions? pr-pulse and your
   other windows stay as they are."
   `--dry-run` stops before this question: show the summary and run `P cancel --park <id>`.
5. **Stop this session's own background work.** The snapshot already recorded it for resume. Stop
   each of this session's Monitors, background Bash tasks and subagents with TaskStop.
6. **Go.** `P shutdown --park <id>`. Reply in one line: "Parking N sessions now; this one goes last.
   Tomorrow: `/park --resume`." Then end your turn and do nothing else: the coordinator stops this
   session too, after it is idle.

## /park --resume

1. **Which park?** `P pick` with the user's flags:
   - none: the newest park with sessions not resumed yet;
   - `--day yesterday|today|YYYY-MM-DD`; if the answer has `choose` (several parks that day), ask
     which with AskUserQuestion (time, label, how many sessions);
   - `--name PART`: sessions with that in their name, newest park first;
   - `--unresumed`: everything not resumed yet, any park.
   Empty: say so in one line, and offer `P list`.
2. **Show the table** (one row per session): name · interactive/background · branch · drift (`drift`
   says what moved since parking) · watchers and crons to restart · warnings (a folder that is gone
   opens in its repo instead). Rows with `running_now` are already open; say they'll be left alone.
3. **Ask once**: "Bring back these N sessions?" Options: **Bring them all back (Recommended)** /
   **Let me pick** (then one multiSelect question with the names, up to 4 per question) / **Not now**.
   `--pick` goes straight to picking.
4. **Go.** `P resume --park <id>`, or `P resume --sid <sid> …` for a pick or a name search. Each
   interactive session opens in its own Terminal window (on Windows, a tab in the Windows Terminal
   window `park`); background ones come back in the background. Each one's first message tells it to check its folder for drift, restart its watchers
   and crons, and continue. pr-pulse is switched back on if it was on.
5. Reply with its lines as they are, plus one line: "Each session checks its folder and restarts its
   watchers first; background ones: `claude agents`."

## Also

- `P list`: parks kept (30 days by default). `P show --park <id>`: everything stored about one park.
- `P config`: settings; `P config retention_days 14`, `P config quit_terminal claude` (close only
  Claude's windows) or `none`, `P config busy_wait_s 30`.

## Rules

- Never commit, stash, push or reset anything. Uncommitted work stays in the folder and is copied
  to a patch (binary changes included); untracked files are listed, not copied, and each resumed
  session is told about them.
- A park with a session never resumed is never cleaned up, however old: its patch may be the only copy.
- The coordinator only signals a pid that `claude agents` still reports for that session; anything
  else is left alone and reported as not stopped. If any session was not stopped, Terminal is not
  quit (only the stopped sessions' windows close), so nothing still running is cut off.
- Never park without the one confirmation in /park step 4 (a full park quits Terminal).
- Never resume a session that is already running, and never pass flags to `claude --resume` beyond
  the session id and the prompt: any flag starts a copy instead.
- If a step fails, say what happened in one line and the next thing to try. Never claim a session
  was parked or resumed without the command saying so.
