# reclaim: design and rebuild guide

reclaim is a Claude Code plugin that frees disk space on a Mac or a Windows PC. It removes git worktrees you no longer need,
gets Docker Desktop running again after it hung on a full disk, and prunes old Docker data. It never deletes
work that isn't backed up.

This folder is complete: the plugin source is under `plugins/reclaim/` and its tests pass as shipped. This
document explains what it does, why each rule exists, and how to rebuild or extend it.

---

## 1. Why it exists

On a Mac used for development with many git worktrees, the disk fills quietly. A monorepo worktree with
`node_modules`, a Python venv and build output weighs 1.5 GB or more, and a hundred of them add up to over
150 GB. Docker adds old images, build cache and the containers of finished projects.

When the disk is full, Docker Desktop crashes writing its own log ("no space left on device"). Its backend
process then sticks in a "stopping" state, so every relaunch, from the menu bar or with `open -a Docker`,
hangs and never comes up.

Cleaning up by hand works, but it is easy to get wrong in ways that lose work:

- removing a worktree whose uncommitted edits you forgot about;
- `git worktree remove --force` used as a fallback when the plain remove refuses;
- acting on a status snapshot taken minutes earlier;
- missing a branch that has a new open PR because a bulk `gh pr list --limit N` came back exactly full.

reclaim turns that afternoon into one command, with each of those mistakes made impossible by code and
pinned by a test.

## 2. Plugin, not a skill

| Need | Skill | Plugin |
|---|---|---|
| A warning at session start when disk is low | no | yes (SessionStart hook) |
| Safety checks as tested code, with CI | awkward | `scripts/` plus `tests/` |
| Versioning and updates | no | `plugin.json` version |
| Per-user settings outside any repo | manual | `${CLAUDE_PLUGIN_DATA}` |

The safety checks are the value, so they live in Python, not in prose. The skills only orchestrate: they
show tables, ask, and call the CLI. Each skill's `allowed-tools` pre-approves just the CLI and
AskUserQuestion. The skill text says plainly that running `git worktree remove`, `docker rm` and the like
directly would skip the checks.

## 3. Layout

```
reclaim/                                  # a local marketplace you can add directly
├── .claude-plugin/marketplace.json       # lists one plugin: ./plugins/reclaim
├── DESIGN.md                             # this file
└── plugins/reclaim/
    ├── .claude-plugin/plugin.json        # name, version, description, author
    ├── README.md                         # user-facing: install, use, what is kept, where data lives
    ├── hooks/hooks.json                  # SessionStart -> scripts/low-disk.sh
    ├── skills/reclaim/SKILL.md           # /reclaim (or /reclaim:reclaim): the main flow
    ├── skills/init/SKILL.md              # /reclaim:init: writes config.json
    ├── scripts/reclaim                   # sh launcher: exec python3 reclaim.py "$@"
    ├── scripts/reclaim.py                # CLI (argparse), JSON out
    ├── scripts/plat.py                   # every macOS / Windows difference, in one place
    ├── scripts/common.py                 # run(), git(), config, free space, data folder
    ├── scripts/worktrees.py              # facts, verdicts, scan, remove
    ├── scripts/backup.py                 # patch + archives, verified
    ├── scripts/docker.py                 # status, hung detection, restart, prune, rm
    ├── scripts/low-disk.sh               # the hook
    └── tests/run.test.sh, test_reclaim.py
```

It needs only the standard library: Python 3.9 or newer, `git` and `gh` (logged in). On macOS it also uses
`lsof`, `tar` and `du`; on Windows it uses none of Git Bash's Unix tools (see 9b). The Docker part needs
Docker Desktop.

## 4. The CLI

All output is JSON. A subcommand changes nothing unless its name says it removes something.

| Command | Does |
|---|---|
| `reclaim df` | Free GB on `/` |
| `reclaim scan [--days N] [--no-merged] [--repo PATH]...` | One row per worktree of each configured repo, with a verdict. Writes `last-scan.json` |
| `reclaim remove PATH...` | Removes worktrees the last scan approved, re-checking each one |
| `reclaim backup PATH` | Backs up one worktree's uncommitted work |
| `reclaim docker status [--days N]` | Is the daemon up? If not, is it hung? Plus `docker system df` and stale containers |
| `reclaim docker restart-hung` | Only when hung: kills the stuck processes, `open -a Docker`, waits up to 3 min |
| `reclaim docker prune [--days N]` | `image prune -a` and `builder prune -a`, both with `--filter until=<N*24>h` |
| `reclaim docker rm NAME...` | Removes named containers that are still stale now (no `-v`), then prunes images |
| `reclaim config show \| set KEY VALUE \| detect` | Read, write, or find repos from recent Claude sessions |

