# skills

[Claude Code skills](https://code.claude.com/docs/en/skills) I use and share.

## Skills

| Skill | What it does |
| --- | --- |
| [pr-review](skills/pr-review/SKILL.md) | Reviews someone else's PR in an isolated worktree, verifies findings, and posts a review you approve. |
| [pr-feedback](skills/pr-feedback/SKILL.md) | Works the review comments on your own PR: verifies each claim, fixes what holds up, and posts replies you approve. |
| [bugfix](skills/bugfix/SKILL.md) | Takes a tracker issue from report to PR: reproduces it on the latest default branch, fixes the root cause behind a fails-before/passes-after test, opens the PR, gets CI green, and answers the review bots. |

All need the [GitHub CLI](https://cli.github.com/) (`gh`), authenticated. `bugfix` reads the issue from whichever tracker is connected to Claude Code (Jira, Linear, and so on), falling back to GitHub Issues.

## Install

Plugin marketplace (all skills):

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

`bugfix` only runs when you type the command — it pushes code and opens PRs, so Claude never loads it on its own. Optional flags add second opinions and skip silently when the tool isn't installed: `--agy` and `--boost` challenge the root cause (they need an `agy-ask` wrapper for the Antigravity CLI), and `--codex` challenges the fix diff (it needs the `openai-codex` plugin).

Installed as a plugin, the commands are namespaced: `/skills:pr-review`, `/skills:pr-feedback`, `/skills:bugfix`.

## Adding a skill

1. `cp -r templates/skill skills/<skill-name>`
2. Set `name` (must match the directory) and `description` (what it does and when to use it) in `SKILL.md`.
3. Add a row to the table above.

## License

[MIT](LICENSE)
