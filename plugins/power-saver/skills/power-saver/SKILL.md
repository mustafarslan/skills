---
name: power-saver
description: Switch this Windows PC between unattended work and full power. "on" is for leaving it to run builds, tests and AI agents alone - CPU boost off, each NVIDIA GPU at a share of its default power limit, screens dark, Windows Energy Saver on; the work only runs slower, it never stops. "off" is full power for when you're at the PC, with the power plan you had before. Use when the user says "/power-saver on", "/power-saver off", "/power-saver status", "power saver on", "I'm leaving the PC working", "save power while I'm away", "I'm back, full power", or asks whether power-saver is on. Flag --keep-screen for on.
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/scripts/power-saver *)
---

# power-saver: on, off, status

Be brief. Lead with the result.

`P` below means `${CLAUDE_PLUGIN_ROOT}/scripts/power-saver`. Every subcommand prints JSON. Act only through `P`:
it checks each lever after switching. Running `powercfg` or `nvidia-smi` yourself skips those checks.

If a command returns `error` "not set up", say so in one line and offer `/power-saver:setup` (one UAC prompt).
On anything but Windows, `P` says v0.1 runs on Windows only; pass that on.

## /power-saver on [--keep-screen]

1. Run `P on` (add `--keep-screen` if given). It can take up to about 20 seconds: it samples the CPU under a
   short load and waits for the guard to set each GPU.
2. Report one line per lever, from `levers`: its `result` (applied, skipped, pending or failed) and its `why`.
   Never sum it up as "done".
   - `cpu` failed with "boost still on": this CPU ignores Windows' boost setting. Say so plainly; the GPU and
     screen levers still apply.
   - `gpu` pending: the task could not be started now, so the limit lands at the guard's next run (the `why`
     says when).
   - `energy_saver`: applied means the setting is in the saver plan. Background work runs with EcoQoS: slower,
     never stopped.
3. Unless `--keep-screen` was given, the screens are now dark (still connected). Any key or mouse move wakes them.

## /power-saver off

Run `P off` and report each lever the same way. Mention `notes` if there are any (for example: the plan from
before was deleted, so the PC went back to Balanced).

## /power-saver status

Run `P status`. Show, in this order and briefly:
- the mode and the active plan (and whether it is the saver plan);
- what was detected (`detected`: CPU, GPUs with their min/default/max watts, Energy Saver, laptop or not) and the
  notes on what is skipped;
- each GPU now (`gpus_now`): limit, draw, temperature;
- from the guard's log: the average GPU watts in each mode over the last 24 hours, and the last hot step-down;
- every line of `drift`, if any, first and in bold.

Say once that savings are not measured: only the GPU watts nvidia-smi reports are shown, and a wall meter is the
way to measure the whole PC.

## Never

- Run `powercfg /setactive`, `/setacvalueindex`, `nvidia-smi -pl` or `schtasks` yourself.
- Edit the files in `%ProgramData%\power-saver\` by hand. Config changes go through `/power-saver:setup`.
