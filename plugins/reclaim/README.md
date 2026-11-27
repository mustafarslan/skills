# reclaim

**Claude Code only. macOS and Windows; the worktree half also runs on Linux (less tested).**

When your computer runs out of disk, run `/reclaim`. It removes the git worktrees you no longer need and old
Docker data. If Docker Desktop crashed because the disk filled up, it gets Docker running again. It asks
before every removal, and it backs up any work that isn't committed first.

## Install

```sh
claude plugin marketplace add mustafarslan/skills
claude plugin install reclaim@mustafarslan-skills
```

Then run `/reload-plugins` and `/reclaim:init`.

## What you need, and what happens without it

Only `git` and Python 3.9+ (`python3`, `python` or `py`) are required. Everything else is optional, and a missing piece makes reclaim more
careful or skips that part. It never makes it bolder, and it says so in the scan result.

| Missing | What reclaim does |
|---|---|
| `gh`, or not logged in | Scans on age and unpushed commits only, and tells you PRs were not checked. A `gh` that works but fails on one branch keeps that worktree |
| `lsof` (macOS) | Keeps every worktree, because it cannot tell which are in use. On Linux it reads `/proc` instead; on Windows it asks Windows itself (no tool needed) |
| Docker | Skips the Docker half with one line |
| Windows | Works without Git Bash's Unix tools. The Docker revive only reports until it has run live once on a Windows PC (DESIGN.md, 9b) |
| `jq` | Not needed. The start-of-session warning is plain Python |
| The reviewing tools used to build the plugin (`agy`, the advisor) | Not used at run time. reclaim depends on none of them |

## Use it

| You type | What happens |
|---|---|
| `/reclaim` | Shows what it would remove and asks you, then removes worktrees, revives a hung Docker, and prunes old images, build cache and stale containers |
| `/reclaim --dry-run` | Shows every table and removes nothing |
| `/reclaim --days 7` | Treats a worktree as old after 7 days instead of your setting |
| `/reclaim --no-merged` | Removes worktrees by age only, not because their PR merged |
| `/reclaim --worktrees-only` / `--docker-only` | Does only that half |
| `/reclaim:init` | Changes your repos, backup folder, age, protected containers and warning level |

At the start of a session, reclaim shows one line when free space is below your warning level (15 GB by
default), at most once an hour. It says nothing otherwise.

## What it removes, and what it never removes

A worktree is removed when its PR is merged, or when it has had no activity for your number of days. It is
kept when:

- its branch has an open PR;
- a process runs inside it;
- a paused session will resume there (if you wire in a session-parking tool; see DESIGN.md);
- it has commits that no remote holds;
- its HEAD is detached and no branch holds it;
- it has uncommitted or new files edited within your number of days;
- another repo or worktree sits inside it;
- it is the main checkout;
- it is locked, or uses a sparse checkout or `skip-worktree` files (git cannot show edits to those);
- its folder and the folder around it are both missing (an unplugged disk, not a deleted worktree);
- the GitHub lookup or the running-process check failed.

Removing a worktree deletes the folder only. The branch and its commits stay in git.

**Build folders in kept worktrees.** A worktree kept for an open PR or unpushed commits can still hold
gigabytes of `node_modules`, `target`, `.venv`, `build`, `dist`, `.gradle`, `Intermediate`, `Binaries` or a
build cache such as `DerivedDataCache` (add your own names with `build_dir_names`). reclaim offers them, per
tree and with their size, only when the tree has been idle for your number of days and is not kept because a
process, this session or a paused session uses it; main checkouts only with `buildirs_in_main: true`. A
folder qualifies only if git tracks nothing in it and `git check-ignore` agrees it is ignored, and it is
checked again right before it is deleted.

Before removing a worktree with uncommitted work, reclaim writes `<backup folder>/<name>-<date>/`:

