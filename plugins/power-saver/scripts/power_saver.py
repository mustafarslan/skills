"""power-saver: one switch between unattended work (builds, tests, AI agents: CPU boost off, each NVIDIA GPU at a
share of its default power limit, screens dark) and full power for when you're at the PC.

    power-saver detect                     what this PC has and which levers apply (JSON)
    power-saver on [--keep-screen]         unattended work
    power-saver off                        full power, the plan you had before
    power-saver status                     mode, plan, each GPU now, the guard's last 24 hours, drift
    power-saver mode-line                  one line for the SessionStart hook when the mode is on, else nothing
    power-saver setup [options]            the one-time admin install (one UAC prompt); --uninstall removes it

Every command prints JSON; each lever is reported as applied, skipped, pending or failed, never just "done".
Nothing here needs admin. The GPU limit is changed by the guard (guard.ps1), which a SYSTEM scheduled task runs
every few minutes and when `on`/`off` start it. The only file a user can write that the guard reads is `mode`,
and the guard accepts only the word on or off from it.
"""
import argparse
import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import winpower as wp  # noqa: E402
from gpu_backends import is_virtual, nvidia, unsupported_note, vendor_of  # noqa: E402

TASK = 'power-saver'
CREATE_NO_WINDOW = 0x08000000


def system_tool(name, env=None):
    env = os.environ if env is None else env
    return os.path.join(env.get('SystemRoot', r'C:\Windows'), 'System32', name)


def powershell_exe(env=None):
    return os.path.join(system_tool('WindowsPowerShell', env), 'v1.0', 'powershell.exe')


def real_run(argv, timeout=60):
    """(exit code, output). stderr is added to the output only when the command failed."""
    kw = {'creationflags': CREATE_NO_WINDOW} if os.name == 'nt' else {}
    try:
        p = subprocess.run(argv, capture_output=True, timeout=timeout, **kw)
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, str(e)
    out = (p.stdout or b'').decode('utf-8', 'replace')
    if p.returncode != 0:
        out += (p.stderr or b'').decode('utf-8', 'replace')
    return p.returncode, out