## 5. Configuration

`${CLAUDE_PLUGIN_DATA}/config.json`. The session-start hook is given that variable (a folder named
`<plugin>-<marketplace>`); commands run through Bash are not. So the hook writes the folder it was given
to `~/.claude/plugins/data/reclaim/data-dir`, and `common.home()` resolves: `RECLAIM_HOME` (tests), then
`CLAUDE_PLUGIN_DATA`, then that pointer, then `~/.claude/plugins/data/reclaim/`. Both sides call the same
function, so they cannot disagree. A config saved in the plain fallback folder before the pointer existed is
still honoured by the hook. `tests/test_safety.py` pins this with the variable set.
`config.json` is validated on load (a bad file or value falls back to the default and is listed under
`config_problems`) and written atomically.

| Key | Default | Meaning |
|---|---|---|
| `repos` | `[]` | Main checkouts whose worktrees reclaim manages |
| `backup_dir` | `~/Desktop/worktree-backups` | Where backups go. Never a temp folder |
| `days` | `3` | No activity for this long counts as old |
| `keep_containers` | `[]` | Container names or globs never offered for removal (`k3d-*`) |
| `warn_gb` | `15` | The hook warns below this |
| `hook` | `true` | `false` silences the warning |

`config detect` reads the first `cwd` of up to 300 recent session transcripts in `~/.claude/projects/*/`.
It maps each one to its repo's main checkout (the parent of `git rev-parse --git-common-dir`), then
counts that repo's worktrees.

## 6. Worktrees: facts, then a verdict

For each worktree in `git worktree list --porcelain` (the first entry is the main checkout), `inspect()`
gathers:

| Fact | How | On failure |
|---|---|---|
| HEAD, branch | `rev-parse HEAD`, `symbolic-ref -q --short HEAD` | |
| Last commit time | `log -1 --format=%ct` | |
| Last checkout time | `reflog -1 --date=unix --format=%gd HEAD` (the `{epoch}`) | 0 |
| Changed and new files | `status --porcelain -z --untracked-files=all` | keep |
| Ignored files | `ls-files -z --others --ignored --exclude-standard --directory`, minus build folders | keep |
| Recent edit | mtime of the changed and new files only | |
| Commits on no remote | `rev-list --count HEAD --not --remotes` | keep |
| Detached and unreachable | `for-each-ref --contains HEAD` over heads, remotes and tags is empty | keep |
| Nested checkouts | any `.git` below the root, including just inside build folders | |
| In use | one machine-wide `lsof -a -d cwd -Fpcn`; any process cwd at or under the tree (Windows: 9b) | keep |
| PRs | `gh pr list --head <branch> --state all`; a detached `...-<n>` folder uses `gh pr view n` | keep |
| Merged and safe | a MERGED PR whose `headRefOid` has local HEAD as an ancestor | |

**Keep reasons**, any one of which keeps the tree:

- it is the main checkout;
- this session runs inside it;
- a process runs inside it;
- a paused session will resume there (see §10);
- its branch has an open PR, even if an older PR on the same branch merged;
- changed or new files were edited after the cutoff, unless the tree is merged-safe and clean;
- it holds another repo or worktree anywhere inside;
- commits that no remote holds, unless merged-safe;
- a detached HEAD that no ref holds;
- any check failed: git status, the ignored-files listing, the commit count, `gh`, or `lsof`;
- it is newer than the cutoff and not merged-safe.

**Removable** when nothing keeps it and either:

- it is old: `max(last commit, last checkout) < now - days`; or
- it is merged-safe, unless `--no-merged` was passed.

The verdict is then:

- `remove` when there are no changed, new or ignored files;
- `backup+remove` otherwise;
- `prune` when the folder is already gone.

### Why the activity signal is what it is

- **Not raw file mtimes.** Tools rewrite tracked files with identical content: a monorepo config file
  got a fresh mtime in every worktree. Those trees looked active forever.
