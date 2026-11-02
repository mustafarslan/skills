# Project facts — finding them, and writing them down

The rebase, commit, pr-merge and pr-upsert skills are generic. What differs between
repositories — how to install, which checks to run, which files are generated, how PRs link
issues — lives in the repository at **`.claude/project-facts.md`**. The layout is in
`project-facts.template.md` next to this file.

## When to run this

A skill runs this procedure when `git-context.sh` printed `facts=missing`, or when it needs a
section the file does not have (`local-checks.sh` prints `NO_PROJECT_FACTS` or
`NO_CHECKS_SECTION`), or a section is malformed (`MALFORMED_CHECKS`). A section that says `none` is an answer: do not ask again.

Run it **once**, for the sections the calling skill needs, and fill in the others while you are
at it only if the evidence is plain. Never run a command you have not shown the user.

## 1. Gather evidence (read only)

Read what the repository already says about itself, from the repo root. Look, do not run:

- `package.json` `scripts` (and `workspaces`), `pnpm-workspace.yaml`, `turbo.json`, `nx.json`
- `Makefile`, `justfile`, `Taskfile.yml`
- `pyproject.toml` (`[tool.*]`, `[project.scripts]`), `tox.ini`, `noxfile.py`, `setup.cfg`
- `Cargo.toml`, `go.mod`, `build.gradle*`, `pom.xml`, `*.csproj`, `Gemfile`, `mix.exs`
- `.github/workflows/*.yml` (and other CI config): the lint, typecheck and test steps CI runs
  on a pull request are the best evidence of what "the checks" are
- `.pre-commit-config.yaml`, `CONTRIBUTING.md`, `AGENTS.md`, `CLAUDE.md`, the README's
  development section
- migrations (`alembic.ini`, `migrations/`, `prisma/`, `db/migrate/`) and generators
  (`openapi*`, `*.gen.*`, `generated/`, `codegen` scripts), and files whose header says
  "generated" or "do not edit"
- `.github/pull_request_template.md`; `git log --format=%s -30` (commit style, issue keys);
  `gh pr list --state merged --limit 10 --json body -q '.[].body'` when gh works (how PRs link
  issues, which review bots comment)

## 2. Draft

Fill only what the evidence shows. Prefer the commands CI runs. Make test commands **scoped**
(`{files}`) and capped in parallelism (`-n 2`, `--maxWorkers=2`) where the runner supports it.
Write `none` where the repository plainly has nothing (no migrations, no generators, no CI). A
repository with no checks at all is fine: `## checks` says `none`, and the skills say "no local
checks configured" instead of failing.

## 3. Confirm once

Show the draft, marking each line **found** (cite the file) or **guessed**. Then ask one
`AskUserQuestion`: *write it as shown* / *edit first* (they reply with changes) / *don't write a
file — use it for this run only*. Never ask section by section.

If the session cannot ask (a non-interactive run), do not guess: use only the **found** lines
for this run, write no file, and say which facts were missing.

## 4. Write

When the file already exists, **add only the missing section** (or fix only the malformed
lines `local-checks.sh` named with `MALFORMED_CHECKS`) and leave every other section exactly as
it is — it may hold decisions you cannot see the reasons for. Otherwise write
`.claude/project-facts.md` from the template's layout, without its example rows and with
its `<!-- -->` comments trimmed to one line each. Do not commit it yourself; say that it is new
and that committing it lets the team and CI agents share it (the commit skill will pick it up
with the next change if the user asks).
