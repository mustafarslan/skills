---
name: reclaim
description: Free disk space on this Mac - remove old git worktrees and ones whose PR merged (backing up uncommitted work first), bring back a Docker Desktop that hung after the disk filled, and prune old Docker images, build cache and stale containers. Use when the user says "/reclaim", "free up space", "disk is full", "clean old worktrees", "delete old docker images", "Docker won't start, no space left on device", or when the reclaim low-disk warning appears. Flags --days N, --dry-run, --no-merged, --worktrees-only, --docker-only.
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
2. Run `R df` and remember `free_gb` as **before**.

Flags: `--days N` overrides the configured age. `--no-merged` removes by age only.
`--worktrees-only` and `--docker-only` skip the other half. `--dry-run` runs every read step,
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

## 2. Docker

1. Run `R docker status`.
2. If `installed` is false, say so in one line (Docker isn't installed here) and skip this whole section.
   If `up` is false:
   - `down.hung` true: Docker Desktop crashed when the disk filled, and its backend is stuck in
     "stopping", so every relaunch hangs. Say this in one line and ask: "Kill the stuck Docker
     processes (pids …) and start Docker again?" On yes, run `R docker restart-hung`, then
     `R docker status` again.
   - `down.hung` false: say Docker isn't running and the reason isn't a full disk; tell the user to
     start it from the menu bar. Skip the rest of this section.
3. From `df`, show the reclaimable space for Images and Build Cache. Ask: "Prune unused images and build
   cache older than N days (about X GB)?" On yes, run `R docker prune --days N` and report both
   `reclaimed` values.
4. If `stale` has containers, show a table of name, image and why (`stopped n days` or
   `restarting in a loop`). Say in one line that the containers' volumes (their databases) stay.
   AskUserQuestion, multiSelect, grouping containers by name prefix (one compose project per option).
   Run `R docker rm NAME...` with the chosen names. Add `--prune-images` only if the user already said yes
   to pruning images in step 3; if they declined that, leave it off. Report each result. A `failed` row
   whose `why` says the container is running means it was started again since the check: leave it.

Volumes are never removed by reclaim. If the user asks for that, show `docker system df -v` volume
sizes and let them run `docker volume rm` themselves, after they confirm which ones.

## 3. Report

Run `R df`. One short summary:

- free space **before → after**;
- what was removed (worktrees, image space, build cache, containers);
- the backup folder, if any backups were made. Each backup's `INFO.txt` holds its restore steps.

Then one line on what was kept and why, for the largest kept groups only.

## Never

- Remove a row whose verdict is `keep`, or re-run `remove` with a path that came back `skipped`.
- Remove anything with a `--dry-run`.
- Touch Docker volumes, or a container on the keep-list (`R config show` → `keep_containers`).