- **Not ignored files.** `.env` and built binaries get regenerated. They are backed up, but they don't
  count as activity.
- **The reflog.** A worktree added an hour ago on a two-month-old commit is new, not old. Its reflog
  says so.
- **Merged and clean trees** go regardless of fresh mtimes: everything in them is in the PR.

## 7. Removal: re-check, back up, re-check, remove

`remove PATH...`:

1. Refuses unless `last-scan.json` exists and is under an hour old.
2. For each path, resolved with `realpath` so `/var` and `/private/var` match:
   - it must be in the scan with verdict `remove`, `backup+remove` or `prune`;
   - `inspect()` runs again: a `keep` now means skip;
   - the **fingerprint** must match the scan's. The fingerprint is a hash of HEAD, every changed file's
     status, path, size and mtime, and the ignored-file list.
3. For `backup+remove`, it runs `backup()`, then **inspects again and compares the fingerprint with the
   pre-backup one**. Edits that landed during a long tar stop the removal, and the backup is kept.
4. Runs `git worktree remove`. It adds `--force` **only** after a verified backup that still matches, and
   only when tracked or untracked changes exist (ignored files don't block a plain remove). It never
   retries with `--force` after a refusal. stderr goes into the result.
5. Catches any exception per tree and reports it as `failed`, so one surprise can't lose the batch report.
6. Runs `git worktree prune` only for repos where this run removed something. A global prune would also
   drop entries for worktrees on an unplugged disk, which nobody approved.

## 8. Backups

`<backup_dir>/<name>-<YYYYmmdd-HHMMSS>[-n]/`:

- `tracked.patch`: `git diff HEAD --binary`, read and written as bytes so non-UTF-8 files round-trip;
- `untracked.tgz`: from `git ls-files --others --exclude-standard -z`, passed to `tar --null -T`;
- `ignored.tgz`: ignored entries outside build folders, never containing another checkout;
- `INFO.txt`: worktree, branch, head, counts, and the restore steps:
  ```
  git worktree add <path> <branch or head>
  cd <path> && git apply <folder>/tracked.patch
  tar -xzf <folder>/untracked.tgz && tar -xzf <folder>/ignored.tgz
  ```

A backup counts as `ok` only when all of these hold:

- the free space is at least the estimated size plus 1 GB, checked before anything is written;
- each archive lists back (`tar -tzf`) at least as many entries as went in;
- the patch on disk is exactly as long as git's output.

A name collision, such as two trees with one name or a retry, gets a `-2`, `-3` suffix.

Build folders (`BUILD_DIRS`) are never backed up and never count as activity: `node_modules`, `.venv`,
`venv`, `.next`, `.turbo`, `__pycache__`, `.pytest_cache`, `.mypy_cache`, `.ruff_cache`, `dist`, `build`,
`coverage`, `target` and `.cache`. Checkouts just inside them are still detected, to depth 3.

## 8b. Build folders in kept worktrees (0.4.0, `scripts/buildirs.py`)

`buildirs scan` reads the last worktree scan (an hour at most) and looks inside each tree whose verdict is
`keep` and that is idle: `old` is true, no uncommitted file was edited since the cutoff, and no keep reason
says it is used (in use, this session, a paused session, the process check failed, edited, newer than the
cutoff). Main checkouts count only with `buildirs_in_main: true`. In those trees, up to four levels down and
never inside another checkout, a link or junction, it offers folders named `node_modules`, `target`, `.venv`,
`build`, `dist`, `.gradle`, `Intermediate`, `Binaries`, `DerivedDataCache` or a `build_dir_names` entry, when
`git ls-files -- <dir>` is empty, `git check-ignore -q -- <dir>/` succeeds, no checkout sits inside, and no
process is in it. It writes `last-buildirs.json`.

`buildirs remove PATH...` takes only folders that scan offered, within the hour. For each it inspects the tree
again (idle, not in use), runs every folder check again, checks for files other programs hold open (Windows),
and deletes through the shared delete routine.

## 9. Docker

- **Down and hung** needs all three facts:
  - a `com.docker.backend` or `docker-agent` process from `Docker.app` is alive (`pgrep -f`);
  - the backend log's last "backend state changed to X" says `stopping`;
  - the log tail (400 KB of `~/Library/Containers/com.docker.docker/Data/log/host/com.docker.backend.log`)
    contains "no space left on device".

  Only then is `restart-hung` allowed. It `kill -9`s those pids (never `vmnetd`, which runs as root),
  runs `open -a Docker`, and polls `docker info` for 3 minutes. If Docker is down for any other reason,
  the user is told to start it from the menu bar. Windows: 9b.
- **Prune** uses age filters only, so nothing newer than N days goes.
- **Stale containers** are those in state `exited`, `dead` or `created` whose `FinishedAt` (else
  `Created`) is at least N days old, plus `restarting` ones (crash loops). Running and paused containers
  are never stale, and the keep-list filters by `fnmatch`.
- **`docker rm`** re-checks staleness at call time and uses plain `docker rm` **without `-v`**, so a
  container started again since the check is refused by Docker, not killed; `-f` only for one stuck
  restarting. It then prunes images only when the user said yes to that, never build cache.
- **Volumes are never touched**: no `-v`, no `volume prune`, no `system prune --volumes`. Volumes hold
  databases. If you ask, the skill shows their sizes and leaves the removal to you.

## 9b. Windows

Every difference lives in `scripts/plat.py`. On macOS and Linux each of its functions computes what 0.3
computed in place (the same `du -sk`, `tar --null -T`, `lsof` and `/`-string tests); Windows gets its own
branch, built on the Win32 API through `ctypes`. No admin, nothing to install, and no Git Bash Unix tool.

- **In use.** Windows has no `lsof` and no `/proc`. The deciding check opens each folder of the tree with no
  sharing at all (`CreateFileW`, share mode 0, `FILE_FLAG_BACKUP_SEMANTICS`) and closes it again. A process
  whose current folder is that folder holds it open, so the open fails with a sharing violation; this works
  for every user's processes, elevated ones too. Only the exact folder counts (a process in `a/b` holds
  `a/b`, not `a`), so every real folder is checked, never through a junction. The test proves it with a
  real child process in a subfolder. A second, read-only pass reads each of this user's processes' current
  folders from their own memory (`NtQueryInformationProcess` and `ReadProcessMemory`) only to *name* who is
  there. If the probe can't run, every tree is kept.
