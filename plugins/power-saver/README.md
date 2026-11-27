# power-saver

**Claude Code only. Windows; any CPU; NVIDIA GPUs (AMD and Intel GPUs are detected and skipped). v0.1 has been
run on one machine.**

One switch for your PC's power:

- `/power-saver on`: **unattended work** (builds, tests, AI agents). CPU boost off, each NVIDIA GPU at a share of
  its default power limit, the screens dark, Windows Energy Saver on. The work keeps going; it only runs slower.
- `/power-saver off`: **full power for when you're at the PC**. The power plan you had before, each GPU at its
  default limit, the screens on.

## Install

```sh
claude plugin marketplace add mustafarslan/skills
claude plugin install power-saver@mustafarslan-skills
```

Then run `/reload-plugins` and `/power-saver:setup` (one UAC prompt).

## What you need

Windows 10 or 11, Python 3.9+ (`python3`, `python` or `py`) and Git Bash (Claude Code's shell on Windows).
`nvidia-smi` comes with the NVIDIA driver. Nothing else is installed.

## What each lever does, and on which hardware

| Lever | on | off | Works on |
|---|---|---|---|
| CPU boost | a saver plan (a copy of the plan you had active) with boost mode off and max processor state 99%, also for the second and third core classes when Windows has them | the exact plan you had before `on`; Balanced if that one was deleted | any CPU whose firmware honours Windows' processor settings. `on` measures `% Processor Performance` under a short load and says "boost still on" if it doesn't |
| GPU power limit | each NVIDIA GPU at 70% of its default (configurable), never outside the card's own min and max | the card's default | NVIDIA desktop cards and the laptop cards that allow it; a card that doesn't is named and skipped. AMD and Intel GPUs: skipped (no supported command-line tool on Windows) |
| Hot guard | a card is held lower again near its own slowdown temperature (T.Limit headroom when the card reports it, else 83 °C), released 5 °C later | the same, with a smaller margin (else 87 °C) | NVIDIA |
| Screens | blanked at once (still connected, so running apps keep their windows), off after 2 minutes; `--keep-screen` skips the blanking | on | any |
| Windows Energy Saver | on in the saver plan: background work runs with EcoQoS (slower, never stopped) | off (the plan from before) | Windows 11 versions that have it; skipped otherwise. `energy_saver: false` at setup turns it off |
| Laptop power mode | "Best power efficiency" | the mode you had | laptops |

Network adapters (Wi-Fi, Ethernet) are never touched: power-saver reads and changes no adapter setting, and a test
checks that no command it builds mentions one.

## Use it

| You type | What happens |
|---|---|
| `/power-saver on` | Unattended work; reports each lever as applied, skipped, pending or failed |
| `/power-saver on --keep-screen` | The same, screens left on |
| `/power-saver off` | Full power and the plan from before |
| `/power-saver status` | What was detected, the mode and plan, each GPU now, the guard's last 24 hours, and any drift ("plan says saver but mode is off", "guard hasn't run for 15 minutes") |
| `/power-saver:setup` | Install, or change the GPU share or Energy Saver (one UAC prompt) |
| `/power-saver:setup --uninstall` | Removes the task, the saver plan and the folder, and gives each GPU its default limit back |

While the mode is on, each new Claude Code session starts with one line: "power-saver is ON (CPU boost off, GPU at
70%): builds and tests run slower", so a slow build isn't taken for a bug.

## Savings are not measured

No watts have been measured for these levers yet, so power-saver promises none. `status` shows only the GPU watts
`nvidia-smi` reports. CPU and wall power can't be read without admin tools: use a wall meter to see what the whole
PC saves.

## Security

The GPU limit needs admin, so a SYSTEM scheduled task (`power-saver`) applies it. It reads input a user can
write, so:

- its script and `config.json` live in `%ProgramData%\power-saver\`, which only administrators can change; the only
  file Users can write is `mode`, and the task accepts only the word `on` or `off` from it (anything else counts
  as off and is logged);
- it calls `nvidia-smi` and `powercfg` by the absolute paths setup found in the system folders, never through
  PATH;
- Users may run the task (so the switch is immediate), never change it. If Windows won't grant that, the task
  repeats every minute instead (`--every-minute`).

Details: [DESIGN.md](DESIGN.md).

## Updates and releases

Background auto-update is off for this marketplace until you turn it on: `/plugin` → **Marketplaces** →
`mustafarslan-skills` → auto-update on. Without it, `claude plugin update power-saver@mustafarslan-skills` fetches
a new release.

Claude Code installs a new copy only when the plugin's `version` changes (it reads `.claude-plugin/plugin.json`
first). **Bump `version` in `plugin.json` for every release**, even a one-line fix: a change merged without a new
version reaches nobody. Don't also set a version in `marketplace.json`.

After an update that changes `guard.ps1`, run `/power-saver:setup` again: the task runs the admin-only copy that
setup made, not the plugin's own file.

## Tests

```sh
sh plugins/power-saver/tests/run.test.sh
```

Fake `powercfg`, `nvidia-smi` and `schtasks`, with real outputs from one desktop as fixtures and made-up ones for
other cards (two GPUs, a laptop GPU that refuses a limit, an older driver without T.Limit, no NVIDIA at all), an
Intel hybrid CPU, an AMD CPU without the boost-mode setting and a laptop. On Windows the guard and setup scripts
also run in PowerShell against fake tools (setup only with `-DryRun`). Nothing on the machine changes.
