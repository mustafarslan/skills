# Environment: worktree, local config, services

Read by `bugfix` §2. Everything here exists for one reason: the fix must be made and tested on
the latest default branch, without touching the user's checkout, their running services, or
their dev data.

## 1. The worktree

Resolve the **main** checkout first. You may be running from inside one of the repo's existing
worktrees, where `--show-toplevel` returns that worktree, not the repo.

```bash
SLUG=<slug from bugfix §1, e.g. proj-1234>
MAIN="$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")"
DEFAULT=$(gh repo view --json defaultBranchRef -q .defaultBranchRef.name)
WT="$MAIN/.claude/worktrees/bugfix-$SLUG"

[ -e "$WT" ] && echo "bugfix-$SLUG worktree exists — an earlier run? inspect it before reusing or removing"
git -C "$MAIN" fetch origin "$DEFAULT"
git -C "$MAIN" worktree add -b "<branch>" "$WT" "origin/$DEFAULT"
```

- **Branch name.** Use the repo's convention. Read `CONTRIBUTING.md`, and look at recent branch
  names (`git branch -r --sort=-committerdate | head -20`). Many trackers link a branch that
  carries the key. No convention → `bugfix/<slug>-<two-word-summary>`.
- **Base on `origin/$DEFAULT`, never the local default branch.** The local one may be days
  behind. "Still happens on latest main" only means something against the remote tip you just
  fetched.
- **A worktree that already exists** is either an earlier run of this skill or the user's own
  work. Look at its status and log before doing anything to it. Reuse it if it is yours and
  clean; otherwise ask.
- **`.claude/worktrees/` should be gitignored** so the worktree does not show up as untracked in
  the main checkout. If it isn't, say so in the report. Don't edit `.gitignore` as part of a
  bugfix.

**Every path passed to a file tool starts with `$WT`.** A path from the repo root silently reads
or edits the main checkout, and the fix never reaches the branch. Run commands as
`cd "$WT" && …` or `git -C "$WT" …`.

## 2. Local config: copy what git does not track

A new worktree holds only tracked files. The app usually needs gitignored local config —
`.env`, `.env.local`, a local settings file — and without it, the tests either fail for the
wrong reason or, worse, **pass against the wrong database** because the loader fell back to a
default.

1. **If the repo has a `.worktreeinclude`**, it is the list. It uses `.gitignore` syntax and
   names the ignored files a worktree needs. Claude Code applies it only to worktrees it
   creates itself, **not** to one made with `git worktree add`, so copy what it lists by hand:

   ```bash
   cd "$MAIN" && git ls-files --others --ignored --exclude-from=.worktreeinclude \
     | while read -r f; do mkdir -p "$WT/$(dirname "$f")" && cp -p "$f" "$WT/$f"; done
   ```

2. **Otherwise**, find the ignored env files without listing every dependency directory:

   ```bash
   git -C "$MAIN" ls-files --others --ignored --exclude-standard --directory | grep -i env
   ```

   Copy each one to the same relative path under `$WT`.

These files often hold real credentials. That is fine for the user's own repo. Never copy them
anywhere outside `$WT`, never commit them, and never print their values — print names only.

Then **install dependencies** in `$WT` with the repo's install command. A worktree has no
`node_modules`, virtualenv, or build output. Skipping this and then reporting install errors as
test failures is a wasted run.

## 3. Services: the repo's containers, not bare metal

If the repo ships a `compose.yaml` / `docker-compose.yml` or a dev-container setup, run its
services that way. Do not rely on whatever database or queue happens to be installed on the
host. The host's version, extensions and data are not what CI runs, and a bug that "doesn't
reproduce" on bare metal often just means the wrong service.

### Give this worktree its own compose project

Compose isolates by **project name**. By default that name comes from the directory, which
means two checkouts of the same repo can end up sharing — or stopping — each other's
containers. Name the project explicitly, on every compose command:

```bash
cd "$WT" && docker compose -p "bugfix-$SLUG" up -d
```

Run it from `$WT`, so images build from — and volumes mount — the worktree's code, not the
main checkout's.

### When the tracked compose file pins ports or names

Look for fixed host ports (`"5432:5432"`) and `container_name:` in the compose file. Either one
collides with the user's running stack even under a different project name. **Do not edit the
tracked compose file.** Instead:

1. **Ports from env vars?** If the file says `"${DB_PORT:-5432}:5432"`, set a free port in
   `$WT`'s copy of the env file. Done.
2. **Otherwise, an untracked override.** Write it outside the tree (or as an untracked file in
   `$WT` that you delete at cleanup), and pass both files:

   ```yaml
   # bugfix-override.yaml — remaps only what collides
   services:
     db:
       ports: !override
         - "55432:5432"
       container_name: !reset null
   ```

   ```bash
   docker compose -p "bugfix-$SLUG" -f compose.yaml -f "<path>/bugfix-override.yaml" up -d
   ```

   `!override` and `!reset` need Compose v2.24 or newer (`docker compose version`).
3. **Neither works** — an old Compose, or a setup script that hard-codes the stack. Reuse the
   user's running server, but with a **scratch database of its own**, named for this issue.
   Create it through the running container (`docker compose exec …` from `$MAIN`, since that is
   where the user's project lives). Host CLI clients often prompt for a password and hang.

Whichever route you take, repoint the connection settings in **`$WT`'s copy** of the config
only. Find every setting that names the service: the app, the test runner, and the migration
tool do not always read the same one. With `sed`, use `-i.bak` and delete the `.bak` afterwards;
that form works on both BSD and GNU sed.

### No containers in the repo

Then the tests run against whatever the repo's docs say to install. Still point them at a
scratch database rather than the user's dev one if the suite writes data. And say in the report
that the run used host services.

## 4. Sanity gate — before every test or migration run

Grep the connection setting out of the worktree's config and check it names **your** instance:

```bash
grep -E '^(DATABASE_URL|DB_[A-Z_]*|REDIS_URL)=' "$WT/.env"
```

Adjust the pattern to the settings you found in §3. If it still names the user's dev instance,
or the file is missing, **stop**. A missing env file usually fails open: the loader proceeds
silently with a default, and you test against the wrong database. Quote the gate's output once
in the evidence.

**Use the repo's entry points, not bare tool invocations.** The script CI runs often loads the
env file and sets config that a bare `pytest` / `jest` / `go test` skips — and the skipped
config is usually the connection setting you just repointed.

**Never run a migration without checking where it connects.** Migration tools often read the
connection from the shell environment rather than the env file. Find the documented invocation,
and source `$WT`'s env first if that is what it needs. An unmerged migration applied to the
user's dev database is not easily undone.

## 5. Teardown

At the end of the run, stop what **you** started, and nothing else:

```bash
cd "$WT" && docker compose -p "bugfix-$SLUG" down            # add -v only for volumes you created
```

Drop a scratch database if you made one. Delete an untracked override file if you put it in
`$WT`. Keep the worktree itself — the PR may need another round — and print the command that
removes it.