- **Paths.** git prints `C:/x`; reclaim compares with `normcase` and `commonpath`, reports relative paths
  with `/`, and reads and deletes past 260 characters through the `\\?\` form. git runs with
  `core.longpaths=true`. Programs are found on absolute `PATH` entries only, never in the current folder
  (Windows searches that first, so a planted `git.exe` would run). Arguments to a `.cmd` (npm, pnpm, yarn)
  are quoted so `|` and `&` reach it as text; one cmd.exe can't take (`%`, a quote) is refused.
- **Junctions** (pnpm, `node_modules` links) are never entered: walks skip them, sizes don't count what they
  point to, backups store them as links, and a delete removes the link only. `git worktree remove` leaves a
  junction (and the folders above it) behind, so reclaim removes what is left the same way afterwards.
- **Locked files.** Windows can't delete a file another program has open, so before `git worktree remove`
  every file is opened the same no-sharing way. One that fails keeps the whole tree, reported as
  "locked by <program>" (named by the Restart Manager, read-only). If a lock still hits partway, the result
  says how many files are left and where; the commits are in git and the uncommitted work in the backup.
  Nothing is "put back" into the folder: a backup holds the uncommitted files only.
- **Backups** use Python's `tarfile` (Git Bash's tar can't take `C:\` paths) with the same read-back count
  check. INFO.txt gives Windows restore steps, with the `tar.exe` Windows ships.
- **Docker** is found on `PATH` or in its install folder (`%ProgramFiles%\Docker\Docker`, or per user
  `%LOCALAPPDATA%\Programs\DockerDesktop`): a session started before the install doesn't have it on `PATH`.
  Its processes (`Docker Desktop.exe`, `com.docker.backend.exe`, `com.docker.build.exe`) are matched by path
  inside that folder; `com.docker.service` (SYSTEM) is never touched. The WSL state comes from `wsl -l -v`
  (UTF-16, read by position because the header is localised), the log from
  `%LOCALAPPDATA%\Docker\log\host\com.docker.backend*.log`.
- **Launchers.** `scripts/reclaim` and the hook take the first of `python3`, `python` and `py -3` that runs
  Python 3.9+: on some PCs `python3` is the Microsoft Store's stub. The hook is still run by `sh` (Claude Code
  on Windows has Git Bash; power-saver's `sh` SessionStart hook was seen firing on Windows).

### Windows: first live runs

The revive (`docker restart-hung`) and the disk compact (`docker compact`, 0.4.0) were written without a
Windows Docker Desktop that had ever started, so the log lines and the disk paths are the Mac's or the
documented ones. Until each step has run live once on a Windows PC, reclaim only reports there:
`LIVE_ON_WINDOWS` in `docker.py` is False, `down.hung` stays False (`down.hung_suspected` carries the three
facts), and the step refuses unless it is given `--first-live-run`. The skill never passes that flag. The
owner runs each step once by hand, watching, and then sets its entry to True in a commit that records what
the log said.

## 9c. Docker's disk file (0.4.0, `scripts/vdisk.py`, `scripts/compact.ps1`)

`docker disk` lists Docker's disk images with their size and their real size on disk (`st_blocks` on
macOS, `GetCompressedFileSizeW` on Windows), next to the sum of `docker system df`'s sizes when Docker is up.

- **macOS**: `Docker.raw` (from `settings-store.json`'s `DataFolder`, else the default) is sparse on APFS, so
  there is nothing to compact; the report says so.
- **Windows**: `docker_data.vhdx`, or `ext4.vhdx` in older versions, under `%LOCALAPPDATA%\Docker\wsl\` or
  the `CustomWslDistroDir` of Docker's settings. `docker compact` refuses unless every one of these holds,
  in this order, and changes nothing until they do:
  1. the step has run live once (`LIVE_ON_WINDOWS['compact']`), or `--first-live-run`;
  2. no Docker Desktop process (by path) and no `docker`, `docker-compose` or `docker-buildx` command runs:
     not while Docker is starting or a build runs;
  3. Docker's own WSL distros are stopped, or `--release` (the user said yes) stops them with
     `wsl --terminate`;
  4. the VHDX opens with no sharing (nothing holds it), or `--shutdown-wsl` (a second yes, after the user
     was told which other distros run) runs `wsl --shutdown`, and then it must open;
  5. one elevated PowerShell runs `compact.ps1`: `Optimize-VHD -Mode Full` if the Hyper-V tools are there,
     else `diskpart` (`attach vdisk readonly`, `compact vdisk`, and `detach vdisk` in a `finally`). It writes
     a JSON result to a file that reclaim reads back; no file is a failure, never a success (power-saver
     0.1.0 lost its elevated reply because it read stdout).
- **Sparse mode is left out.** WSL 3.0.5 lists `wsl --manage <distro> --set-sparse true` (no `--allow-unsafe`
  in its help), but it targets a distro's own disk, and Docker's data disk is a separate VHDX. It has not been
  tried on one, so reclaim doesn't offer it.

## 9d. Developer caches (0.4.0, `scripts/caches.py`)

`caches scan` lists each known cache that exists here: its folders, its size, how it clears and, when a
process of its tool runs, `busy`. `caches clear ID...` re-reads the process table and skips a busy cache.

- **Where**: each tool's own default for the system (`%LOCALAPPDATA%` on Windows, `~/Library/Caches` on macOS,
  `~/.cache` elsewhere), or its variable (`GOCACHE`, `CARGO_HOME`, `GRADLE_USER_HOME`, `UV_CACHE_DIR`,
  `NUGET_PACKAGES`). A missing folder is skipped silently.
- **All**: the tool's own command when it is installed, else the folder's contents through the shared delete
  routine (links removed as links, the folder itself kept).
- **By age**: the tool's own prune (pnpm, uv), else whole entries whose newest file and folder time is older
  than `cache_days`: a Maven version folder (it holds a `.pom`), a Gradle `files-2.1/group/module/version`,
  a build-cache file, or a child of a folder in `cache_dirs`.
- **Busy**: a process whose program, or one of the first four words of its command line (so `node npm-cli.js`
  counts as npm and `node server.js` doesn't), is the tool's; for Gradle and Maven, the daemon's class name
  anywhere in the command line.
- Left out: `%TEMP%`, which is noisy and often locked.

## 10. Extension point: paused sessions

`worktrees.parked_folders()` returns `None` in this version, so the check is skipped and the scan reports
`park_checked: false`. If you use a tool that pauses Claude sessions and resumes them later, make it return
the set of `realpath`s of those sessions' working folders. reclaim then keeps any worktree containing one.
Return `None` when the tool isn't installed, never an empty set: an empty set would mean "checked, and
nothing is parked".

## 11. The hook

`scripts/low-disk.sh` runs at SessionStart with a 10-second timeout. It always exits 0, and it prints
nothing when any of these hold:

- there is no config;
- `jq` is missing;
- the hook is off;
- free space is at or above `warn_gb`;
- it already warned within the last hour (`last-warning` stamp file).

Otherwise it prints hook JSON: `systemMessage`, which the user sees, and
`hookSpecificOutput.additionalContext`, so Claude can offer `/reclaim`.

One jq pitfall: `.hook // true` returns `true` for `false`, because `//` treats `false` as missing. Use
`if .hook == false then "off" else "on" end`.

