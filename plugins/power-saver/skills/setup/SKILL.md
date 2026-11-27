---
name: setup
description: Install, change or remove power-saver on this Windows PC - detect the CPU and GPUs, make the saver power plan, the admin-only folder and the SYSTEM task that sets GPU power limits, all with one UAC prompt. Also changes the GPU share or turns Energy Saver off, and replaces an older hand-made power script it finds. Use when the user says "/power-saver:setup", "set up power-saver", "change the GPU share", "uninstall power-saver", "/power-saver:setup --uninstall", or when /power-saver says it isn't set up. Safe to re-run.
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/scripts/power-saver *), AskUserQuestion
---

# power-saver setup

Be brief. Do what you can yourself and ask only what needs the user.

`P` below means `${CLAUDE_PLUGIN_ROOT}/scripts/power-saver`. Every subcommand prints JSON.

## Install, or change settings

1. Run `P detect`. Show in a few lines: the CPU (and hybrid or not), each GPU with its min / default / max watts
   or why it is skipped, whether Energy Saver is available, laptop or desktop, and each lever's `result` and
   `why`. If `installed` is true, say this run keeps the current settings except what they change.
2. If `predecessors.scripts` or `predecessors.plans` is not empty, an earlier hand-made version of the same idea
   is on this PC. Ask once (AskUserQuestion): "Replace the older power script in `<dir>` and the plan `<name>`?"
   - yes: pass `--replace-dir <dir>` (its scheduled tasks are removed, the folder is left for the user to delete)
     and `--remove-plan <guid>` for each plan they agree to remove.
   - no: say both would then set the GPU limit, so the older one should be stopped by hand.
3. Ask only if they haven't said: "GPU share while on?" with options 70% (default), 80% and 60%, each with the
   watts it gives on their cards (default x share, never below the card's minimum: say when the minimum wins).
   Pass `--share 0.7`. Energy Saver is on by default; pass `--no-energy-saver` only if they ask.
4. Say: "Windows will show one UAC prompt now; approve it." Then run `P setup` with the flags.
5. Read the result:
   - `ok` false: show `why` (for example, the prompt was declined: nothing changed) and stop.
   - `users_can_start_task` false: Windows did not let this account start the task, so `on` and `off` would wait
     for the guard's next run. Offer to run setup again with `--every-minute` (the guard then runs every minute;
     one more UAC prompt).
   - otherwise list `setup.steps` briefly and end with: "Run `/power-saver on` when you leave the PC working,
     `/power-saver off` when you're back."

## --uninstall

Ask once: "Remove power-saver (the task, the saver plan, its folder) and give each GPU its default limit back?"
On yes, say a UAC prompt follows and run `P setup --uninstall`. If the mode was on it switches off first. Report
`setup.steps`.

## Never

- Run setup.ps1, `powercfg`, `schtasks` or `nvidia-smi -pl` yourself.
- Pass `--replace-dir` or `--remove-plan` without the user's yes.
