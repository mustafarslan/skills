---
name: retro
description: Fortnightly retrospective of a repository's AI-agent harness (skills, rules, hooks, subagents, memory). Use when the user runs /retro (flags --setup, --harness, --agents, --all, --days N, --draft, --agy, --boost, --big, --restore RUN_ID), or when the SessionStart reminder says /retro is due and the user picks "Run now". Mines the last 14 days of the user's sessions, the team's merged PRs, reviews, CI failures and, when an issue tracker is configured, completed issues for problems and corrections that keep recurring, proposes the fixes that stop them, and applies only what the user accepts, with backups.
argument-hint: "[--harness|--agents|--all] [--days N] [--draft] [--agy] [--boost] [--big] | --draft RUN_ID | --restore RUN_ID | --setup"
allowed-tools: Bash, Read, Grep, Glob, Edit, Write, Agent, Skill, ToolSearch, AskUserQuestion, Artifact, mcp__linear-server, mcp__claude_ai_Linear, mcp__claude_ai_Google_Drive
---

# retro — stop fixing the same thing twice

Each of these is a sign that the harness does not yet hold a lesson:
- a correction the user types more than once;
- a review finding that comes back;
- a PR that drifted from what it first set out to do. The signs are its description or title rewritten, rework
  commits after review, or reverts. Drift has no fixed wording, so it is judged from what changed.

Retro finds them and proposes the fix **one rung stronger** than whatever already failed to hold
the lesson. It applies only what the user accepts.

Names used below. Shell state does not persist between Bash calls, so substitute them literally in every command:
- `SCRIPTS` = this skill's `scripts/` folder, as an absolute path: `${CLAUDE_SKILL_DIR}/scripts` (the base directory
  shown when the skill loads; `~/.claude/skills/retro/scripts` for a copy install)
- `run-id` = today as `YYYY-MM-DD`; if `~/.claude/retro/runs/<that>` already exists, `-2`, `-3`, …
- `RUN_DIR` = `~/.claude/retro/runs/<run-id>`; all intermediate files go here.
- `CFG` = the settings printed by `python3 $SCRIPTS/config.py show` (`repo`, `base_branch`, `default_checkout`,
  `issue_tracker`, `issue_team`, `issue_prefix`, `instructions_file`, `instructions_cap_bytes`, …). Written once by
  `--setup` to `~/.claude/retro/config.json`; every `<config.…>` below is one of its fields.
- `MAIN` = the main repo checkout: `dirname "$(git rev-parse --path-format=absolute --git-common-dir)"`, run in any
  checkout of `<config.repo>` (default `<config.default_checkout>`).
- Issue tracker: `<config.issue_tracker>` (`linear` or `none`), its team `<config.issue_team>`, issue ids `<config.issue_prefix>-123`.
- `MEMORY_DIR` = your Claude Code memory for the main checkout: `~/.claude/projects/$(printf %s "$MAIN" | sed 's#[/.]#-#g')/memory/`
  (analysts A and C read its `MEMORY.md`; skip it if it does not exist).

## Flags

| Flag | Effect |
|---|---|
| `--setup` | create or update the config (see Setup). Nothing else runs |
| `--all` (default) | every card |
| `--harness` | only cards whose fix lives in the harness: repo skills, `.claude/rules`, hooks, settings, CI |
| `--agents` | only cards whose fix lives in agent behaviour: `.claude/agents/*.md`, brief templates in skills, `~/.claude/CLAUDE.md`, memory |
| `--days N` | window = the last N **active** days. A day is active if it has a session of the user's or a PR opened or merged; idle days (weekends, holidays) are skipped and the window reaches further back. Given explicitly, it overrides `last_run` |
| `--agy` / `--boost` / `--big` | consult agy adversarially on the top 5 (step 5). Only when given, and only if an `agy` skill is installed (else say `agy: not installed — skipped` and continue); follow the `agy` skill |
| `--draft` | share the accepted repo changes as a **draft PR** (step 8), with the report as a short body. Without it, repo changes stay on a local branch |
| `--draft RUN_ID` | publish an earlier run's local branch `retro/RUN_ID` as a draft PR: step 8.5 only, with that run's `RUN_DIR` (its report and cards) |
| `--restore RUN_ID` | undo one run (see Restore). Nothing else runs; needs no config |

## The card (every finding)