### Per drive (0.4.0)

`df` keeps `free_gb` (for `/`, or the home drive on Windows) and adds `drives`: one row per drive or volume
that holds the system, a repo, a repo folder, the backup folder or Docker's disk image, with its free and
total space and what it holds. A path is placed by its nearest existing folder (a backup folder not made yet
counts where it will be), and a drive that isn't there is left out. Windows groups by volume
(`GetVolumePathNameW`); macOS by the space a volume reports, so `/` and the Data volume of one APFS container
are one row and an external SSD is another. The hook warns for each row below `warn_gb`, naming the drive and
what it holds. It only reads the config and checks files: no git, no Docker command.

## 12. The skills

**`/reclaim`** (flags `--days N`, `--dry-run`, `--no-merged`, `--worktrees-only`, `--docker-only`):

0. Set up:
   - read the config; if it isn't configured, run `/reclaim:init`;
   - record free space as *before*.
1. Worktrees:
   - `scan`, then one table of removable rows (name, size, why), plus kept counts by reason;
   - one multi-select question: clean ones, and ones that need a backup, each with its total size;
   - `remove` the chosen paths and report each result. Skipped rows changed since the scan and are
     left alone.
2. Docker:
   - `status`; if hung, explain why and ask before `restart-hung`;
   - ask before `prune`, showing the reclaimable space;
   - list stale containers grouped by compose-project prefix, say that volumes stay, ask, then `rm`.
