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
| [rebase](skills/rebase/SKILL.md) | Rebases the current branch onto its base (or the default branch when the base was merged and deleted) with no questions: auto-stashes by SHA so a shared stash stack never loses work, regenerates conflicts that are only in generated files, then runs the repo's local checks. |
| [commit](skills/commit/SKILL.md) | Runs only the checks the change needs, verifies that what is staged is what was checked, commits in the repo's style, pushes with a pinned lease, and lists other branches that touch the same files. |
| [pr-merge](skills/pr-merge/SKILL.md) | Takes an approved PR the rest of the way: merge queue when the base has one, otherwise rebase, CI, merge. Never bypasses branch protection. |
| [pr-upsert](skills/pr-upsert/SKILL.md) | Current branch to a shippable PR in one flow: rebase, parallel self-review (two reviewer agents, plus Codex and agy when available), fixes, commit, PR from the repo's template, overlap reviewers, tracker sync, CI and bot watch. |
| [design-doc](skills/design-doc/SKILL.md) | My house style for documents (HTML, PDF, Google Docs, Word): achromatic palette with one yellow accent, system fonts, a small component set, checked contrast. |
| [design-video](skills/design-video/SKILL.md) | The same style for short videos: storyboard, an HTML composition in your project, and a frame-exact renderer to MP4. |
| [spm](skills/spm/SKILL.md) | Helps a product manager write requirements engineers can build and test (epic, stories, acceptance criteria, worked examples) without saying how to build it. Enforced by a checker, a fail-closed write hook and red-team passes. |
| [park](skills/park/SKILL.md) | **Beta, macOS + Terminal.app only.** At the end of the day, `/park` snapshots every Claude Code session on your Mac (folder, branch, uncommitted work as a patch, the watchers, background shells and crons running inside it), stops them all and quits Terminal; `/park --resume` brings each conversation back in its own window and restarts what was running. Never commits, stashes or resets. |
| [system-design](skills/system-design/SKILL.md) | Designs, reviews and stress-tests systems at a staff-engineer bar: locks requirements and non-goals first, runs the capacity math in a script, defaults to the boring design, pushes back on steers that break a requirement, walks failure cascades, and ends with a trade-off table whose every row says when to change the decision. Modes for real designs (design doc + ADRs), mock interviews (as candidate or interviewer), reviews and deep dives. Its calculator also sizes restore time against RTO, LLM serving (tokens, cost, KV cache), stream partitions, cost from your prices, and the 10x/100x path; its gate rejects vague, strawman or already-fired triggers. `--walkthrough` adds an animated, step-by-step page of the design (brief, numbers, draft, what breaks, each fix, one failure walked hop by hop, trade-offs), checked against the doc and the calculator. Ships with a 19-case eval suite. |
| [pr-pulse](plugins/pr-pulse/README.md) | **A separate plugin, macOS only.** Runs your PR loop across all your Claude Code sessions and repos: announces new PRs in Slack, runs `/pr-review`, `/pr-feedback` and `/pr-merge` in idle sessions or background workers, asks your decisions from macOS notifications, and posts nothing in your name until you have written your own top lines. |