| Field | Values |
|---|---|
| `recurs` | `problem` (CI breaks, repeated review findings, PR drift, reopened bugs) · `habit` (a correction the user keeps typing) |
| `lives_in` | `harness` · `agents` (decides which flag shows it) |
| rung | `none` → `memory` → `rule` (prose) → `skill-step` → `hook`/CI gate |

Rules every card obeys:
- **Ladder.** If the lesson already exists at some rung and still recurs, propose the next rung up.
  Never more prose for something prose already failed to hold.
- **Just in time over ambient.** Prefer a skill step or a `PreToolUse`/`PostToolUse` hook at the moment
  of action (e.g. after `gh pr create` → "watch CI; approved + green + threads answered → merge") to
  always-loaded text.
- **One in, one out.** Every prose card names what it merges or deletes. If `<config.instructions_cap_bytes>` is set,
  `<config.instructions_file>` has a size cap in CI: measure it (`git show origin/<config.base_branch>:<file> | wc -c`),
  and when the headroom is smaller than the new text, treat the file as closed: new invariants go in a path-scoped rule
  file or a docs page instead. With no cap, the file still stays lean.
- **Evidence.** Counted, from ≥ 2 independent places, with refs (session id8 + date, PR #, issue id).
  Patterns, never people. Never copy transcript text into a repo file.
- **Key** = `target::slug`. A key that was rejected or is still in an open PR is never re-proposed.
- **New subagent** is a card kind of its own (`kind: new-subagent`). Propose one when the evidence
  shows a recurring job without a fitting agent. Examples: the same long brief retyped to `general-purpose`/`claude`
  dispatches (`agents.jsonl`); a review angle the user keeps adding by hand that no agent in
  `.claude/agents/` or `~/.claude/agents/` covers; a correction that keeps hitting the same kind of delegated
  work. The card names:
  - its job, its trigger (when the main agent dispatches it) and its tools (read-only unless it must edit);
  - why no existing agent fits, or why extending one is worse;
  - the ad-hoc briefs it replaces (one in, one out);
  - where it lives: repo `.claude/agents/` for team work (PR), or `~/.claude/agents/` for personal work.
  The draft is the full agent `.md` (frontmatter + body), in the style of the existing ones.
  Its `signature.agent_regex` matches the ad-hoc dispatches it replaces. Next cycle, those should drop.
- **Delete / merge** (`kind: delete`) removes or merges text, a rule or an agent that the evidence shows is dead or duplicated.
  Dispatch counts cover only the user's own sessions, so a team agent is never deleted or merged on
  `agents.jsonl` alone. It needs a second source (PR history, review threads, the user saying so).
- **Subagents cannot ask the user.** "Ask me instead of deciding" for subagents is fixed in briefs
  ("return open decisions as questions; do not decide"), and the main agent asks.
- **Generated skills.** If some skills in `~/.claude/skills` are generated by a script from the repo, never edit the generated copies; fix the source.

## Steps

### 1 · Preflight
0. `python3 $SCRIPTS/config.py show`. If it prints `retro: no config at …`, run the **Setup** flow first, then carry on.
1. `python3 $SCRIPTS/state.py show`. Pick `since`:
   - `--days N` given → `python3 $SCRIPTS/window.py --days N`, and use its `since`;
   - else `last_run` if there is one;
   - else `window.py --days 14`.
   Keep its `active_days`, `calendar_days` and `skipped` for the report header.
2. **Open PRs from earlier runs:** for each `applied` entry with a `pr`, `gh pr view <pr> --repo <config.repo> --json state,mergedAt`.
   - OPEN → its key goes on the do-not-propose list.
   - Merged under 7 days ago → skip its efficacy check (too new).
   - CLOSED unmerged → its key may be proposed again.
   - An entry with a `branch` but no `pr` (local only, never shared) goes on the do-not-propose list while
     `git -C "$MAIN" rev-parse --verify <branch>` succeeds. List it in the report as "waiting to be shared".
   (The efficacy check itself runs at the end of step 2, once `prs.jsonl` exists.)

### 2 · Gather (no model calls)
```bash
mkdir -p "$RUN_DIR"
python3 $SCRIPTS/extract_sessions.py --since <since> --out "$RUN_DIR/turns.jsonl" --sessions-out "$RUN_DIR/sessions.jsonl" \
  --agent-calls-out "$RUN_DIR/agents.jsonl"
python3 $SCRIPTS/gather_prs.py --since <since> --out "$RUN_DIR/prs.jsonl" --ci-out "$RUN_DIR/ci.json"
```
Issues, only if `<config.issue_tracker>` is `linear`: `ToolSearch("+linear list issues")`, list issues of
`<config.issue_team>` completed since `since`, and write one JSON line each (`id, title, labels, project,
completedAt, first 300 chars of description`) to `$RUN_DIR/linear.jsonl`. If Linear is not connected, say so in
one line and continue without it. With `issue_tracker: none`, write no file and use no issue evidence.
Repo tree for analyst C: `git -C "$MAIN" fetch origin <config.base_branch>` and read files at
`origin/<config.base_branch>` (`git show origin/<config.base_branch>:<path>`), so a feature branch's local edits
don't count as the harness.

**Efficacy check** of last cycle's fixes, for every `applied` entry with `status: applied` whose fix is live:
personal cards, plus repo cards whose PR merged ≥ 7 days ago. Skip a repo card whose PR is still open or was closed
unmerged; that fix never ran. Count each non-empty signature list, and skip an empty one; never pass `''`:
- users: `python3 $SCRIPTS/extract_sessions.py --since <since> --count <signature.user_regex…>`;
- dispatches: `python3 $SCRIPTS/extract_sessions.py --since <since> --count-agents <signature.agent_regex…>`;
- PRs: count the PRs in `prs.jsonl` matching `signature.pr_regex`.
Compare the per-day rates with `signature.baseline`. If the rate is not lower, that is a card to escalate one rung, and the
now-useless text is proposed for deletion. The result goes into the report's "Last cycle's fixes" table.

### 3 · Price, then go
Print the evidence counts, then the plan: 3 analysts (one message, `Plan` subagents), roughly
`turns.jsonl` + `prs.jsonl` size ÷ 4 tokens each plus ~30k, about 5–10 minutes, plus agy if flagged.
**Wait for the user's go.** Never more than 3 subagents at once.

### 4 · Analyze
Dispatch A (sessions), B (PRs/reviews/CI/issues) and C (harness + memory inventory) from
[briefs.md](briefs.md), with the do-not-propose keys (rejected + open-PR keys) and the config values its slots name
(`{instructions_file}`, `{base_branch}`, `{budget_note}`). Check each
analyst's refs before using them: open 2 cited sessions or PRs per analyst and confirm they say
what the card claims. Drop cards whose evidence does not hold.

### 5 · Synthesize
Merge the three lists. Dedupe by key, fill `current_rung` from C's inventory, apply the
ladder and one-in-one-out, then rank by recurrence × cost of a miss. Filter by flag. Keep the
top 5; the rest become one-liners.

**Always call `advisor` here**, before the report, whatever the flags. Its question: is the ranking right,
is each fix at the right rung, and is any card's evidence weak? Act on its advice, or record in
`cards.json` why you didn't. If advisor is unavailable, say so in one line and continue.

Only with `--agy`/`--boost`/`--big`, and only if an `agy` skill is installed: give agy the top 5 and ask it to
break them (would it stop the recurrence? what would it break?). Keep its voice separate in the report. If no `agy`
skill is installed, say "agy: not installed — skipped" and continue. Without those flags, never call agy.

### 6 · Report
Ask with AskUserQuestion: **Claude artifact** or **Google Doc**? Write it from [report.md](report.md):
concise, table first, no chit-chat. Artifact → load `artifact-design` if it is listed, publish. Google Doc → load
`anthropic-skills:google-workspace` if it is listed, create it in Drive. If the chosen route's tool or skill is not
available here, say so in one line and offer the other; with neither, show `$RUN_DIR/report.md` in the chat. Save `$RUN_DIR/report.md` and `$RUN_DIR/cards.json` either way.

### 7 · Review loop, then accept
**Every question about the report carries its link inside the question text** (artifact URL or Doc URL).
A question dialog covers the text above it, so a link only in the reply is a link the user never sees.
1. AskUserQuestion: "Report: <link>. Read it, then: any point to change or update?" (answers come back as free text via Other).
   Revise the affected cards, republish to the same URL or Doc, and repeat until the user says it is done.
2. Ask for acceptance in one call: Q1 multiSelect proposals 1–4; Q2 multiSelect proposal 5 plus up
   to 3 one-liners; Q3 "Reason for anything rejected?" (optional). Not accepted = rejected.

### 8 · Back up, then apply
**Undo must touch only retro's own edits, never later work.**

**Always call `advisor` first**, on the exact accepted edits, before any backup or edit. Its question: will
these edits stop the recurrence, and can any of them break something or clash with another? Raise any
blocker with the user before applying. If advisor is unavailable, say so in one line and continue.

For every accepted card:

- **Personal file** (`~/.claude/**`, memory):
  1. `python3 $SCRIPTS/backup.py <run-id> <every path it will edit, create or delete>`.
  2. Explain before applying: show the change with a concrete example and get "go".
  3. Edit.
  4. `python3 $SCRIPTS/backup.py <run-id> --after <same paths>`.
  Run multi-file steps under `bash` with arrays (`mapfile -t`, `"${A[@]}"`): the session shell may be
  zsh, which does not split an unquoted `$LIST`, so every command gets one bogus path.
  5. After editing `settings.json`: `jq empty ~/.claude/settings.json`, then
     `jq -e '.hooks.<Event>[] | .hooks[] | .command' ~/.claude/settings.json` to confirm that the new entry sits where
     the event expects it. If either check fails, undo **that file only**:
     `python3 $SCRIPTS/restore.py <run-id> --dry-run --only ~/.claude/settings.json`, then the same command without `--dry-run`.
- **Repo file** — all accepted repo cards go on one local branch, `retro/<run-id>`. **Without `--draft`,
  nothing leaves this machine**: no push and no PR. Step 7 acceptance does **not** count as the go for the commit:
  ```bash
  WT=~/.claude/retro/worktrees/<run-id>
  git -C "$MAIN" fetch origin <config.base_branch> && git -C "$MAIN" worktree add "$WT" -b retro/<run-id> origin/<config.base_branch>
  python3 $SCRIPTS/backup.py <run-id> --repo "$WT" <paths>
  ```
  1. Edit inside `$WT`. Every command is `cd "$WT" && …`, because the workspace shell resets its cwd.
  2. Show the full diff (`cd "$WT" && git diff`) and wait for "go".
  3. Commit in `$WT`: use the repo's `/commit` skill if it has one (lint, typecheck, tests), else run the repo's own
     checks and `git commit`. Do not push.
  4. Record `"branch": "retro/<run-id>"` on every repo card in `run.json`.
  5. **Only with `--draft`**, the light draft flow (not a full PR skill that pings reviewers and babysits CI):
     1. Write `$RUN_DIR/pr-body.md` from [pr-body.md](pr-body.md).
     2. Ask once for the user's own top lines (retro's own rule: outward text starts with the user's words). Their lines go first, verbatim.
     3. Show the final body and wait for "go". A draft PR is still visible to the team.
     4. Run:
        ```bash
        git -C "$MAIN" push -u origin retro/<run-id> &&
          gh pr create --repo <config.repo> --draft --base <config.base_branch> --head retro/<run-id> \
            --title "retro <run-id>: <the change in a few words>" --body-file "$RUN_DIR/pr-body.md"
        ```
     5. Record the URL in `backup.py <run-id> --repo "$WT" --pr <url>` and in the `pr` field of every repo card
        in `run.json`. For `--draft RUN_ID` (a run already recorded), use `python3 $SCRIPTS/state.py set-pr <run-id> <url>`
        instead; never re-run `state.py record`, which would move `last_run`.
     6. Give the user the link, and nothing else: no reviewer requests, no CI watch.
  6. Clean up, by `cd "$WT" && git status --porcelain`:
     - empty, or only untracked build output → `git -C "$MAIN" worktree remove "$WT"`. The branch stays, so
       `/retro --draft <run-id>` can publish it later. If git refuses because of untracked files, ask before `--force`.
     - anything tracked and uncommitted → stop and show it.

### 9 · Record
Write `$RUN_DIR/run.json`:
```json
{"run_id": "…", "applied": [{"key": "target::slug", "target": "…", "slug": "…", "rung": "hook",
  "lives_in": "harness", "pr": null, "branch": null, "signature": {"user_regex": ["…"], "pr_regex": ["…"],
  "agent_regex": [],
  "baseline": {"turns": 9, "sessions": 6, "dispatches": 0, "prs": 0, "days": 14}}}],
 "rejected": [{"key": "…", "target": "…", "slug": "…", "reason": "…"}]}
```
`branch` is `retro/<run-id>` for a repo card, `null` for a personal one. `pr` is the draft PR URL once shared, else `null`. `signature` comes from the analyst's card.
`baseline` is measured now, over this run's window:
- `turns` and `sessions`: `extract_sessions.py --since <since> --count <user_regex…>` (sum over the regexes);
- `dispatches`: `extract_sessions.py --since <since> --count-agents <agent_regex…>`;
- `prs`: the count of `prs.jsonl` rows matching `pr_regex`;
- `days`: the window length.
Then `python3 $SCRIPTS/state.py record $RUN_DIR/run.json`. This sets `last_run`, and that is what
arms the reminder. Finish with one line per applied change and the report link.

## Restore (`--restore RUN_ID`)
1. `python3 $SCRIPTS/restore.py --list`, then `python3 $SCRIPTS/restore.py <RUN_ID> --dry-run`. Show the user the output.
2. On "go": `python3 $SCRIPTS/restore.py <RUN_ID>`.
   - Files unchanged since retro → the original comes back.
   - Files edited since → only retro's edit is reversed (3-way merge), and later edits stay.
   - Overlapping edits → the file is left alone, and the merge is saved under `backups/<RUN_ID>/conflicts/` to resolve with the user.
   - Files with no record of what retro wrote (the run stopped mid-apply) → a missing original comes back;
     anything else is left alone, reported, and exits 1.
   - Repo changes → it prints the PR to close, or the merge commit to `git revert`. Ask before doing either; both are visible to the team.
     A local-only run (no PR) has nothing on GitHub to undo: after asking, `git -C "$MAIN" branch -D retro/<RUN_ID>`.
   - `--only <path>…` limits the restore to those files.
   - Exit 1 means some file needs a manual look. Show the user which file, and never force it.
3. The current versions are kept in `backups/<RUN_ID>/pre-restore/<time>/` first, so a restore can itself be undone.
   State is marked reverted only on a clean, full restore, and only for the personal cards.

## Setup (`--setup`)
Creates or updates `~/.claude/retro/config.json` (`RETRO_HOME` moves the folder, `RETRO_CONFIG` names the file). Nothing else runs.
1. Detect defaults in the current directory; skip any that fails:
   - repo: `git remote get-url origin`, reduced to `OWNER/NAME` (drop a trailing `.git`, keep the last two path parts);
   - default checkout: `dirname "$(git rev-parse --path-format=absolute --git-common-dir)"`;
   - instructions file: `AGENTS.md` if it exists at that checkout's root, else `CLAUDE.md`;
   - base branch: `git symbolic-ref --short refs/remotes/origin/HEAD` without the `origin/`, else `main`.
   If a config already exists, read it and offer its values as the defaults instead.
2. **One AskUserQuestion call**, four questions, the detected value first and marked recommended, the user's own
   value through Other (when nothing was detected, offer the example `acme/widgets` and say to type theirs):
   1. repo `OWNER/NAME` (the GitHub repo `gh` queries and the draft PR goes to);
   2. default checkout (where `MAIN` is when retro is not run inside a checkout);
   3. issue tracker: `None` or `Linear`. For Linear the user types `linear <team> <prefix>` in Other, e.g. `linear Core CORE`;
      a bare `Linear` gets one short follow-up for team and prefix, the only second question allowed;
   4. instructions file, and its CI size cap if it has one: `<file>, no cap` options, or Other as `<file> <cap in bytes>`, e.g. `AGENTS.md 10240`.
3. Write the JSON (keep the old file as `config.json.bak`): `repo`, `default_checkout`, `issue_tracker`, `issue_team`,
   `issue_prefix`, `instructions_file`, `instructions_cap_bytes` (`null` = no cap), `base_branch`. Leave the rest to their
   defaults (`repo_folder` = the repo name, `remote_regex` derived from it, `reminder_interval_days` 14); the user can edit the file for those.
4. Run `python3 $SCRIPTS/config.py show` and print its output. If it reports an error, fix the file and run it again.
   Then stop; only when Setup was entered from Preflight, carry on with step 1.

## Reminder
`hooks/retro-reminder.sh` in this skill (SessionStart, registered once by the user; see
[references/install.md](references/install.md)) → `state.py remind`. It is silent until the first
recorded run, and without a config. After that it fires in sessions of `<config.repo>` once
`<config.reminder_interval_days>` days (default 14) have passed, at most once a day,
and stamps the day before it speaks. It tells the model to ask: Run now / Snooze 3 days (`state.py snooze 3`) / Skip this
cycle (`state.py skip`). On **Run now**, run this skill, then continue the user's original request.