3. Report free space before and after, what was removed, where backups went, and the largest kept groups.

`--dry-run` runs every read step and shows every table, then asks nothing and removes nothing.

**`/reclaim:init`** asks for the repos (from `config detect`), the age, the backup folder, the containers to
keep, and the warning level, then reads the config back.

## 13. Tests (37, about 12 s)

`tests/test_reclaim.py` builds throwaway git repos with a bare remote. `gh`, `lsof` and `docker` are fakes
on `PATH`, driven by environment variables. Commit and reflog times are set through
`GIT_COMMITTER_DATE`. Each risk has a case:

| Risk | Test |
|---|---|
| A clean remove falls back to `--force` | spy on git calls; no `--force` |
| A tree changed after the scan | untracked file with an old mtime → skipped by fingerprint |
| An edit during the backup | the backup function edits a file → skipped, edit intact |
| A failed backup, or too little space | no removal; refusal message |
| A path the scan kept | refused |
| A branch with unpushed commits, or an unreachable detached HEAD | keep |
| An open PR next to an older merged one | keep |
| A merged PR that doesn't hold local HEAD | keep |
| A merged clean tree with fresh mtimes | remove |
| A merged tree with fresh uncommitted edits | keep |
| A fresh new file in an old tree | keep |
| A fresh mtime on a clean tracked file | still removable |
| A worktree just added on an old commit | keep (reflog) |
| A gitignored file written just now | backup, not activity |
| `.env.local` | lands in `ignored.tgz` |
| A same-repo worktree nested inside | outer kept; inner's uncommitted file survives a remove attempt |
| A foreign repo in an ignored folder, or under `dist/` | keep |
| A non-ASCII file name edited recently | keep (`status -z`) |
| `lsof` missing or failing, or `gh` failing | keep |
| A backup-name collision | two folders |
| `docker rm` | exactly `rm -f NAME`; no `-v`, no `volume`, no `builder` |
| Kept, running or paused containers | never removed |
| Hung detection | needs the process, the "stopping" state and ENOSPC together |
| The hook | silent without config, with enough space, or when off; JSON once, then silent within the hour |

