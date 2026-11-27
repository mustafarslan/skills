# reclaim

**Claude Code only. macOS fully; the worktree half also runs on Linux (less tested).**

When your Mac runs out of disk, run `/reclaim`. It removes the git worktrees you no longer need and old
Docker data. If Docker Desktop crashed because the disk filled up, it gets Docker running again. It asks
before every removal, and it backs up any work that isn't committed first.

## Install

```sh
claude plugin marketplace add mustafarslan/skills
claude plugin install reclaim@mustafarslan-skills
```

Then run `/reload-plugins` and `/reclaim:init`.

## What you need, and what happens without it

Only `git` and `python3` are required. Everything else is optional, and a missing piece makes reclaim more
careful or skips that part. It never makes it bolder, and it says so in the scan result.

| Missing | What reclaim does |
|---|---|
| `gh`, or not logged in | Scans on age and unpushed commits only, and tells you PRs were not checked. A `gh` that works but fails on one branch keeps that worktree |
| `lsof` (macOS) | Keeps every worktree, because it cannot tell which are in use. On Linux it reads `/proc` instead |
| Docker | Skips the Docker half with one line |
| macOS | The Docker revival (`open -a Docker`, Docker Desktop's log) is macOS only; worktrees work anywhere git does |
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

## Where data lives

- Settings: `config.json` in the plugin's data folder (`~/.claude/plugins/data/reclaim-<marketplace>/`). The
  session-start hook records that folder in `~/.claude/plugins/data/reclaim/data-dir`, so the command and the
  hook always read the same file. Before the hook has run once, the command uses `~/.claude/plugins/data/reclaim/`.
- The last scan: `last-scan.json` in the same folder. A removal must follow a scan from the last hour.
- Backups: the folder you chose in `/reclaim:init`.
