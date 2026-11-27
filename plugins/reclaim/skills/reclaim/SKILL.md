---
name: reclaim
description: Free disk space on this computer (macOS or Windows) - remove old git worktrees and ones whose PR merged (backing up uncommitted work first), clear build folders (node_modules, target, ...) in worktrees that are kept but idle, bring back a Docker Desktop that hung after the disk filled, prune old Docker images, build cache and stale containers, show (on Windows, shrink) Docker's disk file, and clear developer caches (npm, pnpm, yarn, pip, uv, NuGet, Cargo, Gradle, Maven, Go, Xcode). Use when the user says "/reclaim", "free up space", "disk is full", "clean old worktrees", "delete old docker images", "Docker won't start, no space left on device", or when the reclaim low-disk warning appears. Flags --days N, --dry-run, --no-merged, --worktrees-only, --docker-only.
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/scripts/reclaim *), AskUserQuestion
---

# reclaim: free disk space, lose nothing

Be friendly, concise and brief. Lead each step with its result.

`R` below means `${CLAUDE_PLUGIN_ROOT}/scripts/reclaim`. Every subcommand prints JSON. Act only through
`R`: it re-checks each item right before removing it and refuses anything the scan did not approve.
Running `git worktree remove`, `rm -rf`, `docker rm` or `docker volume` yourself skips those checks.

## 0. Setup and the starting point

1. Run `R config show`. If `configured` is false, say "reclaim isn't set up yet" and run `/reclaim:init`
   first, then come back here.
