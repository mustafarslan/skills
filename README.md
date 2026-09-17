# skills

A collection of [Claude skills](https://code.claude.com/docs/en/skills) I use and share.

## Available skills

| Skill | Description |
| --- | --- |
| [pr-review](skills/pr-review/SKILL.md) | Thorough PR review in an isolated worktree: baseline vs. head test runs, issue-driven acceptance checks, security/edge-case lenses, and a user-approved GitHub review |
| [pr-feedback](skills/pr-feedback/SKILL.md) | Work the review feedback on your own PR: fetch every thread (including bot findings hidden in collapsed sections), verify each claim before agreeing, fix what survives, and post user-approved replies |

## Installation

### Option 1: Claude Code plugin marketplace

This repo is a Claude Code plugin marketplace. In Claude Code, run:

```
/plugin marketplace add mustafarslan/skills
/plugin install skills@mustafarslan-skills
```

This installs every skill in the repo as a single plugin. Run
`/plugin marketplace update mustafarslan-skills` to pull new skills later.

### Option 2: Copy individual skills

Copy any skill directory into your personal or project skills folder:

```bash
git clone https://github.com/mustafarslan/skills.git
cp -r skills/skills/<skill-name> ~/.claude/skills/        # all projects
cp -r skills/skills/<skill-name> .claude/skills/          # current project only
```

### Option 3: Claude apps

Zip a skill directory and upload it in the Skills section of Claude's settings.

## Repository structure

```
.
├── .claude-plugin/
│   └── marketplace.json     # Plugin marketplace manifest
├── skills/                  # Published skills (auto-discovered)
│   └── <skill-name>/
│       ├── SKILL.md         # Required: frontmatter + instructions
│       ├── scripts/         # Optional: helper scripts
│       └── references/      # Optional: docs loaded on demand
├── templates/
│   └── skill/SKILL.md       # Starting point for new skills (not installed)
├── LICENSE
└── README.md
```

## Adding a skill

1. Copy the template: `cp -r templates/skill skills/<skill-name>`
2. Edit `skills/<skill-name>/SKILL.md`:
   - `name`: lowercase letters, numbers, and hyphens; must match the directory name.
   - `description`: what the skill does **and when to use it**. Claude uses this to decide when to load the skill.
3. Add a row to the **Available skills** table above.

Every directory under `skills/` is picked up automatically by the plugin; no
manifest changes are needed.

## License

[MIT](LICENSE)
