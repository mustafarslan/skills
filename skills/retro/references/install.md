# Installing /retro

A fortnightly retrospective of a repository's AI-agent harness. It mines your Claude Code
transcripts (`~/.claude/projects`), the repo's merged PRs and CI runs (via `gh`), and optionally
completed issues from Linear, finds what keeps recurring, proposes fixes one step stronger than
what already failed, and applies only what you accept, with backups. Transcripts stay on your
machine; nothing is pushed unless you pass `--draft`.

## Needs

- Claude Code, `python3` (3.9+), `git`, macOS or Linux (the scripts use `fcntl`).
- `gh`, logged in with read access to the repo (`gh auth status`).
- `jq` (used to check `settings.json` after retro edits it).
- Optional: Claude artifacts or a Google Drive connector for the report; without either it is shown in the chat.
- Optional: a Linear connector (MCP) for completed issues; the [agy](../../agy/SKILL.md) skill for `--agy`/`--boost`/`--big`.

## Install

1. Install the skill: the plugin (see the repository README), or copy it with
   `cp -r skills/retro ~/.claude/skills/`. It keeps its state in `~/.claude/retro/`, never in a repo.
2. Optional, the fortnightly reminder: register this skill's `hooks/retro-reminder.sh` as a SessionStart hook in
   `~/.claude/settings.json` (merge into any existing `hooks` block). For a copy install:
   ```json
   {"hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "~/.claude/skills/retro/hooks/retro-reminder.sh"}]}]}}
   ```
   The hook finds the scripts beside it, so with the plugin, point `command` at the hook inside the plugin's
   install folder, or copy the skill as above just for the hook.
3. In a checkout of your repo, run `/retro --setup`. It asks once, then writes `~/.claude/retro/config.json`.
   Or copy `scripts/config.example.json` there and edit it.
4. Run `/retro`. The reminder only starts after the first recorded run.

Until the config exists, every script stops with `retro: no config at <path> — run /retro --setup (see references/install.md)`,
and the reminder stays silent. `--restore` and the bookkeeping commands of `state.py` never need it.

## Config fields (`~/.claude/retro/config.json`)

JSON has no comments, so the fields are described here. Only `repo` is required.

| Field | Default | Meaning |
|---|---|---|
| `repo` | (required) | `OWNER/NAME` of the GitHub repo: `gh` queries and the draft PR go here. `--repo` on a script overrides it |
| `repo_folder` | `NAME` | Folder name that counts as the repo when a session's cwd has no git remote (a removed worktree) |
| `remote_regex` | `[/:]NAME(\.git)?/?$` | Which `origin` URLs count as the repo; `null` = the default |
| `default_checkout` | `~/code/NAME` | Where `MAIN` is when retro is not run inside a checkout |
| `base_branch` | `main` | Branch the retro branch is cut from, the draft PR targets, and CI failures are counted on |
| `issue_tracker` | `none` | `linear` (read through the connector) or `none` |
| `issue_team` | `""` | Linear team key or name |
| `issue_prefix` | `""` | Issue id prefix, e.g. `ABC` for `ABC-123` |
| `instructions_file` | `AGENTS.md` | The repo's always-loaded agent instructions file (`AGENTS.md` or `CLAUDE.md`) |
| `instructions_cap_bytes` | `null` | The size cap CI puts on that file, if any; `null` = no cap |
| `reminder_interval_days` | `14` | Days between reminders. A `state.json` `interval_days`, if set, wins |

`python3 <skill>/scripts/config.py show` prints the resolved values.

## Environment

- `RETRO_HOME`: folder for config, state, runs and backups (default `~/.claude/retro`).
- `RETRO_CONFIG`: the config file itself (default `$RETRO_HOME/config.json`).
- `RETRO_TODAY` (`YYYY-MM-DD`) and `RETRO_SCRIPTS` (scripts folder the hook calls): for tests.

## Test

From a clone of this repository:

```bash
python3 -m unittest skills/retro/scripts/tests/test_retro.py -v
```
