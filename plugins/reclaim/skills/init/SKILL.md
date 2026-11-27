---
name: init
description: Set up reclaim with the user - find the git repos with worktrees from their recent Claude sessions, choose the backup folder, the age after which a worktree counts as old, the Docker containers that must never be removed, and the free-space level for the start-of-session warning. Use when the user says "/reclaim:init", "set up reclaim", "change reclaim settings", or when /reclaim finds no config. Safe to re-run; it shows the current values as the defaults.
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/scripts/reclaim *), Bash(docker ps *), AskUserQuestion
---

# reclaim init

Set reclaim up together with the user. Be friendly, concise and brief. Do what you can yourself
and ask only what needs them.

`R` below means `${CLAUDE_PLUGIN_ROOT}/scripts/reclaim`. Config lives in reclaim's own data folder,
never in a repo.

1. Run `R config show`. If `configured` is true, list the current values in one line each and say this
   run changes only what they pick.
2. **Repos.** First ask one AskUserQuestion: "Clean every repo in whole folders, or pick repos one by one?".
   For whole folders, run `R config detect-roots`, offer up to 4 folders as "`<folder>` · `<n>` repos"
   (multiSelect, Other: they type a path, such as one on an external disk), and save with
   `R config set roots '["/folder/a","/folder/b"]'`. Then run `R config preview` and tell them how many repos
   it found and any warning. Whole folders cover repos cloned later too, so skip the rest of this step.
   For one by one, run `R config detect`. One AskUserQuestion, multiSelect: "Which repos should reclaim clean
   worktrees for?" Offer up to 4, the most worktrees first, as "`<path>` · `<n>` worktrees". Other: they
   type a path. Save with `R config set repos '["/path/a","/path/b"]'`.
   On Windows, write paths in these JSON lists with forward slashes (`'["C:/Users/me/Projects","D:/work"]'`):
   a backslash must be doubled inside JSON, and a forward slash needs nothing.
3. **Age and backups.** One AskUserQuestion with two questions:
   - "Remove worktrees with no activity for how long?" with options 3 days (default), 7 days and 14 days.
     Save with `R config set days 3`.
   - "Where should uncommitted work be backed up before a worktree is removed?" Offer the current
     `backup_dir` first, then `~/Desktop/worktree-backups` on a Mac or `~/reclaim-backups` elsewhere. Save
     with `R config set backup_dir PATH`.
4. **Containers to keep.** Run `docker ps -a --format '{{.Names}}'`. If Docker isn't installed or running, skip
   this step and say they can re-run init later. Otherwise one AskUserQuestion, multiSelect: "Which
   containers must reclaim never remove?" Offer the running ones, the local database first. Other:
   they type a name or glob (`k3d-*`). Save with `R config set keep_containers '["name","k3d-*"]'`.
5. **Warning.** One AskUserQuestion: "Warn at the start of a session when free space drops below?" with
   options 15 GB (default), 30 GB and "No warning". Save with `R config set warn_gb 15`, or
   `R config set hook false` for no warning.
6. Run `R config show` and read the result back in one short list. End with: "Run `/reclaim --dry-run`
   to see what it would clear, with nothing removed."
