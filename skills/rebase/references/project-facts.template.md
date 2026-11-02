# Project facts

<!-- Read by the rebase, commit, pr-merge and pr-upsert skills. Lives in the repository
     at .claude/project-facts.md, so the skills stay generic and each repo says how it is built.
     Commit it so everyone (and every agent) runs the same checks. Delete a section's example
     lines and write `none` when the project has nothing of that kind; a section that is missing
     makes the skill ask again, a section that says `none` does not.

     The skills run every command in this file, so it is code: review a change to it the way you
     would review a change to the Makefile. -->

## install

<!-- How to install dependencies in a fresh checkout or worktree. -->
- js: `npm ci`

## areas

<!-- How the repository splits into areas, and what to run for a change in each. The commit
     skill maps the changed files to areas and runs only those rows. `*` in a command is not
     expanded; write the command exactly as you would type it. A change to a shared path or a
     root dependency file counts as every area. Leave a cell `-` when the area has no such step. -->

| Area | Paths | Lint + format (autofix) | Typecheck | Tests (scoped; {files} = changed test files) |
| --- | --- | --- | --- | --- |
| web | `apps/web/` | `npm run lint:fix -w apps/web` | `npm run typecheck -w apps/web` | `npx vitest run --maxWorkers=2 {files}` |
| api | `services/api/` | `uv run ruff check --fix services/api && uv run ruff format services/api` | `uv run mypy services/api` | `uv run pytest -n 2 {files}` |

Shared paths (count as every area): `package.json`, `package-lock.json`, `packages/shared/`
Markdown lint, if any: `npx markdownlint-cli2 "**/*.md"`

## checks

<!-- Run by local-checks.sh: `### quick` after every rebase and for structural changes in
     /commit, `### quick` + `### full` with /rebase --test. One check per line,
     `- name: `command``, run with bash from the repo root. Write `none` under `## checks` when
     there are no local checks. $GIT_SKILLS_SCRIPTS is the rebase skill's scripts folder. -->

### quick
- migration-head: `test "$(uv run alembic heads | grep -c .)" -eq 1`
- generated-fresh: `"$GIT_SKILLS_SCRIPTS/generated-fresh.sh" 'npm run generate:api' api/generated`

### full
- lint: `npm run lint`
- typecheck: `npm run typecheck`
- test: `npm test`

## generated

<!-- Generated files: /rebase resolves a rebase step whose only conflicts are in these by
     regenerating, and /commit makes sure they are staged with the change. `path → command`.
     Lockfiles belong here too if you want /rebase to regenerate them. -->
- `api/generated/` → `npm run generate:api`
- `package-lock.json` → `npm install --package-lock-only`

Mixed files (hand-written prose with a generated block), with the block markers:
- `docs/config-reference.md` — `<!-- GENERATED-START -->` / `<!-- GENERATED-END -->`

Migration folders (must be staged with the code that needs them): `migrations/`

## commit

<!-- Commit message style. Default: match `git log`; with no clear style, the Linux kernel
     style (imperative subject ≤ 50 chars, blank line, body ≤ 72 columns on the why). -->
- style: match git log

## pr-merge

<!-- How /pr-merge lands a PR when the base has no merge queue: squash, merge or rebase (it must
     be enabled in the repo settings). And whether an approving review is required even when
     branch protection does not ask for one: `yes` (stop without one) or `ask` (ask the user). -->
- method: squash
- approval: ask

## pr

<!-- pr-upsert. Write `none` for anything the project does not have. -->
- issues required: yes   <!-- yes: a product-facing PR must link an issue; no: never ask -->
- tracker: GitHub Issues   <!-- or Jira, Linear, … (the skill uses a connected MCP server) -->
- key format: `#123`   <!-- or `ABC-123` -->
- link words: `Fixes #123` closes on merge; `Part of #123` links without closing
- housekeeping (exempt from an issue): tooling, CI, repo docs, trivial fixes
- review bot login: none   <!-- e.g. coderabbitai[bot] -->
- AI review trigger: none   <!-- e.g. `@claude review`; sticky comment marker: claude-review -->
- container build triggers: none   <!-- e.g. `Dockerfile`, `services/*/pyproject.toml` → `docker buildx build -f services/api/Dockerfile services/api` -->
- config-model files: none   <!-- e.g. `**/config.py`; feeds the PR's "Config changes" section -->
- local environment for a manual check: none   <!-- e.g. `docker compose up --build -d`, then http://localhost:3000 -->

Docs to update when an area changes:

| When the diff touches | Review and update |
| --- | --- |
| `db/models/`, `migrations/` | `docs/data-model.md` |
| `.github/workflows/` | `docs/ci.md` |
