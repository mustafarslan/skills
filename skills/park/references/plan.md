For agents — no need to read.

# /park — park every Claude session, resume them later (team plugin, beta)

## Context

Today `/pause` (personal skill, `~/.claude/skills/pause/`) parks **one workstream from inside one
session**: it stops that session's Monitors, background tasks and subagents, snapshots its worktrees
(`git diff` patch, never commit/stash), and writes `~/.claude/resume/<ws>.md` with re-arm commands.

The owner wants more than that. At the end of the day they run `/park`. Every Claude session on the Mac
(10 today: 4 interactive in Terminal tabs, 6 background) is snapshotted and shut down, and Terminal
quits. Next morning, or later the same day, he runs `/park --resume`, and yesterday's sessions come
back in new Terminal windows. Whatever was running inside them comes back too: watchers, background
shells, crons, and plugin watchers such as pr-pulse's inbox watcher. A different day, a session name,
or a hand-picked subset can be chosen instead. The plugin keeps its own SQLite store and cleans up
after 30 days by default.

### Decisions

**The owner's (2026-11-10):**
- **Team plugin** in your-org/claude-plugins: beta, Claude Code only, macOS only.
- **Retire personal `/pause`** after `/park` ships, with a backup, the way retro replaced the
  personal retro skill.
- **Quit all of Terminal** on park. Terminal still asks if a shell is busy, and that dialog stays.
- **pr-pulse workers are not reopened.** `/park` switches pr-pulse off, and `--resume` switches it
  back on. pr-pulse then requeues its unfinished jobs itself (stale-job requeue).

**agy big (consulted, Gemini 4 Argon), adopted:**
- Shutdown runs in a **detached coordinator**, so the `/park` session can be parked last.
- A busy session gets **SIGINT, then waits** until its transcript is quiet, then SIGTERM. A turn is
  never cut off mid-write.
- The resume prompt goes in as a **positional argument** (`claude --resume <sid> "<prompt>"`).
  A SessionStart hook only adds context and doesn't start a turn, so nothing would re-arm.
- **Pre-flight the Automation permission** (osascript to Terminal) before stopping anything.
- **One window per resumed session.** Restoring tabs needs Accessibility permission, which
  breaks on team Macs.
- Track `resumed_at` per session. Add `--unresumed`. List the parks when one `--day` has several.
- Skip pr-pulse's spawned workers: `spawned=1` in pr-pulse's sessions table, or a cwd under
  `.claude/worktrees/pr-pulse-*`.
- Missing cwd: fall back to that repo's main checkout, and warn.
- Add `--dry-run`, `--only/--exclude`, and a resume summary table.

**Where I differ from agy:**
- agy would drop each session writing its own note. I keep it as **opt-in** (`--notes`), with
  host-side inspection as the default. The host side reads processes and transcripts, costs zero
  tokens and works even mid-turn, but it can't know the "next action" as well as the session itself.

### What "as they were" means (limit to state in the README and in the /park summary)
- Every conversation comes back as it was: the same session id, the full history, the same folder.
- Work running inside a session is ordinary processes, and parking ends them. That covers watchers,
  background shells, subagents and crons. `/park` writes down exactly what was running and starts
  it **again from scratch** on resume. It can't freeze a process mid-step. A half-finished turn, a
  long build or a test run is lost, and a restarted watcher doesn't remember what it already saw.
- Work running outside sessions keeps going: pr-pulse's background service, and launchd agents.
- So `/park` warns about sessions that are **busy**, and about long-running child processes such
  as test runs and builds. It offers "Wait for them / Park anyway / Skip those sessions".

## Design

### Package: `plugins/park/`
- `.claude-plugin/plugin.json` (0.1.0), `README.md`, `plan.md` (this plan, in the repo, as memory
  asks), a marketplace entry, and a README row: "beta · macOS · Claude Code only".
- `skills/park/SKILL.md`: `/park` and `/park --resume`, with friendly, brief AskUserQuestion steps.
- `scripts/park`: a CLI in stdlib Python 3. Subcommands: `inventory`, `snapshot`, `plan`,
  `shutdown` (starts the detached coordinator), `resume`, `list`, `show`, `gc`, `doctor`, `config`.
- Modules:
  - `db.py`: SQLite in WAL mode, `~/.claude/park/park.db`; `PARK_HOME` overrides it for tests.
  - `inventory.py`: `claude agents --json` (fields pid, cwd, kind, sessionId, name, status), plus
    pid → tty, plus each session's child processes.
  - `snapshot.py`: git state and patches, re-arm items, the last assistant message.
  - `terminal.py`: osascript calls (pre-flight, quit, open window).
  - `coordinator.py`: the detached shutdown sequence.
- **Reuse, copying the pattern rather than importing across plugins:**
  - pr-pulse `scripts/sessionui.py`: matching a pid's tty to a Terminal tab, and `do script`.
  - pr-pulse `scripts/core.py`: `list_sessions`, `run`, `repo_of`.
  - pr-pulse `scripts/dispatch.py`: `notify` (detached `Popen`, `start_new_session=True`).
  - `/pause` steps 2–3: the worktree snapshot rules and the resume-prompt shape.
