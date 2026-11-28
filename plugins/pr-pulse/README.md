# pr-pulse

<img src="assets/logo-1024.png" alt="pr-pulse logo: two overlapping translucent circles, cyan and violet" width="96">

pr-pulse is a personal Claude Code plugin that runs the pull-request loop across all your Claude
sessions and repos. It runs only on your machine.

- **Your own PRs:** it announces new ones in Slack. When people review them, it runs
  `/pr-feedback`. When one is approved and green, it runs `/pr-merge`.
- **Teammates' PRs:** it picks up the ones that ask for your review, whether on GitHub or in
  Slack, and runs `/pr-review`. When your review is posted, it replies in the Slack thread with
  the verdict.
- **Your top lines first:** nothing it writes is posted in your name until you have added your
  own top lines.

In Claude Code, `/pr-pulse:help` gives the one-screen version of this page.

## Features

- **Works across all your sessions and repos.** A small background service tracks every Claude session and the repos you map with `/pr-pulse:map`.
- **Builds on the skills you already use.** Reviews run `/pr-review`, review feedback runs `/pr-feedback`, and merges run `/pr-merge`. It uses your own versions, or the repo's when you have none, so your review rules and safety checks still apply.
- **Announces your PRs.** New PRs get a short, friendly note in #pr-reviews, written by Claude, with the link and your name.
- **Handles reviews on your own PRs.** When a person reviews, it starts a `/pr-feedback` round. CodeRabbit and Claude bot comments wait for that first human review, then get handled in the same round.
- **Merges when it's safe.** Approved at the latest commit with CI green: it runs `/pr-merge`. If new commits came after the approval, it summarises them and asks you first.
- **Reviews teammates' PRs.** It picks up GitHub review requests and PRs shared in #pr-reviews, 1–2 at a time, and starts a re-review when someone tags you.
- **Replies in the PR's own thread.** After your review, it answers under the PR's message in #pr-reviews with your verdict, your top lines and the author tagged, for example "Alex's review: approved @Sam". It never posts a new message in the channel. If the author deleted and reposted their PR message, the reply goes under the repost; if there is no repost, the verdict is not posted.
- **Or emoji only (`verdict_style: "emoji"`).** pr-pulse reacts instead of replying, and only on two messages:
  - **The author's PR message:** the latest verdict. ✅ approved, ⚠️ changes requested, 💬 comments.
  - **The author's re-review request** ("fixed @you"): ♻️ while the re-review runs, then that round's verdict.
  - **Many rounds stay clean:** each round swaps the emoji pr-pulse added before, never anyone else's, so a PR that went through five rounds shows one status, not five replies.
  - **Shared bot:** with a shared pr-pulse bot, reviewers who use emoji mode on the same PR share one reaction of each kind.
  - **Setup:** it needs the Slack app's `reactions:write` permission. `pr-pulse doctor` says how to add it; until then verdicts are replied as before.
- **Your words go first.** Nothing is posted in your name until you add your top lines. Each draft arrives as a macOS notification: type your own lines, pick "Fill it for me" (you see the lines and press Post before anything goes out), or drop it. `/pr-pulse:inbox` has everything you put off. A guard blocks any early post.
- **Asks you from a notification.** Decisions arrive as a macOS notification with a findings summary: critical / improvement / nit, and what each touches. Answer right there from its Answer menu, which also has Details… (first, so a stray keystroke never answers) and Open session. A question you answer elsewhere leaves the screen on its own.
- **Tells you when any session needs you.** If any Claude session is waiting for your input, you get "Claude needs you" with an Open session button. It skips the session you're looking at.
- **Keeps architecture in mind.** Every job reads your architecture intent and AGENTS.md before judging or changing anything.
- **Shares the work out.** Sessions you `/pr-pulse:join` get PR jobs; otherwise a fresh background worker in its own worktree takes them. At most 3 run at once.
- **Stays safe on its own.** Routine steps are pre-approved, and merging always asks. Force-push is blocked, stuck workers send you a notification, and feedback rounds are capped.
- **Ready for the whole team.** One shared Slack bot, so setup is just copying the token from your password manager. Every message carries the sender's own name.
- **Easy to run.** `/pr-pulse:init` sets it up step by step, and `/pr-pulse:status` shows what's happening. `/pr-pulse:stop` and `/pr-pulse:start` switch everything off and on, and `/pr-pulse:help` explains it all.
- **Keeps itself current.** After `claude plugin update`, every part of pr-pulse runs the new code: the background service copies the installed plugin within a minute whenever its content differs (even with the same version number) and restarts on it, and the hooks and CLI of sessions opened on 0.7.7 or later hand over to that copy (a running inbox watcher keeps its code until it restarts). Only new slash commands, skills and hook matchers need `/reload-plugins` in an open session; pr-pulse names those sessions in one notification and in `/pr-pulse:status`.
- **Tidy by default.** It keeps its own small database, cleans out history older than 30 days, and removes finished worktrees.