Run them with `sh plugins/reclaim/tests/run.test.sh`.

## 14. Install and rebuild

Install from the marketplace this plugin ships in:

```sh
claude plugin marketplace add mustafarslan/skills
claude plugin install reclaim@mustafarslan-skills
```

Then start a new session and run `/reclaim:init`, then `/reclaim --dry-run`.

To try it in a single session without installing:
`claude --plugin-dir ./plugins/reclaim`, then `/reclaim:reclaim --dry-run`.

Bump `version` in `plugin.json` on every change: installed copies update only when it changes. The data
folder follows `${CLAUDE_PLUGIN_DATA}`, which Claude Code names `<plugin>-<marketplace>`; the hook records
it for the CLI (§5), so no path is hard-coded.

To rebuild from scratch, work in this order, testing each step before the next:

1. `common.py`, then `worktrees.py` facts (§6) with tests for each keep reason.
2. `backup.py` (§8) with its verification.
3. `remove` (§7): fingerprint, both re-checks, no force fallback, per-tree error isolation.
4. `docker.py` (§9).
5. The CLI, the skills, the hook and the README.

## 14b. Changes in 0.2.0

Found by an adversarial review and checked against the code before each fix. Each has a test in
`tests/test_safety.py`.

- **One config folder** for the hook and the CLI (§5).
- **Ignored files are fingerprinted** by size and mtime, not only name, so a `.env.local` edited after the
  scan or during the backup stops the removal.
- **No blanket `git worktree prune`** after a removal (it also drops records of worktrees on an unplugged
  disk). A `prune` verdict clears only that worktree's own record. A missing folder whose parent is also
  missing is kept as "unplugged disk?".
- **Kept as well:** locked worktrees, sparse checkouts and `skip-worktree` files, and a merged PR on a shared
  branch name (`main`, `master`, ...) never counts as merged work.
- **Bare repos:** the bare entry is not a checkout, and `config detect` returns the bare repo itself.
- **Backups also save `staged.patch`** (the index can differ from the files).
- **Docker:** `docker rm` without `-f` (only a container stuck restarting gets `-f`), so one started since the
  check is refused instead of killed; image pruning after `rm` only with `--prune-images`; "no space left" must
  be in the last 100 log lines, and the hung state must still hold after a 5 s wait before any `kill -9`.
- **Without optional tools:** no `gh` or not logged in degrades with a warning (PRs not checked); `/proc` is
  read on Linux; the hook is Python (no `jq`); `docker status` reports `installed` and `platform`; no
  `~/Desktop` is created on Linux.
- **CLI:** `--days 0` is honoured, and `config set` rejects bad JSON and wrong types.

Deliberately not done: skipping `gh` for `--no-merged` (it would hide open PRs, which are a keep reason), and
choosing the disk to check from the repos' volume (it checks `/`).

## 14c. Changes in 0.3.0

- **`roots`**: folders of repos, scanned two levels deep on every run (`find_repos`), so users with several
  repo folders, or an external disk, can say "all my repos" without listing each one. Configured `repos` and
  found repos are de-duplicated by (device, inode). `config detect-roots` suggests parent folders and
  `config preview` shows the repos a scan would use.
- A repo with only its main checkout is not scanned: nothing to clean, and it kept the scan slow with 50+ repos.
- A missing worktree whose parent folder is empty (an unmounted mount point) is kept, not pruned.
- Suggested by a second-model review (agy, Neon Medium); each point was checked against the code first.
- Not done: a per-root exclude list and a repo-count cap (the folder cap and warning are enough), and checking
  the disk that holds the repos instead of `/` (`df` still reads `/`).

## 15. Known limits

- macOS and Windows. The worktree half also works on Linux, but it is untested there. On Windows the Docker
  revive and compact only report until they have run live once (9b).
- It is a heuristic: a worktree you are reading but not editing, with no process open inside it, counts
  as idle.
- A scan calls `gh` once per worktree, six at a time. Thousands of worktrees would run into GitHub's rate
  limits.
- Removing a worktree removes the folder only. Branches stay, so delete merged branches separately if
  you want.
- Docker's own disk image (`Docker.raw`) doesn't shrink on the spot after a prune. Docker Desktop
  reclaims the space over time. On Windows the VHDX needs `docker compact` (9c).
