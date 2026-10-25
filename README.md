# skills

[Claude Code skills](https://code.claude.com/docs/en/skills) I use and share.

## Skills

| Skill | What it does |
| --- | --- |
| [pr-review](skills/pr-review/SKILL.md) | Reviews someone else's PR in an isolated worktree, verifies findings, and posts a review you approve. |
| [pr-feedback](skills/pr-feedback/SKILL.md) | Works the review comments on your own PR: verifies each claim, fixes what holds up, and posts replies you approve. |
| [bugfix](skills/bugfix/SKILL.md) | Takes a tracker issue from report to PR: reproduces it on the latest default branch, fixes the root cause behind a fails-before/passes-after test, opens the PR, gets CI green, and answers the review bots. |
| [agy](skills/agy/SKILL.md) | Consults the Antigravity CLI (`agy`, Gemini) as a read-only second advisor: Claude writes the brief, agy answers as a separate voice, and a hook blocks every write and every read of secrets. |
| [retro](skills/retro/SKILL.md) | A fortnightly retrospective of a repo's AI-agent harness: finds the corrections, review findings and CI failures that keep recurring, proposes the fix one rung stronger than what already failed, and applies only what you accept, with backups and an undo. |
| [cure](skills/cure/SKILL.md) | Sourced prospect and account research for B2B sales: learns what your own organization sells, then sizes the companies at an event or on a list, or maps one company's evidenced needs to your capabilities. Every figure has a source or says "not public". Uses [cure-style](skills/cure-style/SKILL.md) for the report and six research agents in [agents/](agents). |

The PR skills and `bugfix` need the [GitHub CLI](https://cli.github.com/) (`gh`), authenticated. `bugfix` reads the issue from whichever tracker is connected to Claude Code (Jira, Linear, and so on), falling back to GitHub Issues.

`agy` needs the Antigravity CLI (`agy`) installed and signed in, plus a one-time setup that installs the read-only gate and the `agy-ask` wrapper. Run it from a clone of this repo. It is verified on macOS; Linux and Windows (Git Bash) are supported but not yet verified, and `agy-ask` stays disabled on any machine until the installer's live write-block test has passed there:

```bash
bash skills/agy/scripts/install.sh
```

Details, Windows notes and troubleshooting: [skills/agy/references/details.md](skills/agy/references/details.md).

`retro` needs `python3` (3.9+), `gh`, `jq` and macOS or Linux; Linear is optional. It reads your own Claude Code transcripts on your machine and keeps its config, state and backups in `~/.claude/retro/`. Run `/retro --setup` once inside the repo it should watch; the optional SessionStart reminder is set up by hand: [skills/retro/references/install.md](skills/retro/references/install.md).

`cure` runs best on Opus in a working folder (Claude Code, or a Cowork task) and can use a large share of your usage limit on a full run; try a Quick run first. Its agents come with the plugin; for a copy install also copy `agents/cure-*.md` to `~/.claude/agents/`. Setup, cost and surfaces: [skills/cure/references/usage.md](skills/cure/references/usage.md).

## Install

Plugin marketplace (all skills, and cure's agents):

```
/plugin marketplace add mustafarslan/skills
/plugin install skills@mustafarslan-skills
```

Or copy one skill:

```bash
git clone https://github.com/mustafarslan/skills.git
cp -r skills/skills/<skill-name> ~/.claude/skills/   # or .claude/skills/ for one project
```

## Usage

Invoke with a slash command, or just ask ("review PR 42", "address the comments on my PR") and Claude loads the skill. `bugfix` is the exception: slash command only.

| Command | Effect |
| --- | --- |
| `/pr-review 42` | Review PR #42 (number or URL) |
| `/pr-review` | Review the current branch against its base |
| `/pr-feedback 42` | Work the feedback on your PR #42 |
| `/pr-feedback` | Work the feedback on the current branch's PR |
| `/bugfix 1234` | Fix issue 1234 end to end (the tracker prefix is inferred from the repo's history) |
| `/bugfix PROJ-1234` | Same, with an explicit key |
| `/agy <question>` | Ask agy for a second opinion (or just say "ask agy…"; add "boost" for its slow multi-agent mode) |
| `/retro --setup` | Point retro at the current repo (once) |
| `/retro` | Run the retrospective (`--harness`, `--agents`, `--days N`, `--draft`, `--restore RUN_ID`) |
| `cure setup` | Build the profile of your own organization (once) |
| `cure: use cases for Acme Retail` | Research one company against your capabilities (or `cure: size the companies at <event>`) |

`bugfix` only runs when you type the command — it pushes code and opens PRs, so Claude never loads it on its own. Optional flags add second opinions and skip silently when the tool isn't installed: `--agy` and `--boost` challenge the root cause (they need the [agy](skills/agy/SKILL.md) setup above), and `--codex` challenges the fix diff (it needs the `openai-codex` plugin).

Installed as a plugin, the commands are namespaced: `/skills:pr-review`, `/skills:pr-feedback`, `/skills:bugfix`, `/skills:agy`, `/skills:retro`.

## Adding a skill

1. `cp -r templates/skill skills/<skill-name>`
2. Set `name` (must match the directory) and `description` (what it does and when to use it) in `SKILL.md`.
3. Add a row to the table above.

## License

[MIT](LICENSE)