## How it works

```
launchd ──► pr-pulsed (Python stdlib, one tick a minute) ──► ~/.claude/pr-pulse/pulse.db (SQLite)
              │ reads: claude agents --json, gh, Slack
              ├─► a session you registered, while idle: a line in its inbox wakes it
              └─► otherwise: a fresh `claude --bg` worker in <repo>/.claude/worktrees/pr-pulse-*
sessions ──► `pr-pulse` CLI (job start/done, outbox add, …) ──► the same database
```

A small daemon does the watching and bookkeeping and costs no tokens. Claude sessions do the
actual review and fixing work. Nothing happens for a repo until you map it with `/pr-pulse:map`.

**What triggers a job**

| Trigger | Job |
|---|---|
| A person reviews or comments on your own PR | `/pr-feedback`. It handles the people's comments **and** any waiting CodeRabbit / Claude bot comments in the same round. Max 2 such rounds, then the PR is on hold for you |
| Only review bots (CodeRabbit, Claude, Copilot, …) have commented | Nothing. They wait for the first human review. After a person has reviewed, new bot comments may start up to 2 bot-only rounds, which never put the PR on hold |
| Your PR is approved at its head commit, CI is green, nothing is pending | `/pr-merge` |
| Approved, but the head moved after the approval | `merge-check`: a session summarises approved..head, and you answer merge or re-review in `/pr-pulse:inbox` |
| GitHub requests your review (directly, not via a team) | `/pr-review` |
| A teammate tags you on a PR in a watched Slack channel | Re-review: `/pr-review`, focused on what changed since your last review |
| A teammate tags you in a PR's Slack thread (e.g. answering your review there) | The same re-review. The PR comes from the thread's first message, and the verdict replies in that thread |
| GitHub re-requests your review on a PR you already reviewed | The same re-review, even at the head you reviewed (the author may only have replied) |
| The author pushes and replies after your *changes requested* review, without re-requesting | The same re-review, once per new head. A push with no reply (a rebase) starts nothing |
| pr-pulse loses access to a watched channel (for example, the bot was removed by a reinstall) | One macOS notification with the fix (`/invite @prpulse`), and again only after a new outage |
| A teammate shares a PR in a watched channel without tagging anyone | It goes into the review pool. 1–2 at a time are pulled when a slot is free |
| Your review of someone's PR is posted | The bot replies **in the thread of the PR's message** in #pr-reviews (it finds that message even when the review came from a GitHub request), with your top lines. No message for that PR in the channel: nothing is posted, never a new top-level message. The reply reads "<your name>'s review: approved / lgtm with comments / request changes / comments added @author" |
| You open a PR with `gh pr create` in a mapped repo set to announce, or in a session with `/pr-pulse:on` | Claude writes 1–3 sentences and saves them with `pr-pulse announce <url>`; the pr-pulse service posts them in #pr-review within a minute, then the link. The session itself never writes to Slack, so Claude Code's auto mode has nothing to block |
| A PR was opened but no announcement was saved for it (blocked, skipped or forgotten) | One notification after `announce_nudge_minutes`; `/pr-pulse:inbox` writes and posts it, or skips it |
| You save new text for a PR that is already announced (`pr-pulse announce <url>` again) | The service edits that Slack message in place (bot token only) |

At most 3 jobs run at once (`pool_size`). Every job reminds the session to read
`docs/ARCHITECTURE_INTENT.md` and `AGENTS.md` before judging or changing anything.

