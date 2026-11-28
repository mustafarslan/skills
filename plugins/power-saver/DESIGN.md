# power-saver: design

power-saver switches a Windows PC between two modes:

- **on**: the PC keeps working unattended (builds, tests, AI agents). That work must never fail; it may only run
  slower.
- **off**: full power for when you're at the PC. Everything goes back to exactly how it was.

This document says why each lever is in or out, how the parts fit, and what is still unverified.

## 1. Parts

```
skills/power-saver/SKILL.md   /power-saver on|off|status [--keep-screen]
skills/setup/SKILL.md         /power-saver:setup [--uninstall]
hooks/hooks.json              SessionStart -> scripts/mode-line.sh (one line while on), scripts/update-check
                              (one line when a newer version is published; once a day, installs nothing)
scripts/power-saver           sh launcher: the first of python3, python, py -3 that is 3.9+
scripts/power_saver.py        detect, on, off, status, mode-line, setup (never needs admin itself)
scripts/winpower.py           powercfg parsing (by GUID, indentation and hex, so any display language works) and
                              the Win32 calls: screens, laptop power mode, battery, core classes, % Processor
                              Performance (PdhAddEnglishCounter)
scripts/gpu_backends/         nvidia.py (the only backend in v0.1); AMD and Intel are detected and skipped
scripts/guard.ps1             the SYSTEM task's script (Windows PowerShell 5.1, ASCII)
scripts/setup.ps1             the elevated install and uninstall (-DryRun lists the steps)
```

Files on the machine:

| Path | Who can write | What |
|---|---|---|
| `%ProgramData%\power-saver\guard.ps1` | Administrators, SYSTEM | the copy the task runs |
| `%ProgramData%\power-saver\config.json` | Administrators, SYSTEM | tool paths, saver plan, shares and margins, what setup detected |
| `%ProgramData%\power-saver\mode` | also Users | the word `on` or `off` |
| `%ProgramData%\power-saver\guard.log`, `state.json` | SYSTEM | one JSON line per guard run; which cards are held for heat |
| `%LOCALAPPDATA%\power-saver\state.json` | the user | the plan (and laptop power mode) to go back to on `off` |

The plan to go back to lives in the user's own folder, not in `mode`: the guard must read nothing but one word
from a file Users can write, and only the user's own `off` needs that plan. If the guard finds the saver plan
active while the mode is off, it switches to the plan setup copied from (in the admin-only config).

## 2. The levers

### CPU: Windows' processor settings, checked after each switch

The saver plan is a copy of the plan that was active at setup (not a fixed Balanced GUID), with:

- **processor performance boost mode** (`PERFBOOSTMODE`, be337238-...) = 0, off;
- **maximum processor state** (`PROCTHROTTLEMAX`) = 99%, and the same for core classes 1 and 2 when Windows has
  those settings.

Both are set because some firmware ignores one of them; on CPPC/HWP systems a 99% maximum doesn't always stop
boost. Windows shows the class 1 and 2 settings on non-hybrid CPUs too, so they are set whenever present rather
than only on hybrid ones; on a CPU with one class they do nothing. Values are set for mains and battery.

`on` then measures `% Processor Performance` (PDH, English counter name so it works in any language) while one
core is kept busy for two seconds. Above 100% means the CPU is still boosting, and the CPU lever is reported as
failed: "boost still on: this CPU ignores the setting". `off` activates the exact plan that was active before
`on`, so someone on High performance or a vendor's plan isn't moved to Balanced. Running `on` twice never records
the saver plan as the one before.

### GPU: a share of each card's own default

Each NVIDIA GPU is read with `nvidia-smi --query-gpu=...`. The saver limit is `gpu_share` (default 70%) of that
card's default limit, rounded down to a whole watt and clamped to the card's own min and max. A card that reports
no range, or a min equal to its max (most laptop GPUs, some older cards), is reported and skipped.

T.Limit (`temperature.gpu.tlimit`, the degrees left before the card slows itself down) is queried on its own,
because older drivers reject a whole query that names a field they don't know. With T.Limit the hot guard steps a
card down when the headroom reaches `hot_margin_on` (6) or `hot_margin_off` (2); without it, at `hot_temp_on`
(83 °C) or `hot_temp_off` (87 °C). It releases `hysteresis` (5) degrees later, so it doesn't ping-pong around
one value. Held for heat, a card gets `gpu_hot_share_on` (60%) while on and `gpu_hot_share_off` (78%) while off,
again inside its range. Every value from config is clamped again in the guard.

The change needs admin, so the SYSTEM task applies it: at startup (the driver resets limits on a reboot), every
5 minutes, and at once when `on`/`off` start it. The guard also re-applies the plan that matches the mode, so
mode and plan can't drift apart. `-MultipleInstances IgnoreNew` keeps two runs from racing on the log. Numbers are
parsed with the invariant culture, and `[N/A]` is skipped, not cast.

AMD and Intel: Windows has no supported command-line power limit for them (AMD's is the ADLX SDK in a driver app,
Intel's is in its own app). They are named and skipped, and the CPU, screen and Energy Saver levers still apply.
A backend can be added in `gpu_backends/` with the same shape as `nvidia.py`.

### Screens

`on` posts `SC_MONITORPOWER` 2: the screens go dark but stay connected. Disconnecting a display (as
`DisplaySwitch` does) can break apps that render to it, so it is never done. The saver plan turns the screens
off after 2 minutes without input. `--keep-screen` skips the blanking. `off` posts `SC_MONITORPOWER` -1, asks
for the display and nudges the mouse by one pixel, since Windows doesn't always honour -1.

### Windows Energy Saver

In by default (`energy_saver: false` turns it off at setup). It applies EcoQoS to background processes, and
unattended builds are background processes, so it slows them; it doesn't stop them. Setup sets the Energy Saver
threshold (`ESBATTTHRESHOLD`, e69653ca-...) to 100%, always on, in the saver plan only, on mains and battery, and
only when the `SUB_ENERGYSAVER` subgroup exists. `off` undoes it by switching plans. **Unverified:** whether
Windows honours this on a desktop on mains power; the live check is the Energy Saver tile in Quick Settings.

### Laptops

On a PC with a battery, `on` also selects Windows' "Best power efficiency" power mode (the overlay, through
`PowerSetActiveOverlayScheme`) and `off` puts back the one that was set.