2. Run `R df` and remember each of its `drives` (volume, `free_gb`, `holds`) as **before**. When there is
   more than one, say in one line which drive is filling and what it holds (repos, backups, Docker's disk).

Flags: `--days N` overrides the configured age. `--no-merged` removes by age only.
`--worktrees-only` and `--docker-only` run only that section. `--dry-run` runs every read step,
shows every table, and asks nothing and removes nothing.

## 1. Worktrees

1. Run `R scan --days N` (add `--no-merged` if given). Each row has a `verdict`:
   - `remove`: clean. Only the folder goes; the branch and its commits stay in git.
   - `backup+remove`: uncommitted, new or gitignored files (`.env`, …) are copied to the backup
     folder first.
   - `prune`: the folder is already gone; git's list gets cleaned up.
   - `keep`: with `reasons` (open PR, in use, edited recently, commits on no remote, paused session,
     main checkout, PR lookup failed, locked, sparse checkout, unplugged disk).
   If the scan result has `warnings` (for example "PRs were not checked": `gh` is missing or not logged in),
   show them first, in one line each. Verdicts then rest on age and unpushed commits only; say so.
2. Show one table: the remove and backup+remove rows with name, size and why (`old` / `merged PR #n`),
   then a count of kept rows by reason. Show kept rows one by one only if the user asks.
3. One AskUserQuestion, multiSelect, with each group as an option and its total size:
   "Remove the clean ones (n, X GB)", "Back up and remove the ones with uncommitted work (n, X GB)".
   List the names inside each option's description.
4. Run `R remove PATH...` with the chosen rows' paths. Report each `removed` / `skipped` / `failed`
   with its `why`. A skipped row changed since the scan, so leave it. If the scan is over an hour old,
   `remove` refuses: run the scan again and show the table again.
5. **Build folders in kept worktrees.** Run `R buildirs scan` (it reads the scan from step 1). It lists
   `folders` such as `node_modules` or `target` inside worktrees that are kept but idle, each with its
   `tree`, `folder` and `size` (what a rebuild would download or compile again). If there are none, say
   nothing. Otherwise show one table grouped by tree, then one AskUserQuestion, multiSelect, one option per
   tree: "`<tree name>`: `<folders>` (X GB)". Run `R buildirs remove PATH...` with the chosen folders'
   `path`s and report each result. The worktrees themselves, their commits and their other files stay.

## 2. Docker

1. Run `R docker status`.
2. If `installed` is false, say so in one line (Docker isn't installed here) and skip this whole section.
   If `up` is false:
   - `down.hung` true: Docker Desktop crashed when the disk filled, and its backend is stuck in
     "stopping", so every relaunch hangs. Say this in one line and ask: "Kill the stuck Docker
     processes (pids …) and start Docker again?" On yes, run `R docker restart-hung`, then
     `R docker status` again.
   - `down.hung` false: say Docker isn't running and the reason isn't a full disk; tell the user to
     start Docker Desktop (the menu bar on a Mac, the Start menu on Windows). Skip the rest of this section.
   - On Windows, `down.hung` stays false until the revive has run live once there; if
     `down.hung_suspected` is true, say Docker looks hung after a full disk, list `down.pids`, and tell the
     user to quit Docker Desktop and start it again themselves. Never run `R docker restart-hung` with
     `--first-live-run`: that flag is for the tool's owner's one supervised run, not for this skill.
3. From `df`, show the reclaimable space for Images and Build Cache. Ask: "Prune unused images and build
   cache older than N days (about X GB)?" On yes, run `R docker prune --days N` and report both
   `reclaimed` values.
4. If `stale` has containers, show a table of name, image and why (`stopped n days` or
   `restarting in a loop`). Say in one line that the containers' volumes (their databases) stay.
   AskUserQuestion, multiSelect, grouping containers by name prefix (one compose project per option).
   Run `R docker rm NAME...` with the chosen names. Add `--prune-images` only if the user already said yes
   to pruning images in step 3; if they declined that, leave it off. Report each result. A `failed` row
   whose `why` says the container is running means it was started again since the check: leave it.
5. **Docker's disk file.** Run `R docker disk` (after any prune, so the numbers are current). Show each disk's
   `on_disk` size next to `inside.used` (what Docker says it holds), in GB.
   - macOS: say in one line that `Docker.raw` is sparse and gives space back by itself after a prune.
   - Windows, `compact.verified_on_windows` false: show the sizes and say that reclaim only reports Docker's
     disk on Windows for now; it does not compact it yet. Don't run `R docker compact`.
   - Windows, `compact.verified_on_windows` true and `compact.about_free` over 1 GB: ask "Shrink Docker's
     disk file (about X GB back)? Docker Desktop must be quit first, and Windows asks for admin once." On
     yes, run `R docker compact`. If it answers `needs: release`, ask "Stop Docker's WSL distro (`<running>`)?"
     and on yes run it again with `--release`. If it answers `needs: shutdown`, ask "Shut WSL down? It also
     stops `<other_running>`." and on yes add `--shutdown-wsl`. If it says `not now`, show its `why` and stop.
     Report `freed`.

Volumes are never removed by reclaim. If the user asks for that, show `docker system df -v` volume
sizes and let them run `docker volume rm` themselves, after they confirm which ones.

## 3. Developer caches

1. Run `R caches scan`. Each row has a `label`, a `size`, `how` it clears, `clears_with` (the command or the
   deletion it uses) and, when the cache's tool is running, `busy`:
   - `all`: the whole cache goes; the next build downloads what it needs again.
   - `by age`: only what hasn't changed for `days` days (the tool's own prune, or whole old entries).
2. Show one table of the caches over 100 MB, largest first: label, size, how. A `busy` cache gets
   "in use by X: skipped" and is not offered.
3. One AskUserQuestion, multiSelect, each offered cache as an option "<label> · X GB · all / by age", none
   chosen in advance. On macOS, Xcode's DerivedData and unavailable simulators are offered the same way,
   only on a yes.
4. Run `R caches clear ID...` with the chosen ids. Report each `cleared` / `partly` / `skipped` / `failed`
   with its `freed` size. A `skipped` cache's tool started since the scan: leave it.

## 4. Report

Run `R df`. One short summary:

- free space **before → after**, for each drive in `drives`;
- what was removed (worktrees, image space, build cache, containers, developer caches);
- the backup folder, if any backups were made. Each backup's `INFO.txt` holds its restore steps.

Then one line on what was kept and why, for the largest kept groups only.

## Never

- Remove a row whose verdict is `keep`, or re-run `remove` with a path that came back `skipped`.
- Remove anything with a `--dry-run`.
- Touch Docker volumes, or a container on the keep-list (`R config show` → `keep_containers`).
- Pass `--first-live-run`. It exists for the tool's owner to run a Windows step once by hand, never for this skill.