- `tests/`: unit tests on a temporary home with fake `claude` and `osascript` on PATH, plus
  `run.test.sh` for the repo's `scripts/check.sh`.

### Store (`~/.claude/park/park.db`)
- `parks(id, at, label, host_note)`
- `sessions(park_id, sid, name, kind, cwd, repo_root, branch, head, dirty, patch_path, status_at_park,
  was_busy, skipped_reason, resume_prompt, rearm JSON, crons JSON, last_message, note, resumed_at)`
- `events(ts, kind, detail)`
- `config`: `retention_days` 30, `quit_terminal` "all", `notes` false, `busy_wait_s` 20.
- Patches go to `~/.claude/park/patches/<park>/<sid>.patch`, and untracked files are listed by path.
- **gc** runs at every command: it deletes parks older than `retention_days`, with their rows and
  patch folders.

### `/park` flow
1. **`doctor` pre-flight.** `claude` is on PATH, Automation permission for Terminal works
   (`osascript -e 'tell application "Terminal" to count windows'`), and the store is writable.
   On failure, say what to allow in one line and stop before touching anything.
2. **`inventory`.** List every live session, and mark the skipped ones with a reason:
   - pr-pulse spawned workers;
   - `--only` / `--exclude`.
3. **`snapshot`.** Host side, no tokens. For each session:
   - **Worktree:** cwd, repo root, branch, HEAD, `git status`, unpushed commits, and
     `git diff > patch`. Never commit, stash or push.
   - **Re-arm list:**
     - the session's child processes (`ps -o pid,ppid,command`): Monitor commands such as
       `inbox-watch.sh <sid>` and `pr-watch.sh <n>`, and background shells, saved as exact commands;
     - crons: `CronCreate` calls with no matching `CronDelete` in
       `~/.claude/projects/*/<sid>.jsonl`;
     - pr-pulse "joined" state, from pr-pulse's DB when it's installed.
   - **Context:** the last assistant message, shortened, and the busy/idle state.
   - **With `--notes`:** idle sessions also get a SendMessage asking them to write a short "next
     action" note through `park note --sid <sid>`, with a 60-second timeout. Busy sessions are
     skipped, and the report says which ones.
4. **Build each session's resume prompt.** It covers drift checks, the re-arm commands, the crons
   to recreate and the next action. It's stored, and printed in the summary.
5. **Summary and confirmation** in one AskUserQuestion: "Park 9 sessions (skip 3 pr-pulse workers),
   stop pr-pulse, quit Terminal?" Options: Park / Dry run only / Cancel. `--dry-run` stops here.
6. **`shutdown`** starts the detached coordinator and returns. The `/park` session says one line and
   goes idle. The coordinator then:
   1. runs `pr-pulse stop`, if pr-pulse is installed (records `pr_pulse_was_on`);
   2. runs `claude stop <id>` for each background session;
   3. for each interactive session: SIGINT if busy, then waits until its transcript has been
      unchanged for 2 s (at most `busy_wait_s`), then SIGTERM, then waits for the pid to exit.
      The `/park` session itself goes last;
   4. quits Terminal: `tell application "Terminal" to quit`. Terminal's own "running processes"
      dialog stays;
   5. records the outcome per session in `events`, and sends one macOS notification:
      "Parked 9 sessions. /park --resume to bring them back."

### `/park --resume` flow
- **Pick a park.** Default: the newest park with unresumed sessions.
  - `--day yesterday|YYYY-MM-DD`: if one day has several parks, list them and ask.
  - `--name <part>`: sessions whose name contains it, in any park within retention.
  - `--pick`: a multiSelect of that park's sessions.
  - `--unresumed`: everything not yet resumed.
  - `park list` shows the parks.
- **Summary table** before anything opens: session | branch | HEAD/patch drift | re-arm items |
  cwd status. A missing cwd falls back to the repo root, with a warning. Then confirm once.
- **Interactive sessions:** one new Terminal window each:
  `cd <cwd> && claude --resume <sid> "<resume prompt>"`, with no other flags, so it doesn't fork.
- **Background sessions** (user-started only): `claude --bg --resume <sid> "<resume prompt>"`,
  run in `<cwd>`, with no other flags.
- **The resume prompt** tells the session to:
  1. check drift against the snapshot, and never reset or overwrite to make it match;
  2. re-arm each Monitor with its exact command;
  3. recreate each cron;
  4. continue with the next action, or wait for the owner if there was none.
- **Afterwards:** `pr-pulse start` if `pr_pulse_was_on`. Mark `resumed_at`. One summary line per
  session, plus one macOS notification.

### Retire `/pause` (after the plugin is installed)
- Back up `~/.claude/skills/pause/` to `~/.claude/backups/pause-<date>/`, then remove it.
- Fix every reference: the `/pause` lines in the memories (`resume: ~/.claude/resume/<ws>.md`) and
  the retro pending-notes reference to the pause skill.
