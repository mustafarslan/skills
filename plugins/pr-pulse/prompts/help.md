pr-pulse runs your PR loop across every Claude session and repo on this machine.

WHAT IT DOES (for repos you mapped with /pr-pulse:map)
  Your PRs     A person reviews → /pr-feedback, with waiting CodeRabbit/Claude comments in the
               same round. After 2 rounds the PR is on hold for you.
               Approved at head + CI green → /pr-merge.
               Head moved after the approval → you decide in /pr-pulse:inbox.
  Their PRs    GitHub review request, or a Slack tag (re-review) → /pr-review.
               Untagged shares in Slack wait in a pool, pulled 1–2 at a time.
               Afterwards the bot replies in the thread: "approved @author", and so on.
  Announce     New PRs go to #pr-review (repo mapped with announce, or /pr-pulse:on).

WHO WORKS    A session you /pr-pulse:join (only while idle), otherwise a fresh background
             worker: claude attach <id> (ids in /pr-pulse:status). At most 3 at once.
YOUR LINES   Sessions never post text themselves. Each draft comes as a notification: type your
             own top lines, "Fill it for me" (you confirm before it posts), or drop it.
             /pr-pulse:inbox has anything you put off.
INTENT       Every job is told to read ARCHITECTURE_INTENT.md / AGENTS.md first.

COMMANDS
  /pr-pulse:init [slack]      Guided setup, safe to rerun (pr-pulse doctor shows where you are)
  /pr-pulse:status            What's running: daemon, repos, sessions, PRs, jobs, drafts
  /pr-pulse:map               Choose repos and PR sessions (it suggests from live sessions)
  /pr-pulse:join | :leave     This session takes, or stops taking, PR work
  /pr-pulse:spawn <owner/repo>  Start a background PR session for a repo
  /pr-pulse:inbox             Drafts and merge decisions waiting for your lines
  /pr-pulse:stop | :start     Everything off / on, in one step (off survives a reboot)
  /pr-pulse:pause | :resume   Keep watching, but hand nothing out
  /pr-pulse:auto-review off | on   Stop / restart reviewing others' PRs (yours carry on)
  /pr-pulse:rules [repo]      PR rules for one repo: auto-review, merge auto/ask/never,
                              rounds, bots, plus plain rules every job there follows
  /pr-pulse:on | :off         Announce from this session without mapping the repo
  pr-pulse --help             The full CLI, in a terminal

WHERE  Store ~/.claude/pr-pulse/pulse.db · log ~/.claude/pr-pulse/daemon.log
       Settings ~/.config/pr-pulse/config.json · secrets ~/.config/pr-pulse/env
DOCS   {{readme}}