The PR skills and `bugfix` need the [GitHub CLI](https://cli.github.com/) (`gh`), authenticated. `bugfix` reads the issue from whichever tracker is connected to Claude Code (Jira, Linear, and so on), falling back to GitHub Issues.

`agy` needs the Antigravity CLI (`agy`) installed and signed in, plus a one-time setup that installs the read-only gate and the `agy-ask` wrapper. Run it from a clone of this repo. It is verified on macOS; Linux and Windows (Git Bash) are supported but not yet verified, and `agy-ask` stays disabled on any machine until the installer's live write-block test has passed there:

```bash
bash skills/agy/scripts/install.sh
```

Details, Windows notes and troubleshooting: [skills/agy/references/details.md](skills/agy/references/details.md).

`retro` needs `python3` (3.9+), `gh`, `jq` and macOS or Linux; Linear is optional. It reads your own Claude Code transcripts on your machine and keeps its config, state and backups in `~/.claude/retro/`. Run `/retro --setup` once inside the repo it should watch; the optional SessionStart reminder is set up by hand: [skills/retro/references/install.md](skills/retro/references/install.md).

`cure` runs best on Opus in a working folder (Claude Code, or a Cowork task) and can use a large share of your usage limit on a full run; try a Quick run first. Its agents come with the plugin; for a copy install also copy `agents/cure-*.md` to `~/.claude/agents/`. Setup, cost and surfaces: [skills/cure/references/usage.md](skills/cure/references/usage.md).

The git skills (`rebase`, `commit`, `pr-merge`, `pr-upsert`) work in any repository. Each repo's own commands (install, lint, tests, generated files, commit style) live in that repo's `.claude/project-facts.md`; the first time a skill needs one and it is missing, the skill reads the repo (package.json, Makefile, CI workflows, …), shows what it found, asks once and writes the file. Template: [skills/rebase/references/project-facts.template.md](skills/rebase/references/project-facts.template.md). They need `git` and `gh`; `commit`, `pr-merge` and `pr-upsert` call `rebase`, and `pr-upsert` also calls `commit`, `pr-feedback` and the `pr-self-reviewer` / `pr-architect` agents in [agents/](agents).

`design-video` needs Node 18+ and Chrome; its renderer installs its own pinned packages into `~/.cache/design-video/` on first run. `design-doc` and `design-video` share one `tokens.css` and one diagram recipe, `references/diagrams.md` (inline SVG, light variant for documents, dark for video), each kept byte-identical in both (`cmp` must print nothing). `system-design --html` draws its styled diagrams from the same recipe, and its `--walkthrough` page follows the recipe's motion rules and carries a copy of `tokens.css` (`skills/system-design/assets/walkthrough/tokens.css`, also byte-identical), so documents, videos and design diagrams look like one hand made them; the Mermaid in repo design docs stays unstyled.

`system-design` needs `python3` (3.9+) for its calculator and design checker, and uses the `system-design-reviewer` agent in [agents/](agents); agy, when set up, joins the review as a second voice. Without subagents it falls back to a labelled self-review, and without a user to answer it writes its questions down as assumptions. Its behavioural evals run with `claude plugin eval` (billed model runs): see [skills/system-design/evals/README.md](skills/system-design/evals/README.md).

`park` needs macOS, Terminal.app, `python3` and `git`. The first `/park` asks macOS to let Claude control Terminal (System Settings → Privacy & Security → Automation). Its store and patches live in `~/.claude/park/` and are kept 30 days. What comes back and what doesn't: [skills/park/references/usage.md](skills/park/references/usage.md).

`pr-pulse` is its own plugin in [plugins/pr-pulse/](plugins/pr-pulse/), installed separately (below). It needs macOS, `gh` (logged in), `jq`, `curl` and `python3`, and runs a background service under launchd; Slack is optional. It hands each job to this repo's `/pr-review`, `/pr-feedback` or `/pr-merge` (your own versions win), and `pr-pulse doctor` names any that are missing. Setup with `/pr-pulse:init`: [plugins/pr-pulse/README.md](plugins/pr-pulse/README.md).

`spm` needs `python3` (3.9+) and its `spm-red-team` agent. The word trigger ("spm" in a prompt) is opt-in, because it is a prompt hook: [skills/spm/references/install.md](skills/spm/references/install.md).

## Install

Plugin marketplace (all skills and agents):

```
/plugin marketplace add mustafarslan/skills
/plugin install skills@mustafarslan-skills
/plugin install pr-pulse@mustafarslan-skills   # optional, macOS: the pr-pulse plugin
```

Or copy one skill:

```bash
git clone https://github.com/mustafarslan/skills.git
cp -r skills/skills/<skill-name> ~/.claude/skills/   # or .claude/skills/ for one project
cp skills/agents/*.md ~/.claude/agents/              # agents used by cure, pr-upsert, spm and system-design
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
| `/agy <question>` | Ask agy for a second opinion on Gemini 4 Hydrogen High (or just say "ask agy…"; "agy big" for Gemini 4 Carbon High; add "boost" for its slow multi-agent mode) |
| `/park` | Park every session for the day (`--dry-run`, `--only NAME`, `--exclude NAME`, `--notes`) |
| `/park --resume` | Bring the newest park's sessions back (`--day yesterday`, `--name PART`, `--pick`) |
| `/retro --setup` | Point retro at the current repo (once) |
| `/retro` | Run the retrospective (`--harness`, `--agents`, `--days N`, `--draft`, `--restore RUN_ID`) |
| `cure setup` | Build the profile of your own organization (once) |
| `cure: use cases for Acme Retail` | Research one company against your capabilities (or `cure: size the companies at <event>`) |
| `/rebase` | Rebase on the PR's base, or the default branch (`/rebase <branch>`, `--test` for the full local suite) |
| `/commit` | Check, commit and push the current change (`--no-push` to stop before pushing) |
| `/pr-merge 42` | Merge approved PR #42 through the queue or the protected flow |
| `/pr-upsert` | Take the current branch to a reviewed, green PR |
| `/design-doc`, `/design-video` | Style a document or make a short video in the house style |
| `/spm` | Write product requirements for engineering |
| `/system-design <problem>` | Design a system (`--interview candidate\|interviewer`, `--review <doc>`, `--deep-dive <topic>`, `--html`, `--walkthrough`) |

`bugfix` and `pr-upsert` only run when you type the command — they push code and open PRs, so Claude never loads them on its own. `pr-merge` can also be started by Claude (pr-pulse's merge jobs use it); it never bypasses branch protection. Optional flags add second opinions and skip silently when the tool isn't installed: `--agy` and `--boost` challenge the root cause (they need the [agy](skills/agy/SKILL.md) setup above), and `--codex` challenges the fix diff (it needs the `openai-codex` plugin).

Installed as a plugin, the commands are namespaced: `/skills:pr-review`, `/skills:pr-feedback`, `/skills:bugfix`, `/skills:agy`, `/skills:retro`, `/skills:pr-merge`, and so on.

## Adding a skill

1. `cp -r templates/skill skills/<skill-name>`
2. Set `name` (must match the directory) and `description` (what it does and when to use it) in `SKILL.md`.
3. Add a row to the table above.

## License

[MIT](LICENSE)