- Existing `~/.claude/resume/*.md` files stay readable. `/park --resume` doesn't need them.
- The per-workstream tracker sync (tracker-hub) isn't part of v1. Note it in the README as a follow-up.

## Build steps
1. **Spike first.** These are facts the whole design rests on, and they get checked before any
   other code:
   1. `claude --resume <sid> "prompt"` (interactive) and `claude --bg --resume <sid> "prompt"` keep
      the same session id (no fork).
   2. SIGINT then SIGTERM on an interactive `claude` leaves a complete transcript.
   3. `tell application "Terminal" to quit` behaves as expected when shells are idle and when
      they're busy.
   4. Monitor and background-shell commands are visible as child processes of the session pid.

   Write the results into `plan.md`. If (1) fails, the fallback is `--fork-session` plus re-keying
   pr-pulse joins. Ask the owner before taking it.
2. Store, gc and config, with tests.
3. inventory and snapshot, with tests against fake `claude agents` output and fake transcripts.
4. Resume-prompt builder and the resume picker, with tests, including several parks on one day.
5. terminal.py and the coordinator, with fake `osascript` and `claude` on PATH in tests.
6. SKILL.md, README, marketplace entry; check.sh passes.
7. A live run on the owner's Mac, in this order:
   - `--dry-run`;
   - park two throwaway sessions (one interactive, one background, each with a Monitor);
   - resume them, and check that the session ids match and the Monitors are re-armed;
   - then the full day's set.
8. PR. Its body waits for the owner's top lines; agy runs as an adversarial reviewer. After the merge:
   install, then retire `/pause`.

## Verification
- **Unit tests, both directions:**
  - pr-pulse workers are skipped, and user sessions are kept;
  - `--only` / `--exclude`;
  - gc deletes parks older than 30 days and keeps newer ones;
  - several parks on one day ask which one;
  - a missing cwd falls back to the repo root;
  - the re-arm extractor finds `inbox-watch.sh`, `pr-watch.sh` and a background shell, and ignores
    unrelated processes;
  - crons: CronCreate without a matching CronDelete is kept, and deleted ones are dropped;
  - the coordinator order: pr-pulse first, the `/park` session last;
  - resume opens one window per interactive session and uses `--bg --resume` with no extra flags.
- **Live:**
  - the same session ids after resume (`claude agents --json`);
  - a pr-pulse joined session gets its inbox watcher back (`inbox/<sid>.live` is fresh);
  - Terminal quits and reopens;
  - the notification arrives;
  - a second park on the same day is listed for picking.

## Spike results (2026-11-10, Claude Code 2.1.322, macOS, Apple Terminal)
1. **No fork on resume: confirmed.** A background session stopped with `claude stop`, then resumed
   with `claude --bg --resume <sid> "prompt"`, kept its id and name. Resumed interactively in a new
   Terminal window (`do script "cd … && claude --resume <sid> \"prompt\""`), it kept the same id.
2. **Clean exit: confirmed for an idle interactive session.** One SIGINT exits it, and the whole
   transcript still parses. A busy session gets a SIGINT, waits until its transcript is quiet, then
   gets a SIGTERM; covered by tests. The live run checks it again.
3. **Closing Terminal: partly checked.** Closing a window by its tty when its shell is idle gives no
   prompt. Quitting all of Terminal was left for the live run, so the sessions in use weren't closed.
4. **Watchers are visible: confirmed.** Monitor and background-Bash commands run as
   `zsh -c source <snapshot> … && eval '<command>'` under the session's pid, so the exact command can
   be recovered. Seen live: pr-pulse `inbox-watch.sh <sid>` and `pr-watch.sh <n>`.
5. **Crons:** a CronCreate result reads "Scheduled recurring job <id> …". Crons are session-only and
   expire after 7 days.

## Built since the plan
- **Partial parks.** `--only` / `--exclude` leave pr-pulse on and quit no Terminal; only the parked
  sessions' own windows close. This makes a safe live test possible.
- **park never records itself.** The command running park, and its parents, is never captured as a
  watcher to restart.
- **The `/park` session finishes its reply first.** It waits until Claude reports it idle (at most
  60 s) before it is stopped.

## Live run (2026-11-11)
- **Dry run:** `park plan` + `cancel` on the real sessions. Every session stopped by the night's
  reboot was listed with a pid of null, and is now skipped as "not running".
- **Partial park and resume of two throwaway sessions,** one interactive and one background, each
  running a Monitor:
  - both stopped, and only their own window closed;
  - pr-pulse's setting stayed as it was;
  - both came back with the same session ids;
  - each restarted its Monitor.
- **Bug found and fixed:** a resume prompt starting with "/park …" is read by Claude Code as a slash
  command ("Unknown command: /park"). The prompt now never starts with "/", and a test guards it.
- **Changed:** a full park now stops pr-pulse's running workers too. They still aren't reopened.
- **Still open:** a full park (it quits Terminal) needs the owner's go.