class Ctx:
    """Everything that touches the machine, so tests can swap each part for a fake."""

    def __init__(self, run=None, win=None, root=None, state_dir=None, programdata=None, env=None,
                 sleep=time.sleep, now=None):
        self.env = os.environ if env is None else env
        self.run = run or real_run
        self.win = win or wp.Win()
        pd = programdata or self.env.get('ProgramData', r'C:\ProgramData')
        self.programdata = Path(pd)
        self.root = Path(root or self.env.get('POWER_SAVER_ROOT') or (self.programdata / 'power-saver'))
        local = self.env.get('LOCALAPPDATA') or str(Path.home() / 'AppData' / 'Local')
        self.state_dir = Path(state_dir or self.env.get('POWER_SAVER_STATE') or (Path(local) / 'power-saver'))
        self.sleep = sleep
        self.now = now or (lambda: datetime.now(timezone.utc))

    # files
    def config(self):
        try:
            return json.loads((self.root / 'config.json').read_text(encoding='utf-8-sig'))
        except (OSError, ValueError):
            return None

    def mode_word(self):
        """('on'|'off', ok). Anything but the two words counts as off, as in the guard."""
        try:
            raw = (self.root / 'mode').read_bytes()[:64]
        except OSError:
            return 'off', False
        word = raw.decode('utf-8', 'replace').replace('\ufeff', '').strip().lower()
        return (word, True) if word in ('on', 'off') else ('off', False)

    def write_mode(self, word):
        try:
            with open(self.root / 'mode', 'w', encoding='ascii', newline='\n') as f:
                f.write(word + '\n')
            return True, ''
        except OSError as e:
            return False, f'could not write the mode file ({e.strerror or e}); run /power-saver:setup again'

    def state(self):
        try:
            return json.loads((self.state_dir / 'state.json').read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return {}

    def save_state(self, st):
        self.state_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.state_dir / 'state.json.tmp'
        tmp.write_text(json.dumps(st, indent=2), encoding='utf-8')
        os.replace(tmp, self.state_dir / 'state.json')

    def log_path(self):
        return self.root / 'guard.log'


def lever(name, result, why):
    return {'lever': name, 'result': result, 'why': why}


# ---- powercfg ---------------------------------------------------------------------------------

def powercfg(ctx, cfg=None):
    return (cfg or {}).get('powercfg') or system_tool('powercfg.exe', ctx.env)


def get_active(ctx, pc):
    code, out = ctx.run([pc, '/getactivescheme'])
    return wp.active_plan(out) if code == 0 else None


def list_plans(ctx, pc):
    code, out = ctx.run([pc, '/list'])
    return wp.plans(out) if code == 0 else []


def plan_settings(ctx, pc, plan, subgroup):
    code, out = ctx.run([pc, '/qh', plan, subgroup])
    return wp.settings(out) if code == 0 else ({}, set())


def plan_name(plist, guid):
    for p in plist:
        if p['guid'] == guid:
            return p['name']
    return guid


# ---- detect -----------------------------------------------------------------------------------

def display_adapters(ctx):
    ps = powershell_exe(ctx.env)
    code, out = ctx.run([ps, '-NoProfile', '-NonInteractive', '-Command',
                         'Get-CimInstance Win32_VideoController | Select-Object Name,AdapterCompatibility | '
                         'ConvertTo-Json -Compress'])
    if code != 0 or not out.strip():
        return []
    try:
        data = json.loads(out.strip().lstrip('\ufeff'))
    except ValueError:
        return []
    rows = data if isinstance(data, list) else [data]
    return [{'name': (r.get('Name') or '').strip(), 'maker': (r.get('AdapterCompatibility') or '').strip()}
            for r in rows if isinstance(r, dict)]


def find_predecessors(ctx, pc, plist, cfg):
    """Earlier hand-made versions of the same idea: a script under ProgramData that sets `nvidia-smi -pl`, and power
    plans that aren't Windows' own or ours and cap the processor below 100%. Setup offers to replace them."""
    ours = (cfg or {}).get('saver_plan')
    found = {'scripts': [], 'plans': []}
    try:
        dirs = [d for d in ctx.programdata.iterdir() if d.is_dir()]
    except OSError:
        dirs = []
    for d in dirs:
        if d.resolve() == ctx.root.resolve():
            continue
        try:
            files = [f for f in d.iterdir() if f.suffix.lower() == '.ps1' and f.stat().st_size < 262144]
        except OSError:
            continue
        for f in files:
            try:
                text = f.read_text(encoding='utf-8', errors='replace').lower()
            except OSError:
                continue
            if 'nvidia-smi' in text and '-pl' in text:
                found['scripts'].append({'dir': str(d), 'script': str(f)})
                break
    for p in plist:
        if p['guid'] in wp.BUILTIN_PLANS or p['guid'] == ours:
            continue
        vals, _ = plan_settings(ctx, pc, p['guid'], wp.SUB_PROCESSOR)
        mx = vals.get(wp.PROCTHROTTLEMAX)
        if mx and mx['ac'] < 100:
            found['plans'].append({'guid': p['guid'], 'name': p['name'], 'max_processor_state': mx['ac']})
    return found


def detect(ctx):
    cfg = ctx.config()
    pc = powercfg(ctx, cfg)
    plist = list_plans(ctx, pc)
    active = get_active(ctx, pc)
    cpu = ctx.win.cpu()
    classes = ctx.win.core_classes()
    proc, _ = plan_settings(ctx, pc, active or 'SCHEME_CURRENT', wp.SUB_PROCESSOR)
    es, es_groups = plan_settings(ctx, pc, active or 'SCHEME_CURRENT', wp.SUB_ENERGYSAVER)
    laptop = ctx.win.has_battery()
    smi = nvidia.find_smi(ctx.env)
    cards = nvidia.query(ctx.run, smi)
    gpus = [{'vendor': 'nvidia', 'name': g['name'], 'index': g['index'], 'adjustable': g['adjustable'],
             'why': g['why'], 'default_w': g['default'], 'min_w': g['min'], 'max_w': g['max'],
             'tlimit': g['tlimit'] is not None} for g in cards]
    notes = []
    for a in display_adapters(ctx):
        v = vendor_of(a['name'], a['maker'])
        if is_virtual(a['name'], a['maker']) or (v == 'nvidia' and cards):
            continue
        gpus.append({'vendor': v, 'name': a['name'], 'adjustable': False, 'why': unsupported_note(v, a['name'])})
        notes.append(unsupported_note(v, a['name']))
    for g in gpus:
        if g['vendor'] == 'nvidia' and not g['adjustable']:
            notes.append(f"GPU: {g['name']}, {g['why']}, skipped")
    boost = wp.PERFBOOSTMODE in proc
    maxstate = wp.PROCTHROTTLEMAX in proc
    extra = [i + 1 for i, g in enumerate(wp.PROCTHROTTLEMAX_CLASSES) if g in proc]
    es_ok = wp.SUB_ENERGYSAVER in es_groups and wp.ESBATTTHRESHOLD in es
    adj = [g for g in gpus if g['vendor'] == 'nvidia' and g['adjustable']]
    levers = [
        lever('cpu', 'applies' if (boost or maxstate) else 'skipped',
              ('boost mode off' if boost else 'boost mode setting not on this PC')
              + (', max processor state 99%' if maxstate else ', max processor state setting not on this PC')
              + (f', also core class {", ".join(map(str, extra))}' if extra else '')),
        lever('gpu', 'applies' if adj else 'skipped',
              f'{len(adj)} NVIDIA GPU(s) with an adjustable power limit' if adj else
              ('no GPU with a power limit power-saver can change' if gpus else 'no GPU found')),
        lever('screen', 'applies', 'blanked at once by `on` (still connected), off after 2 minutes'),
        lever('energy_saver', 'applies' if es_ok else 'skipped',
              'Windows Energy Saver is available' if es_ok else 'Windows Energy Saver is not on this PC'),
    ]
    if laptop:
        levers.append(lever('power_mode', 'applies', 'a laptop: "Best power efficiency" power mode while on'))
    return {
        'platform': sys.platform,
        'cpu': {'name': cpu.get('name'), 'vendor': cpu.get('vendor'), 'hybrid': len(set(classes)) > 1,
                'cores': len(classes), 'boost_mode_setting': boost, 'max_state_setting': maxstate,
                'extra_core_classes': extra},
        'laptop': laptop,
        'gpus': gpus,
        'energy_saver': es_ok,
        'tools': {'powercfg': pc, 'nvidia_smi': smi},
        'active_plan': {'guid': active, 'name': plan_name(plist, active)},
        'levers': levers,
        'notes': notes,
        'predecessors': find_predecessors(ctx, pc, plist, cfg),
        'installed': cfg is not None,
    }


# ---- the guard's log --------------------------------------------------------------------------

def read_log(ctx, offset=0):
    try:
        with open(ctx.log_path(), 'rb') as f:
            f.seek(offset)
            data = f.read()
    except OSError:
        return []
    out = []
    for line in data.decode('utf-8', 'replace').replace('\ufeff', '').splitlines():
        line = line.strip()
        if line.startswith('{'):
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
    return out


def log_size(ctx):
    try:
        return ctx.log_path().stat().st_size
    except OSError:
        return 0


def parse_t(s):
    try:
        return datetime.strptime(s, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def start_guard(ctx):
    code, out = ctx.run([system_tool('schtasks.exe', ctx.env), '/run', '/tn', TASK])
    return code == 0, out.strip()


def wait_for_guard(ctx, offset, timeout=15.0):
    deadline = time.monotonic() + timeout
    while True:
        size = log_size(ctx)
        entries = read_log(ctx, offset if size >= offset else 0)
        if entries:
            return entries[-1]
        if time.monotonic() >= deadline:
            return None
        ctx.sleep(0.5)


def gpu_levers(ctx, cfg, offset):
    det = cfg.get('detected') or {}
    out = [lever('gpu', 'skipped', g['why']) for g in det.get('gpus', []) if g.get('vendor') != 'nvidia']
    smi = cfg.get('nvidia_smi')
    if not smi:
        if not out:
            out.append(lever('gpu', 'skipped', 'no NVIDIA GPU (nvidia-smi not found)'))
        return out
    started, why = start_guard(ctx)
    minutes = int(cfg.get('interval_minutes', 5))
    if not started:
        unit = 'a minute' if minutes == 1 else f'{minutes} minutes'
        out.append(lever('gpu', 'pending', f'could not start the task now ({why or "access denied"}): '
                                           f'the guard applies the GPU limit within {unit}'))
        return out
    entry = wait_for_guard(ctx, offset)
    if not entry:
        out.append(lever('gpu', 'pending', 'the task started but the guard has not logged yet; '
                                           'check `/power-saver status` in a minute'))
        return out
    live = {g['uuid']: g for g in nvidia.query(ctx.run, smi)}
    for g in entry.get('gpus') or []:
        name = g.get('name') or f"GPU {g.get('i')}"
        if g.get('result') == 'skipped':
            out.append(lever('gpu', 'skipped', f"{name}: {g.get('why')}"))
            continue
        if g.get('result') == 'failed':
            out.append(lever('gpu', 'failed', f"{name}: {g.get('why')}"))
            continue
        want = g.get('want')
        now = (live.get(g.get('uuid')) or {}).get('limit')
        hot = ' (held lower: hot)' if g.get('hot') else ''
        share = f" ({round(100 * want / g['default'])}% of its {g['default']:g} W default)" if g.get('default') else ''
        if now is not None and want is not None and abs(now - want) < 1:
            out.append(lever('gpu', 'applied', f'{name}: limit {want} W{share}{hot}'))
        else:
            out.append(lever('gpu', 'failed', f'{name}: the guard asked for {want} W but nvidia-smi reports {now} W'))
    if not entry.get('gpus'):
        out.append(lever('gpu', 'skipped', 'the guard found no NVIDIA GPU'))
    return out


# ---- on / off ---------------------------------------------------------------------------------

class NotSetUp(Exception):
    pass


def need_config(ctx):
    cfg = ctx.config()
    if not cfg or not cfg.get('saver_plan'):
        raise NotSetUp()
    return cfg


def cpu_lever(ctx, pc, saver, plist):
    active = get_active(ctx, pc)
    if active != saver:
        return lever('cpu', 'failed', f'Windows kept the plan {plan_name(plist, active)} active')
    vals, _ = plan_settings(ctx, pc, saver, wp.SUB_PROCESSOR)
    parts = []
    if wp.PERFBOOSTMODE in vals:
        parts.append('boost mode off' if vals[wp.PERFBOOSTMODE]['ac'] == 0 else
                     f"boost mode is {vals[wp.PERFBOOSTMODE]['ac']}, not off")
    if wp.PROCTHROTTLEMAX in vals:
        parts.append(f"max processor state {vals[wp.PROCTHROTTLEMAX]['ac']}%")
    perf = ctx.win.processor_performance(2.0)
    if perf is not None and perf > 100:
        return lever('cpu', 'failed', f'saver plan active ({", ".join(parts)}), but boost still on: this CPU ignores '
                                      f'the setting ({perf:g}% processor performance under load)')
    tail = f', {perf:g}% processor performance under load' if perf is not None else ''
    return lever('cpu', 'applied', f'saver plan active: {", ".join(parts) or "settings not readable"}{tail}')


def energy_lever(ctx, pc, saver, cfg):
    det = cfg.get('detected') or {}
    if not cfg.get('energy_saver', True):
        return lever('energy_saver', 'skipped', 'turned off in config (energy_saver: false)')
    if not det.get('energy_saver'):
        return lever('energy_saver', 'skipped', 'Windows Energy Saver is not on this PC')
    vals, _ = plan_settings(ctx, pc, saver, wp.SUB_ENERGYSAVER)
    v = vals.get(wp.ESBATTTHRESHOLD)
    if v and v['ac'] == 100:
        return lever('energy_saver', 'applied', 'set to always on in the saver plan (background work runs with '
                                                'EcoQoS: slower, never stopped)')
    return lever('energy_saver', 'failed', 'the saver plan does not hold the Energy Saver setting; run setup again')


def cmd_on(ctx, keep_screen=False):
    cfg = need_config(ctx)
    pc, saver = powercfg(ctx, cfg), cfg['saver_plan']
    plist = list_plans(ctx, pc)
    active = get_active(ctx, pc)
    st = ctx.state()
    if active and active != saver:
        st['back_plan'], st['back_plan_name'] = active, plan_name(plist, active)
    elif not st.get('back_plan'):
        st['back_plan'] = cfg.get('fallback_plan') or wp.BALANCED
    laptop = ctx.win.has_battery()
    if laptop:
        ov = ctx.win.get_overlay()
        if ov and ov != wp.OVERLAY_BEST_EFFICIENCY:
            st['back_overlay'] = ov
    st['mode'] = 'on'
    ctx.save_state(st)
    ok, why = ctx.write_mode('on')
    if not ok:
        return {'mode': 'unchanged', 'levers': [lever('mode', 'failed', why)]}
    offset = log_size(ctx)
    ctx.run([pc, '/setactive', saver])
    levers = [cpu_lever(ctx, pc, saver, plist)]
    if laptop:
        done = ctx.win.set_overlay(wp.OVERLAY_BEST_EFFICIENCY)
        levers.append(lever('power_mode', 'applied' if done else 'failed',
                            '"Best power efficiency"' if done else 'Windows refused the power mode change'))
    levers.append(energy_lever(ctx, pc, saver, cfg))
    levers += gpu_levers(ctx, cfg, offset)
    if keep_screen:
        levers.append(lever('screen', 'skipped', '--keep-screen'))
    else:
        mins = cfg.get('screen_off_minutes', 2)
        done = ctx.win.blank_screens()
        levers.append(lever('screen', 'applied' if done else 'failed',
                            f'screens blanked now (still connected), and off after {mins} minutes of no input'
                            if done else 'Windows refused the blanking message'))
    return {'mode': 'on', 'plan_to_go_back_to': st.get('back_plan_name') or st['back_plan'], 'levers': levers}


def cmd_off(ctx):
    cfg = need_config(ctx)
    pc, saver = powercfg(ctx, cfg), cfg['saver_plan']
    plist = list_plans(ctx, pc)
    have = {p['guid'] for p in plist}
    st = ctx.state()
    target, notes = st.get('back_plan'), []
    if not target or target == saver or target not in have:
        if target and target != saver and target not in have:
            notes.append(f"the plan from before ({st.get('back_plan_name') or target}) was deleted: back to Balanced")
        target = wp.BALANCED if wp.BALANCED in have else cfg.get('fallback_plan') or wp.BALANCED
    ok, why = ctx.write_mode('off')
    if not ok:
        return {'mode': 'unchanged', 'levers': [lever('mode', 'failed', why)]}
    offset = log_size(ctx)
    ctx.run([pc, '/setactive', target])
    now = get_active(ctx, pc)
    levers = [lever('cpu', 'applied', f'back to {plan_name(plist, target)}: boost as that plan sets it')
              if now == target else lever('cpu', 'failed', f'Windows kept {plan_name(plist, now)} active')]
    if st.get('back_overlay'):
        done = ctx.win.set_overlay(st['back_overlay'])
        levers.append(lever('power_mode', 'applied' if done else 'failed',
                            'power mode put back' if done else 'Windows refused the power mode change'))
    levers += gpu_levers(ctx, cfg, offset)
    done = ctx.win.wake_screens()
    levers.append(lever('screen', 'applied' if done else 'failed', 'screens on'))
    for k in ('back_plan', 'back_plan_name', 'back_overlay'):
        st.pop(k, None)
    st['mode'] = 'off'
    ctx.save_state(st)
    return {'mode': 'off', 'notes': notes, 'levers': levers}


# ---- status -----------------------------------------------------------------------------------

def log_summary(ctx, now):
    entries = read_log(ctx)
    since = now - timedelta(hours=24)
    watts = {'on': [], 'off': []}
    last, last_hot = None, None
    for e in entries:
        t = parse_t(e.get('t'))
        if not t:
            continue
        last = e
        if any('hot' in str(ev) for ev in e.get('events') or []):
            last_hot = e
        if t >= since and e.get('mode') in watts:
            draws = [g.get('draw') for g in e.get('gpus') or [] if isinstance(g.get('draw'), (int, float))]
            if draws:
                watts[e['mode']].append(sum(draws))
    return {
        'avg_gpu_watts_24h': {m: (round(sum(v) / len(v)) if v else None) for m, v in watts.items()},
        'samples_24h': {m: len(v) for m, v in watts.items()},
        'last_run': last.get('t') if last else None,
        'last_hot_step_down': ({'t': last_hot.get('t'), 'events': last_hot.get('events')} if last_hot else None),
        'last_entry': last,
    }


def guard_is_stale(ctx):
    """True when the admin-only copy of guard.ps1 isn't this plugin version's (a plugin update needs setup again)."""
    try:
        mine = (HERE / 'guard.ps1').read_bytes().replace(b'\r\n', b'\n')
        theirs = (ctx.root / 'guard.ps1').read_bytes().replace(b'\r\n', b'\n')
    except OSError:
        return False
    return mine.lstrip(b'\xef\xbb\xbf') != theirs.lstrip(b'\xef\xbb\xbf')


def cmd_status(ctx):
    cfg = ctx.config()
    if not cfg:
        return {'installed': False, 'hint': 'run /power-saver:setup'}
    pc, saver = powercfg(ctx, cfg), cfg.get('saver_plan')
    plist = list_plans(ctx, pc)
    active = get_active(ctx, pc)
    word, ok = ctx.mode_word()
    now = ctx.now()
    logs = log_summary(ctx, now)
    drift = []
    if not ok:
        drift.append('the mode file holds something other than on/off (the guard treats it as off)')
    if word == 'on' and active != saver:
        drift.append(f'mode is on but the plan is {plan_name(plist, active)}: the guard puts the saver plan back')
    if word == 'off' and active == saver:
        drift.append('plan says saver but mode is off: the guard switches back at its next run')
    interval = int(cfg.get('interval_minutes', 5))
    last = parse_t(logs['last_run'])
    if last is None:
        drift.append('the guard has never logged a run')
    else:
        idle = (now - last).total_seconds() / 60
        if idle > max(15, 3 * interval):
            drift.append(f"guard hasn't run for {int(idle)} minutes")
    if guard_is_stale(ctx):
        drift.append('the installed guard differs from this version of the plugin: run /power-saver:setup again')
    gpus_now = []
    for g in nvidia.query(ctx.run, cfg.get('nvidia_smi')):
        gpus_now.append({k: g[k] for k in ('index', 'name', 'limit', 'default', 'min', 'max', 'draw', 'temp', 'tlimit',
                                           'adjustable')})
    logs.pop('last_entry', None)
    return {
        'installed': True,
        'mode': word,
        'active_plan': {'guid': active, 'name': plan_name(plist, active), 'is_saver_plan': active == saver},
        'detected': cfg.get('detected'),
        'config': {k: cfg.get(k) for k in ('gpu_share', 'gpu_hot_share_on', 'gpu_hot_share_off', 'hot_margin_on',
                                           'hot_margin_off', 'hot_temp_on', 'hot_temp_off', 'hysteresis',
                                           'energy_saver', 'interval_minutes', 'run_rights')},
        'gpus_now': gpus_now,
        'guard': logs,
        'drift': drift,
        'note': 'Savings are not measured: only the GPU watts nvidia-smi reports are shown. Use a wall meter for '
                'the whole PC.',
    }


def mode_line(ctx):
    """For the SessionStart hook: one line when the mode is on, nothing otherwise. Files only, no commands."""
    word, ok = ctx.mode_word()
    if not ok or word != 'on':
        return ''
    cfg = ctx.config() or {}
    det = cfg.get('detected') or {}
    adj = [g for g in det.get('gpus', []) if g.get('vendor') == 'nvidia' and g.get('adjustable')]
    share = nvidia.clamp_share(cfg.get('gpu_share'), 0.7)
    what = 'CPU boost off' + (f', GPU at {round(share * 100)}%' if adj else '')
    return f'power-saver is ON ({what}): builds and tests run slower'


# ---- setup (the only part that asks for admin) -----------------------------------------------

def ps_quote(s):
    return "'" + str(s).replace("'", "''") + "'"


def setup_args(action, source, detect_file, result_file, share=None, energy_saver=None, every_minute=False,
               replace_dir=None, remove_plan=None, back_plan=None):
    """The command line for the elevated setup.ps1. Paths are double-quoted (Windows paths can't hold a quote)."""
    a = ['-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', f'"{source / "setup.ps1"}"',
         '-Action', action, '-Source', f'"{source}"', '-ResultFile', f'"{result_file}"']
    if detect_file:
        a += ['-DetectFile', f'"{detect_file}"']
    if share is not None:
        a += ['-Share', f'{float(share):.2f}']
    if energy_saver is not None:
        a += ['-EnergySaver', '1' if energy_saver else '0']
    if every_minute:
        a += ['-EveryMinute']
    if replace_dir:
        a += ['-ReplaceDir', f'"{replace_dir}"']
    if remove_plan:
        a += ['-RemovePlan', remove_plan]
    if back_plan:
        a += ['-BackPlan', back_plan]
    return ' '.join(a)


def elevated_command(ctx, arg_string):
    """powershell -EncodedCommand that starts setup.ps1 elevated (the one UAC prompt) and waits for it."""
    ps = powershell_exe(ctx.env)
    script = (f"$ErrorActionPreference = 'Stop'\n"
              f"try {{ $p = Start-Process -FilePath {ps_quote(ps)} -ArgumentList {ps_quote(arg_string)} "
              f"-Verb RunAs -Wait -PassThru -WindowStyle Hidden }}\n"
              f"catch {{ Write-Output ('UAC: ' + $_.Exception.Message); exit 1223 }}\n"
              f"exit $p.ExitCode\n")
    enc = base64.b64encode(script.encode('utf-16-le')).decode('ascii')
    return [ps, '-NoProfile', '-NonInteractive', '-EncodedCommand', enc], script


def guid_or_none(s):
    g = wp.guids(s or '')
    return g[0] if g and len((s or '').strip()) == 36 else None


def cmd_setup(ctx, uninstall=False, share=None, energy_saver=None, every_minute=False, replace_dir=None,
              remove_plan=None, dry_run=False):
    tmp = Path(tempfile.mkdtemp(prefix='power-saver-'))
    try:
        return _setup(ctx, tmp, uninstall, share, energy_saver, every_minute, replace_dir, remove_plan, dry_run)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _setup(ctx, tmp, uninstall, share, energy_saver, every_minute, replace_dir, remove_plan, dry_run):
    result_file = tmp / 'result.json'
    pre = None
    if uninstall:
        cfg = ctx.config()
        word, _ = ctx.mode_word()
        if cfg and word == 'on' and not dry_run:
            pre = cmd_off(ctx)
        args = setup_args('Uninstall', HERE, None, result_file, back_plan=ctx.state().get('back_plan'))
    else:
        if share is not None and not 0.3 <= float(share) <= 1.0:
            return {'error': 'share must be between 0.3 and 1.0 (a part of each GPU\'s default limit)'}
        det = detect(ctx)
        detect_file = tmp / 'detect.json'
        detect_file.write_text(json.dumps(det), encoding='utf-8')
        args = setup_args('Install', HERE, detect_file, result_file, share, energy_saver, every_minute,
                          replace_dir, guid_or_none(remove_plan) if remove_plan else None)
    argv, script = elevated_command(ctx, args)
    if dry_run:
        return {'dry_run': True, 'would_run': script}
    code, out = ctx.run(argv, timeout=900)
    try:
        result = json.loads(result_file.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        result = None
    if code == 1223 or 'UAC' in out:
        return {'ok': False, 'why': 'the UAC prompt was declined or failed: nothing changed', 'detail': out.strip()}
    if result is None:
        return {'ok': False, 'why': f'setup did not report back (exit {code})', 'detail': out.strip()[-2000:]}
    report = {'ok': bool(result.get('ok')), 'setup': result}
    if pre:
        report['switched_off_first'] = pre
    if not uninstall and result.get('ok'):
        started, why = start_guard(ctx)
        report['users_can_start_task'] = started
        if not started and not every_minute:
            report['hint'] = ('Windows did not let this account start the task, so `on` and `off` would wait for the '
                              "guard's next run. Run setup again with --every-minute for the 1-minute fallback.")
    if uninstall and result.get('ok'):
        try:
            (ctx.state_dir / 'state.json').unlink()
        except OSError:
            pass
    return report


# ---- main -------------------------------------------------------------------------------------

def main(argv=None, ctx=None):
    ap = argparse.ArgumentParser(prog='power-saver')
    sub = ap.add_subparsers(dest='cmd', required=True)
    sub.add_parser('detect')
    p_on = sub.add_parser('on')
    p_on.add_argument('--keep-screen', action='store_true')
    sub.add_parser('off')
    sub.add_parser('status')
    sub.add_parser('mode-line')
    p_set = sub.add_parser('setup')
    p_set.add_argument('--uninstall', action='store_true')
    p_set.add_argument('--share', type=float)
    p_set.add_argument('--energy-saver', dest='energy_saver', action='store_true', default=None)
    p_set.add_argument('--no-energy-saver', dest='energy_saver', action='store_false')
    p_set.add_argument('--every-minute', action='store_true')
    p_set.add_argument('--replace-dir')
    p_set.add_argument('--remove-plan')
    p_set.add_argument('--dry-run', action='store_true')
    a = ap.parse_args(argv)
    if a.cmd == 'mode-line':
        try:
            line = mode_line(ctx or Ctx())
        except Exception:      # a hook must never break a session
            line = ''
        if line:
            print(line)
        return 0
    if sys.platform != 'win32' and ctx is None:
        print(json.dumps({'error': 'power-saver v0.1 runs on Windows only (a macOS half is planned)'}))
        return 2
    ctx = ctx or Ctx()
    try:
        if a.cmd == 'detect':
            out = detect(ctx)
        elif a.cmd == 'on':
            out = cmd_on(ctx, a.keep_screen)
        elif a.cmd == 'off':
            out = cmd_off(ctx)
        elif a.cmd == 'status':
            out = cmd_status(ctx)
        else:
            out = cmd_setup(ctx, a.uninstall, a.share, a.energy_saver, a.every_minute, a.replace_dir,
                            a.remove_plan, a.dry_run)
    except NotSetUp:
        out = {'error': 'power-saver is not set up on this PC', 'hint': 'run /power-saver:setup (one UAC prompt)'}
    print(json.dumps(out, indent=2))
    return 0 if not out.get('error') else 1


if __name__ == '__main__':
    sys.exit(main())