**Your answers carry over.** A later job on the same PR (say a new approval after you put a merge on hold) gets your answers from the last 14 days, and asks again only when something they depended on changed: a new head, a review asking for changes, a failing check, or the thing you were waiting for. An answer given within 10 seconds of its notification appearing is passed on as "confirm before acting on it", in case it was a stray click. `pr-pulse decisions <PR>` lists what is carried, and `pr-pulse forget <question id>` withdraws a mistaken answer.

**Questions you can answer from a notification.** When a session needs your decision (a
triage choice in `/pr-review`, implement or defer in `/pr-feedback`), it asks through pr-pulse.
You get a macOS notification with three short lines: the findings by severity, with what
they touch, then the most important finding in one sentence, then the question.
```
1 critical (test) · 2 improvements (1 docs) · 1 nit
Test asserts the old token, so a refresh race would go unnoticed (tests/auth/test_refresh.py:40)
Approve, request changes or comment?
```
A critical that only touches a test or a doc is marked as such but keeps its severity, so you
can judge it. Migrations and infra always count as production, and a session can only raise a
finding's scope, never relabel production code as a test. Still, for any critical, read its one
line or open its details before approving. Everything is in the banner's **Answer** menu: pick an
answer, or "Type an answer…" for your own words, and the session carries on. **Details…** lists
every finding on its own line, with **Open session**, which brings that session to the front (a
background worker opens with `claude attach <id>`), and **Back** to return to the summary and
answer. Only one question is on screen at a time. "Later", or no answer within 5 minutes, keeps it
in `/pr-pulse:inbox`, and it comes back in an hour.