- `tracked.patch`: the changes against HEAD;
- `staged.patch`: what was staged, which can differ from the files;
- `untracked.tgz`: the new files;
- `ignored.tgz`: gitignored files outside build folders, such as `.env.local`;
- `INFO.txt`: the branch, the commit and the restore steps.

The worktree is removed only after each archive reads back complete. reclaim checks each worktree again
right before removing it, and skips one that changed since the scan. It never retries with `--force`.

In Docker, reclaim removes unused images and build cache older than your number of days, plus containers
you pick that have been stopped that long or are stuck restarting. Containers on your keep-list are never
offered. **Volumes are never removed**: they hold your databases.

**Docker's disk file.** A prune frees space inside Docker's disk image, which is not always space on your
drive. reclaim shows the file's size next to what Docker says it holds:

- macOS: `Docker.raw` is sparse, so it gives space back by itself; reclaim only reports it.
- Windows: `docker_data.vhdx` (or the older `ext4.vhdx`) only grows. `docker compact` shrinks it, with
  Docker Desktop quit, after checking that nothing holds the file, in one UAC prompt (`Optimize-VHD`, or
  `diskpart` without the Hyper-V tools). It asks before stopping Docker's WSL distro, and again, naming
  your other distros, before `wsl --shutdown`. It never runs while Docker is starting or a build runs.
  Until it has run live once on a Windows PC, reclaim only reports the size there.

## Developer caches

`/reclaim` also offers the caches your tools keep, each with its size and how it clears, and clears only the
ones you pick:

| Cache | Clears |
|---|---|
| npm, yarn, pip, Go build cache, NuGet | all, with the tool's own command (`npm cache clean --force`, `yarn cache clean`, `pip cache purge`, `go clean -cache`, `dotnet nuget locals all --clear`) |
| pnpm store, uv | by age, with the tool's own prune (`pnpm store prune`, `uv cache prune`) |
| Cargo downloads | all (`registry/cache`, `registry/src`, `git/checkouts`; the index stays) |
| Gradle, Maven | by age: whole versions untouched for `cache_days` days (30 by default) |
| Xcode DerivedData, unavailable simulators (macOS) | all |
| Folders you list in `cache_dirs` | by age: entries untouched for `cache_days` days |

Each is looked for where that tool keeps it on your system (or where its own variable, such as `GOCACHE` or
`CARGO_HOME`, points). A cache is skipped while its tool runs, because an agent may be building with it. Without
the tool installed, an `all` cache's folder contents are deleted, never the folder itself, and links inside are
removed as links, never followed. Set `config set cache_dirs '["~/my-cache"]'` and `config set cache_days 14`.

## Which repos it cleans

You can list repos one by one, or give whole folders. Both work together.

- `repos`: exact main checkouts. `/reclaim:init` suggests the ones your recent sessions used.
- `roots`: folders that hold your repos, for example `~/Projects` and `/Volumes/MyDisk/projects`. Every scan
  walks each folder two levels deep and picks up the repos it finds, so a repo cloned tomorrow is covered
  with no setup. It never follows symlinks, never leaves the folder's disk, skips dot folders,
  `node_modules` and other build folders, never looks inside a repo, and stops at 2,000 folders per root
  with a warning. A linked worktree is never counted as a repo of its own; it is found through its main
  repo. A folder that is missing (an unplugged disk) is skipped with a warning.
- To clean everything under two folders: `config set roots '["~/Projects","/Volumes/MyDisk/projects"]'`.
  `config preview` lists the repos that would be scanned.

## Where data lives

- Settings: `config.json` in the plugin's data folder (`~/.claude/plugins/data/reclaim-<marketplace>/`). The
  session-start hook records that folder in `~/.claude/plugins/data/reclaim/data-dir`, so the command and the
  hook always read the same file. Before the hook has run once, the command uses `~/.claude/plugins/data/reclaim/`.
- The last scan: `last-scan.json` in the same folder. A removal must follow a scan from the last hour.
- Backups: the folder you chose in `/reclaim:init`.