## 3. Left out on purpose

So nobody adds them later without new evidence:

- **GPU clock locks (`nvidia-smi -lgc` / `-lmc`):** unreliable on GeForce cards; a memory clock lock on a recent
  high-end card caused a large slowdown (NVIDIA developer forum; NVIDIA/open-gpu-kernel-modules issue 1266), and
  a locked clock can pin a card at P0 and raise idle draw.
- **CPU Eco Mode, PPT, PL1/PL2:** set in the BIOS, Ryzen Master or Intel XTU only, so they need a reboot or admin
  tools. Measured on a 16-core desktop CPU at 65 W, multi-core work lost about 37%.
- **EPP (energy performance preference):** suggested, but its effect on recent AMD CPUs is unmeasured. Waits for a
  measurement.
- **A maximum processor state below 99%** (for example 80%, which caps the clock): maybe a `--deep` level later,
  after it is measured.
- **Core parking:** rejected; it slows parallel builds most.
- **Network adapters (Wi-Fi, Ethernet), PCIe link power (ASPM), USB selective suspend, sleep and hibernate:**
  these belong to keeping a PC up and reachable, not to power. power-saver never reads or changes them, and a test
  checks that no command it builds or runs mentions an adapter, `netsh` or the network settings of a power plan.

## 4. Security

The guard is a SYSTEM task that reads one file Users can write. That is the risk, and it is handled like this:

- **Admin-only folder.** Setup refuses a folder that is a link or junction, makes Administrators the owner, and
  replaces the folder's whole DACL with a protected one (`D:PAI(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;0x1200a9;;;BU)`:
  SYSTEM and Administrators full control, Users read), so an entry left by whoever created the folder first is
  gone. It resets everything inside to inherit only that, removes links inside, and deletes and rewrites
  `guard.ps1`, `config.json` and `mode` rather than writing through whatever was there. An earlier `config.json` is
  read only when Administrators or SYSTEM own the folder and the file. Only `mode` gets Users "modify". Users
  cannot create files in the folder.
- **One word from `mode`.** The guard reads at most 16 bytes and accepts `on` or `off`; anything else counts as off
  and is logged without echoing the content. No number, path or command is ever read from it.
- **Values in the admin-only config.** The share and margins change only through `/power-saver:setup` (one UAC
  prompt) and are clamped again by the guard, inside each card's own min and max.
- **No PATH lookups.** Setup takes `powercfg` from System32 and `nvidia-smi` only from System32 or
  `Program Files\NVIDIA Corporation\NVSMI`, folders only administrators can write; the guard calls both by those
  absolute paths. A copy of `nvidia-smi` elsewhere on PATH is never used.
- **Task rights.** Setup adds one ACE, `(A;;GRGX;;;BU)` (Users: read and execute), to the task's security
  descriptor through the Task Scheduler COM API (`GetSecurityDescriptor` / `SetSecurityDescriptor`), and records
  the descriptor it reads back. Users may then start the task (`schtasks /run`), never change it. By default a
  standard account can't even query a SYSTEM task ("Access is denied"). If Windows refuses the ACE
  (`SetSecurityDescriptor` throws), setup registers the task to repeat every minute instead, and `on` says "the
  guard applies the GPU limit within a minute". After setup returns, `power-saver setup` tries `schtasks /run`
  from the unelevated account; that decides, and if it is refused it suggests `--every-minute`.

## 5. State and edge cases

- `on` twice: the plan to go back to is recorded only when the active plan isn't the saver plan.
- A reboot while on: the startup trigger re-applies the GPU limits and the saver plan.
- The plan to go back to was deleted: `off` falls back to Balanced and says so.
- `off` twice, or `off` before any `on`: nothing is saved, so the plan in use stays (unless it is the saver plan).
- A guard run already in flight when `on`/`off` start the task (the task ignores a second start) may log the old
  mode; that entry is not taken as the result, and the task is started once more.
- A bad `mode` file: counts as off; `status` flags it.
- `status` flags drift: the saver plan with the mode off, the mode on without the saver plan, and a guard that
  hasn't logged for 15 minutes (or three intervals).
- An earlier hand-made version (a script under `%ProgramData%` that runs `nvidia-smi -pl`, or a plan that caps the
  processor below 100%) is found by `detect`; setup replaces it only on the user's yes: it unregisters the tasks
  that run that script (the folder is left for the user) and deletes the plan.

## 6. Not verified yet

v0.1 has run on one Windows 11 desktop (one NVIDIA card, an AMD CPU). Not tested: another GPU, two GPUs, a
laptop, an Intel hybrid CPU (all covered by fakes only). To confirm on each new machine: that boost really stops
(`% Processor Performance` under load), that the Energy Saver tile turns on, and that a standard account can start
the task.

## 7. Later

A schedule (on at night, off in the morning, run by the same task); AMD and Intel GPU backends; a macOS half
(`pmset -c lowpowermode 1`); Linux (`cpupower` and `nvidia-smi`).