This needs [alerter](https://github.com/vjeantet/alerter); `/pr-pulse:init` installs it with brew.
If a banner ever stays on screen with no buttons or close, set `"use_alerter": false` in
`config.json`: questions then open as a macOS dialog with real buttons instead.

**Who does the work**

- **A session you registered** with `/pr-pulse:join` gets jobs for its repo, but only while it
  is idle. Its inbox watcher (a Monitor) wakes it.
- **Otherwise a fresh background worker** starts, named `pr-<owner>-<repo>-<n>-<action>`. Open
  it with `claude attach <id>` (`/pr-pulse:status` shows the id). Routine steps are pre-approved (`worker_allowed_tools`), so it
  doesn't stall on prompts. Merging still asks you, and force-pushes and `reset --hard` are refused.
  If a worker does stop at a prompt, you get a notification with the attach command.

**Your top lines first.** Sessions never post review comments, replies or PR text themselves.
They park drafts and you get one macOS notification. `/pr-pulse:inbox` shows every waiting
draft in one batch. For each draft you can type your own lines, pick **Fill it for me**
(Claude writes them: friendly, positive, brief, no chitchat; the rules are in
`prompts/top-lines-guide.md`, and you get them back as a notification to Post, retype or drop:
only your Post saves them), or drop it. Then the session that wrote the draft posts it:
your lines first, its draft quoted below. A guard enforces this: in a pr-pulse job, a GitHub post is
blocked until your lines are in, even where posting is pre-approved.

## Commands

| Command | Effect |
|---|---|
| `/pr-pulse:init [slack]` | Guided setup: the daemon, repos, then Slack with you step by step. Safe to rerun |
| `/pr-pulse:help` | This overview, in one screen |
| `/pr-pulse:status` | The daemon, mapped repos, live sessions, tracked PRs, jobs and waiting drafts |
| `/pr-pulse:map` | Suggests a PR session per repo from the live sessions, saves what you pick, and asks about announcing |
| `/pr-pulse:join` / `:leave` | This session takes, or stops taking, PR work for its repo. **`--for <session>`** makes it the PR session of one development session (e.g. `pr-contracts` with `--for contracts`): it handles only the PRs that session opened, and those PRs wait for it (busy: they queue; not listening: they are held and you are told once). A join without `--for` is a general PR session: reviews of others' PRs (still under `/pr-pulse:auto-review`) and PRs with no PR session of their own; with none joined, background workers take those. `pr-pulse focus` lists the pairs, `focus clear <session>` drops one, `focus origin <pr> <session>` attributes an older PR |
| `/pr-pulse:spawn <owner/repo>` | Starts a named background PR session for a repo |
| `/pr-pulse:inbox` | Drafts and merge decisions waiting for you |
| `/pr-pulse:stop` | **Shuts everything down in one step.** Stops the daemon (it stays off after a reboot), every inbox watcher, and the background sessions pr-pulse started; their unfinished jobs go back to the queue. Announcements stop too. Nothing is uninstalled. `--keep-workers` leaves running workers alone |
| `/pr-pulse:start` | Brings everything back after `stop` |
| `/pr-pulse:pause` / `:resume` | Lighter: it keeps watching but hands nothing out |
| `/pr-pulse:rules [repo]` | **PR rules per repo.** Settings pr-pulse enforces for that repo only: `auto_review` on/off, `merge` auto/ask/never (ask: the merge job asks you first; never: pr-pulse starts no merge there), `feedback_rounds`, `bot_rounds`, `review_bots`, `ignore_authors`. Plus plain-language rules ("Run the bank-rule tests before approving") that every job for that repo gets in its instructions. Saved in your `config.json` under `repo_rules`; nothing is committed to the repo. `/pr-pulse:map` offers it for each new repo |
| `/pr-pulse:auto-review off` / `on` | **Stops reviewing other people's PRs on its own**, for when you need the Mac for your own work. Shared PRs, review requests and re-review tags are still read and queued, so none is lost, and they start when you turn it back `on` (held reviews of PRs that closed or merged meanwhile are dropped). Your own PRs (feedback, merge) carry on, and a review whose top lines you already gave still posts. `off` also stops the background sessions pr-pulse started for reviews (conversations are kept); `--keep-running` leaves them. `/pr-pulse:auto-review` alone shows the state |
| `/pr-pulse:on [worktree]` / `:off` | Announce PRs from this session (or worktree) without mapping the repo |

Commands that change state answer instantly, without a model reply. In a terminal, run
`pr-pulse --help` for the full CLI. Useful ones:
- `pr-pulse job list`
- `pr-pulse outbox list`
- `pr-pulse pr release <url>` ends a hold
- `pr-pulse tick --dry-run` shows what it would do now
- `pr-pulse prune` runs the cleanup now

## Requirements

- **Claude Code on macOS.** pr-pulse uses hooks, background sessions (`claude --bg`), launchd
  and macOS notifications, so it doesn't run in claude.ai or on other systems.
- **`gh`** (logged in), **`jq`** and **`python3`** (all on macOS with the developer tools or Homebrew).
  `alerter` is installed for you, so you can answer questions from notifications.
- **The skills it runs: `/pr-review`, `/pr-feedback` and `/pr-merge`.** pr-pulse doesn't ship them;
  it hands each job to the ones you already have, so your own review and merge rules apply.
  `pr-pulse doctor` warns when one is missing, and jobs that need it fail with a notification.
- **Slack, through the team's pr-pulse app.** `team.json` names the shared app and the
  #pr-reviews channel. `/pr-pulse:init` only asks you to copy the bot token from your password manager
  (item "pr-pulse Slack bot token"). Everyone posts through the same bot, with their own name
  on each message. Anyone holding the token can post as the bot and read the channels it's in,
  so keep the password-manager item to developers who open and review PRs. If it leaks, revoke it in
  the app and update the item; everyone then copies the new one with `/pr-pulse:init slack`.
  You can still create your own app instead, from the same init step.

**Where its data lives.** `~/.claude/pr-pulse/` (database, log, inbox) and
`~/.config/pr-pulse/` (your Slack token and settings, readable only by you). Not
`${CLAUDE_PLUGIN_DATA}`, because the background service runs outside Claude Code, where that
folder isn't known. `pr-pulse stop && pr-pulse daemon uninstall` then `rm -rf ~/.claude/pr-pulse`
removes everything.

## Setup

You need macOS with `jq`, `curl`, `gh` (logged in) and Claude Code.

**1. Install the plugin** from the team marketplace:
```bash
claude plugin marketplace add mustafarslan/skills   # once
claude plugin install pr-pulse@mustafarslan-skills
```

**2. Run `/pr-pulse:init`** in any Claude session, and it does the rest with you:

| Step | What happens |
|---|---|
| Daemon | Started automatically (launchd), and `pr-pulse` is linked into `~/.local/bin` |
| Repos | It suggests a PR session per repo from your live sessions; you pick |
| Slack announcements | It asks first. Then it opens Slack in your browser with the app already filled in, and guides each click: create, install, copy the token, pick the channel, an optional test message |
| Reading the review channel (optional) | It explains what this adds and asks. Then: paste the bigger manifest, reinstall, pick the channels to watch, invite the bot, and match your Slack account |

**Secrets never go through the chat.** You copy the token in the browser, and init saves it
straight from the clipboard into `~/.config/pr-pulse/env` (readable only by you), then clears
the clipboard. Running sessions and the daemon read that file themselves, so nothing needs a
restart and nothing goes into `.zshrc`.

Rerun `/pr-pulse:init` any time: it only offers what is missing. `/pr-pulse:init slack` goes
straight to Slack. `pr-pulse doctor` shows where you are.

If your Slack workspace needs an admin to approve new apps, init tells you. Send the request,
and run `/pr-pulse:init slack` once it is approved.

<details><summary>Doing it by hand instead</summary>

- Daemon: `plugins/pr-pulse/scripts/pr-pulse daemon install` (from a checkout of this repo).
- Repos: `/pr-pulse:map`, then `/pr-pulse:join` in each PR session.
- Slack app: open the link from `pr-pulse slack manifest-url announce` (use `full` to include
  reading) and create the app. Then **Install to Workspace**, copy the **Bot User OAuth Token**,
  and run `pr-pulse secret set bot-token --from-clipboard`.
- Channels: `pr-pulse slack channels`, then `pr-pulse config set announce_channel <id>`.
- Reading: `pr-pulse config set watch_channels '["C…"]'` and
  `pr-pulse config set slack_user_id $(pr-pulse slack whois you@company.com)`. Then invite the
  bot with `/invite @pr-pulse` in each channel and check with `pr-pulse slack check <id>`.
- Older setups that use an incoming webhook (`PR_PULSE_SLACK_WEBHOOK_URL`) keep working. The
  bot token wins when both are set.

</details>

## Settings

All settings are in `~/.config/pr-pulse/config.json`. The daemon re-reads the file every tick.

| Key | Default | Effect |
|---|---|---|
| `pool_size` | 3 | Jobs running at once |
| `pool_pull` | 1 | Untagged Slack PRs pulled per free slot (max 2) |
| `feedback_rounds` | 2 | Automatic `/pr-feedback` rounds with human activity, then the PR is on hold |
| `bot_rounds` | 2 | Extra rounds started by review bots alone, after a human has reviewed |
| `review_bots` | coderabbitai, claude, copilot, codex | These wait for a human review. Any `…[bot]` login counts too |
| `ignore_authors` | linear, github-actions, vercel, … | Never counted at all |
| `stale_minutes` | 45 | A job with no heartbeat for this long is re-queued once, then dropped |
| `stall_minutes` | 120 | A job with no heartbeat for this long whose session still looks busy (an idle session with a running inbox watcher looks busy too) stops holding a slot, and you get one notification naming the session |
| `announce_nudge_minutes` | 10 | A PR opened with no saved announcement after this long gets one notification |
| `worker_idle_minutes` | 10 | A background worker pr-pulse started is stopped once it is idle, holds no job, and its last job changed this long ago (its conversation is kept). A busy worker, or one whose job waits for you, is never stopped |
| `repo_rules` | none | Per-repo PR rules, set with `/pr-pulse:rules`: `{"owner/name": {"settings": {...}, "rules": [...]}}`. A bad entry is reported once and that repo uses the global settings |
| `post_as` | bot | `bot`: posts and reactions come from the shared pr-pulse app. `user`: they come from you, with your own Slack user token (see [Posting as yourself](#posting-as-yourself)). Reading channels always uses the bot |
| `verdict_style` | reply | `reply`: a thread reply with your verdict, top lines and the author tagged. `emoji`: a reaction on the author's share message and re-review requests instead (✅ ⚠️ 💬 ♻️); needs `reactions:write` |
| `use_alerter` | true | `false` shows questions as macOS dialogs with buttons and notices as plain notifications, instead of alerter banners |
| `retention_days` | 30 | Finished history older than this is deleted once a day |
| `spawn_workers` | true | `false`: only registered sessions get work |
| `review_requested` | true | Pick up GitHub review requests. A request on a PR you already reviewed ("Re-request review") becomes a re-review, also when someone else approved it |
| `rereview_on_push` | true | Re-review a PR when its author pushes new commits **and** replies (a thread reply or PR comment) after your standing *changes requested* review, with no re-request or Slack tag needed. A push alone, such as a rebase, starts nothing |
| `rereview_poll_seconds` | 300 | How often the `rereview_on_push` search runs |
| `worker_args` | [] | Extra `claude --bg` flags for workers |

Announcement settings are environment variables:

| Variable | Default | Effect |
|---|---|---|
| `PR_PULSE_SLACK_BOT_TOKEN` | none | Set by `/pr-pulse:init` in `~/.config/pr-pulse/env`. Posts announcements to `announce_channel`, and reads the watched channels |
| `PR_PULSE_SLACK_USER_TOKEN` | none | Your own Slack user token (`xoxp-`), set by `/pr-pulse:init slack`. With `post_as` `user`, every post and reaction uses it |
| `PR_PULSE_SLACK_WEBHOOK_URL` | none | Older alternative for announcements only. Never used with `post_as` `user` |
| `PR_PULSE_INCLUDE_DRAFTS` | `0` | `1` announces drafts when they are created |
| `PR_PULSE_POST_ON_READY` | `1` | `0` stops announcing on `gh pr ready` |
| `PR_PULSE_CHANNEL_LABEL` | `#pr-review` | The channel name used in messages. The webhook decides where posts actually go |
| `PR_PULSE_DRY_RUN` | `0` | `1` prints instead of sending, and the daemon decides without acting |

### Posting as yourself

By default your announcements, verdict replies and reactions come from the shared **pr-pulse**
bot, with your name in the text. To have them come from **you** instead:

1. `/pr-pulse:init slack` and pick **Post as me**. It opens Slack with a small personal app,
   **pr-pulse (me)**, already filled in. That app can only post and react as you; it cannot read
   anything. Create it, install it, and copy its **User OAuth Token** (`xoxp-`).
2. `pr-pulse secret set user-token --from-clipboard` saves it, checks it is yours (the same
   Slack id as `slack_user_id`) and turns `post_as` to `user`.
3. `pr-pulse slack test-post <channel id> --as-me` posts one test message as you and reads it
   back the way teammates' pr-pulse sees it.

What changes:
- Messages show as yours, with no "· name" and no "<name>'s review" prefix.
- Reading the channels stays on the team bot. Only the bot token reads; your token only writes.
- You must be a member of the channel to post there.
- Teammates' pr-pulse now sees your announcements as PR shares, picks them up for review, and
  replies to them with verdicts. Bot announcements were ignored.
- A reaction you added by hand is never recorded or removed by pr-pulse. Reactions and
  messages made by the bot before you switched are still removed and edited by the bot.
- No silent fallback. If your user token is missing or revoked, nothing is posted as the bot
  instead: announcements and verdicts wait, and you get a notification. Back to the bot any
  time: `pr-pulse config set post_as bot`.

To change the voice of the announcements, edit `prompts/summary-guide.md`. To change what
every job is told, edit `prompts/job.md`.

## Logo

`assets/logo-1024.png` is the Slack app icon (upload it under the app's **Basic Information → Display Information**). `assets/notification-256.png` is shown on pr-pulse's macOS notifications. `assets/logo.svg` is the source, and `assets/render-logo.py` re-renders the PNGs with no extra tools.

## Where things live

| Path | What |
|---|---|
| `~/.claude/pr-pulse/pulse.db` | The SQLite store: sessions, repos, PRs, jobs, drafts, Slack pool, event log |
| `~/.claude/pr-pulse/daemon.log` | The daemon's log |
| `~/.claude/pr-pulse/inbox/` | One file per registered session; a new line wakes it |
| `~/.config/pr-pulse/env`, `config.json` | Secrets and settings |
| `~/Library/LaunchAgents/local.pr-pulse.plist` | The daemon's launchd agent |
| `<repo>/.claude/worktrees/pr-pulse-*` | Worker worktrees. They are removed when the work is pushed and done |

## Test it first

1. Run `pr-pulse tick --dry-run`. It prints what it would queue, deliver or start, against your
   real sessions and PRs, without doing any of it.
2. In a scratch repo, run `PR_PULSE_SLACK_WEBHOOK_URL="$PR_PULSE_TEST_WEBHOOK" claude`, type
   `/pr-pulse:on`, and open a small PR. One post appears in #pr-pulse-test. A draft PR posts
   nothing until `gh pr ready`.
3. Point `watch_channels` at #pr-pulse-test and post a PR link there. It shows up in
   `pr-pulse status` in the pool.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Nothing happens for a repo | Is it mapped (`/pr-pulse:status`)? Is pr-pulse paused or stopped? |
| A job is queued but never runs | All 3 slots are busy. Or no registered session is idle, and `spawn_workers` is off |
| A registered session gets no work | Its inbox watcher isn't running. Run `/pr-pulse:join` in it again |
| A PR says HOLD in status | The round cap was reached. `pr-pulse pr release <url>` hands it back |
| Status says "Slack posting: NOT set up" | Run `/pr-pulse:init slack`, or `pr-pulse doctor` to see what's missing |
| A command gets a model reply instead of an instant answer | The hook didn't fire, and the command fell back to running the script itself. Run `claude --debug hooks` to see why |
| "Slack rejected the post" | The webhook was revoked, or it belongs to another workspace. Create a new one |
| The daemon isn't running | Check `pr-pulse daemon status` and `tail ~/.claude/pr-pulse/daemon.log`, then `pr-pulse start` |

## Updating

**Automatic updates.** Claude Code can install new versions by itself, but for a team marketplace
that is off until you turn it on: `pr-pulse autoupdate on` (or `/pr-pulse:init` asks once), or
`/plugin` → Marketplaces → this marketplace → Enable auto-update. It covers every plugin from that
marketplace. Claude Code then updates within about 10 minutes of a session's first message; open
sessions load the update with `/reload-plugins`. An org admin can turn it on for everyone, and lock
it, in managed settings:

```json
"extraKnownMarketplaces": {
  "mustafarslan-skills": {"source": {"source": "github", "repo": "mustafarslan/skills"}, "autoUpdate": true}
}
```

With auto-update on, whatever is merged into the marketplace repo reaches everyone within
minutes, so protect its main branch (a required review and the check passing).

By hand, `claude plugin update pr-pulse@mustafarslan-skills` is all it takes:

| Part | How it gets the update |
|---|---|
| Background service | Compares the installed plugin with its own copy (`~/.claude/pr-pulse/app`) by content every minute, at session start and on each `pr-pulse` command; copies it when they differ (locked, verified, switched in one step) and restarts on it |
| Hooks and CLI in open sessions | The announcement hook, the slash-command toggles, the inbox watcher and the CLI hand over to the service's copy, so an open session runs the current code even with an older pr-pulse loaded. The posting guard runs its own copy (it runs before every Bash call, so it stays light). A running inbox watcher keeps its code until it restarts |
| New commands, skills, hook matchers | Only after `/reload-plugins` (or `/park` and resume). pr-pulse notifies once per session that needs it, and lists them in `/pr-pulse:status` |

Sessions opened before 0.7.7 don't have the hand-over yet: reload them once.

From a checkout of this repo, entry points hand over to the installed service's copy; set `PR_PULSE_FORWARDED=1` to run the checkout's own code.


## Update notice

Claude Code leaves background auto-update **off** for third-party marketplaces such as this one, so a new version
would otherwise go unnoticed. To get updates automatically, turn it on once: `/plugin` → **Marketplaces** →
`mustafarslan-skills` → enable auto-update. Or update by hand:
`claude plugin marketplace update mustafarslan-skills && claude plugin update pr-pulse@mustafarslan-skills`, then restart.

If you leave auto-update off, pr-pulse tells you when a newer version is out: at session start, at most once a day,
it reads this plugin's `plugin.json` from GitHub (one `raw.githubusercontent.com` request, 3-second timeout) and shows
one line to you only when that version is newer than the one you have. It installs nothing, sends nothing about you,
and says nothing when it is offline or anything goes wrong. To switch it off, set `MUSTAFARSLAN_SKILLS_UPDATE_CHECK=0`
in your environment (for example in the `env` block of `~/.claude/settings.json`).

## Stop or remove it

To stop: `/pr-pulse:stop` (or `pr-pulse stop`). To bring it back: `/pr-pulse:start`.

To remove it completely:
```bash
pr-pulse stop && pr-pulse daemon uninstall
claude plugin uninstall pr-pulse@mustafarslan-skills
rm -rf ~/.claude/pr-pulse ~/.local/bin/pr-pulse
```

## Development

The tests are in `tests/`:
```bash
python3 -m unittest discover -s tests && bash tests/smoke.sh
```
