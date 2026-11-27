"""Docker Desktop on macOS and Windows: is it up, is it hung after a full disk, and what can be pruned.

Volumes are never touched: no `-v`, no `volume prune`, no `system prune --volumes`.

Windows (WSL 2 backend): the hung test and the revive are written but stay off until they have run live
once on a Windows PC (LIVE_ON_WINDOWS). Until then reclaim only reports there, and `restart-hung` needs
`--first-live-run`, which /reclaim never passes.
"""
import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import plat
from common import run

BACKEND_LOG = Path.home() / 'Library/Containers/com.docker.docker/Data/log/host/com.docker.backend.log'
# The processes that hold a hung Docker Desktop. vmnetd runs as root and is left alone.
HUNG_PATTERN = r'Docker\.app/Contents/(MacOS/com\.docker\.backend|Resources/cli-plugins/docker-agent)'

# Windows steps that have run live once on a Windows PC. Each one only reports until then.
LIVE_ON_WINDOWS = {'revive': False, 'compact': False}
# Docker Desktop's own processes on Windows, matched by path inside its install folder. com.docker.service
# runs as SYSTEM (it needs admin) and is never touched.
WIN_PROCESSES = ('docker desktop.exe', 'com.docker.backend.exe', 'com.docker.build.exe')
WSL_DISTROS = ('docker-desktop', 'docker-desktop-data')


def win_install_dirs():
    """Where Docker Desktop installs on Windows: per machine, or per user (newer installers)."""
    env = os.environ
    dirs = [os.path.join(env.get('ProgramFiles') or r'C:\Program Files', 'Docker', 'Docker')]
    if env.get('LOCALAPPDATA'):
        dirs.append(os.path.join(env['LOCALAPPDATA'], 'Programs', 'DockerDesktop'))
    return dirs


def cli():
    """The docker command, or None. Windows: on PATH, else inside Docker Desktop's install folder (a session
    started before the install doesn't have it on its PATH yet)."""
    if not plat.WINDOWS:
        return 'docker' if shutil.which('docker') else None
    found = plat.which('docker')
    if found:
        return found
    for d in win_install_dirs():
        f = os.path.join(d, 'resources', 'bin', 'docker.exe')
        if os.path.isfile(f):
            return f
    return None


def docker(*args):
    """A docker command line: ['docker', ...] on the Mac, as before; the found docker.exe on Windows."""
    return [(cli() or 'docker') if plat.WINDOWS else 'docker', *args]


def desktop_exe():
    for d in win_install_dirs():
        f = os.path.join(d, 'Docker Desktop.exe')
        if os.path.isfile(f):
            return f
    return None


def daemon_up():
    rc, _, _ = run(docker('info', '--format', '{{.ServerVersion}}'), timeout=20)
    return rc == 0


def _win_log():
    """The Windows backend log: the newest com.docker.backend*.log in Docker's log folder, or None."""
    folder = Path(os.environ.get('LOCALAPPDATA') or '.') / 'Docker' / 'log' / 'host'
    try:
        logs = sorted(folder.glob('com.docker.backend*.log'), key=lambda p: p.stat().st_mtime)
    except OSError:
        return None
    return logs[-1] if logs else None


def _log_tail(lines=600):
    given = os.environ.get('RECLAIM_DOCKER_LOG')
    log = Path(given) if given else (_win_log() if plat.WINDOWS else BACKEND_LOG)
    if not log or not log.exists():
        return []
    with open(log, 'rb') as f:
        f.seek(0, 2)
        f.seek(max(0, f.tell() - 400_000))
        return f.read().decode(errors='replace').splitlines()[-lines:]


def hung_state():
    """Why Docker is down, from its own processes and log. 'hung' needs all three facts."""
    if plat.WINDOWS:
        return _hung_state_windows()
    rc, out, _ = run(['pgrep', '-f', HUNG_PATTERN])
    pids = [int(p) for p in out.split()] if rc == 0 else []
    tail = _log_tail()
    states = [m.group(1) for line in tail for m in [re.search(r'backend state changed to (\w+)', line)] if m]
    # Only the last lines count: an old full-disk error plus a normal Quit must not look like a hang.
    enospc = any('no space left on device' in line for line in tail[-100:])
    last_state = states[-1] if states else None
    return {
        'pids': pids,
        'last_state': last_state,
        'disk_full_in_log': enospc,
        'hung': bool(pids) and last_state == 'stopping' and enospc,
    }


# ---------- Windows ----------

def win_docker_pids(procs=None):
    """Windows: pids of Docker Desktop's own processes, by program path inside its install folder."""
    dirs = win_install_dirs()
    out = []
    for r in procs if procs is not None else plat.processes(details=False):
        name = (r.get('name') or '').lower()
        exe = r.get('exe') or ''
        if name in WIN_PROCESSES and exe and any(plat.same_or_inside(exe, d) for d in dirs):
            out.append(r['pid'])
    return sorted(out)


def parse_wsl_list(raw):
    """`wsl -l -v` (UTF-16 by default, UTF-8 under WSL_UTF8=1) as [{'name', 'state', 'version', 'default'}].
    The header is localised, so rows are read by position. [] for "no installed distributions"."""
    if isinstance(raw, bytes):
        raw = raw.decode('utf-16-le' if b'\x00' in raw[:200] else 'utf-8', 'replace')
    text = raw.replace('\ufeff', '').replace('\x00', '').replace('\r', '')
    rows = []
    for line in [ln for ln in text.split('\n') if ln.strip()][1:]:
        default = line.lstrip().startswith('*')
        parts = line.replace('*', ' ', 1).split() if default else line.split()
        if len(parts) != 3 or not parts[2].isdigit():
            continue
        rows.append({'name': parts[0], 'state': parts[1], 'version': int(parts[2]), 'default': default})
    return rows


def wsl_distros():
    """WSL distributions and their state, or None when wsl.exe is missing."""
    if not plat.which('wsl'):
        return None
    _, out, _ = plat.run_raw(['wsl', '-l', '-v'], timeout=30, env=dict(os.environ, WSL_UTF8='1'))
    return parse_wsl_list(out)


def _hung_state_windows():
    """The Mac's three facts. The log lines it looks for have not been seen in a Windows log yet, so a match
    is hung_suspected, and 'hung' stays False until LIVE_ON_WINDOWS['revive']."""
    pids = win_docker_pids()
    tail = _log_tail()
    states = [m.group(1) for line in tail for m in [re.search(r'backend state changed to (\w+)', line)] if m]
    enospc = any('no space left on device' in line for line in tail[-100:])
    last_state = states[-1] if states else None
    suspected = bool(pids) and last_state == 'stopping' and enospc
    return {
        'pids': pids,
        'last_state': last_state,
        'disk_full_in_log': enospc,
        'log_found': bool(tail),
        'wsl': [d for d in wsl_distros() or [] if d['name'] in WSL_DISTROS],
        'hung_suspected': suspected,
        'hung': suspected and LIVE_ON_WINDOWS['revive'],
        'verified_on_windows': LIVE_ON_WINDOWS['revive'],
    }


def start_detached(exe):
    subprocess.Popen([exe], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     creationflags=0x00000008 | 0x00000200, close_fds=True)  # detached, its own group


def _restart_hung_windows(wait, grace, first_live_run):
    """End Docker Desktop's own processes (taskkill /F /T), stop only its WSL distros (wsl --terminate;
    never --shutdown, which stops every distro), start Docker Desktop again and wait for `docker info`.
    Off until it has run live once: see LIVE_ON_WINDOWS."""
    if not (LIVE_ON_WINDOWS['revive'] or first_live_run):
        return {'ok': False, 'report_only': True,
                'error': 'on Windows reclaim only reports a hung Docker until this step has run live once '
                         '(DESIGN.md, "Windows: first live runs"); quit and start Docker Desktop yourself',
                'state': hung_state()}
    state = hung_state()
    if daemon_up():
        return {'ok': True, 'note': 'Docker is already up; nothing restarted'}
    if not state['hung_suspected']:
        return {'ok': False, 'error': 'Docker is down but not in the hung after-full-disk state; start Docker '
                                      'Desktop yourself', 'state': state}
    time.sleep(grace)  # a real hang is still a hang a few seconds later; a Quit in progress is not
    again = hung_state()
    if daemon_up() or not again['hung_suspected'] or set(again['pids']) != set(state['pids']):
        return {'ok': False, 'error': 'Docker changed state while checking; nothing was killed', 'state': again}
    killed = []
    for pid in state['pids']:
        rc, _, err = run(['taskkill', '/F', '/T', '/PID', str(pid)])
        killed.append({'pid': pid, 'ok': rc == 0, 'err': err.strip()})
    stopped = [d['name'] for d in state.get('wsl', []) if d['state'].lower() == 'running']
    for name in stopped:
        run(['wsl', '--terminate', name], timeout=60)
    time.sleep(3)
    exe = desktop_exe()
    if not exe:
        return {'ok': False, 'killed': killed, 'error': 'Docker Desktop.exe was not found to start it again'}
    try:
        start_detached(exe)
    except OSError as exc:
        return {'ok': False, 'killed': killed, 'error': f'could not start Docker Desktop: {exc}'}
    deadline = time.time() + wait
    while time.time() < deadline:
        if daemon_up():
            return {'ok': True, 'killed': killed, 'wsl_terminated': stopped,
                    'up_after_s': int(wait - (deadline - time.time()))}
        time.sleep(3)
    return {'ok': False, 'killed': killed, 'error': f'Docker did not come up within {wait}s'}


# ---------- containers, images, build cache ----------

def _finished_age_days(cid):
    rc, out, _ = run(docker('inspect', '-f', '{{.State.FinishedAt}}|{{.Created}}', cid), timeout=30)
    if rc != 0:
        return None
    try:
        finished, created = out.strip().split('|')
    except ValueError:  # not the two stamps asked for
        return None
    stamp = finished if not finished.startswith('0001') else created
    stamp = re.sub(r'\.\d+', '', stamp).replace('Z', '+00:00')
    try:
        t = datetime.fromisoformat(stamp)
    except ValueError:
        return None
    return (datetime.now(timezone.utc) - t).total_seconds() / 86400


def containers():
    rc, out, _ = run(docker('ps', '-a', '--format', '{{json .}}'), timeout=60)
    if rc != 0:
        return []
    rows = []
    for line in out.splitlines():
        try:
            c = json.loads(line)
        except ValueError:  # a warning line among the rows
            continue
        if not isinstance(c, dict) or not all(k in c for k in ('Names', 'Image', 'State', 'Status', 'ID')):
            continue
        rows.append({'name': c['Names'], 'image': c['Image'], 'state': c['State'],
                     'status': c['Status'], 'id': c['ID']})
    return rows


def stale_containers(days, keep):
    """Containers not running for `days`, or stuck restarting, minus the keep-list (glob patterns)."""
    out = []
    for c in containers():
        if any(fnmatch.fnmatch(c['name'], k) for k in keep):
            continue
        if c['state'] not in ('exited', 'dead', 'created', 'restarting'):
            continue  # running and paused containers are in use
        if c['state'] == 'restarting':
            c['why'] = 'restarting in a loop'
            out.append(c)
            continue
        age = _finished_age_days(c['id'])
        if age is not None and age >= days:
            c['why'] = f'stopped {int(age)} days'
            out.append(c)
    return out


def system_df():
    rc, out, _ = run(docker('system', 'df', '--format', '{{json .}}'), timeout=60)
    rows = []
    for line in out.splitlines() if rc == 0 else []:
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows


def status(days, keep):
    if not cli():
        return {'installed': False, 'up': False, 'platform': sys.platform,
                'note': 'Docker is not installed (no `docker` command): the Docker part is skipped'}
    up = daemon_up()
    result = {'installed': True, 'up': up, 'platform': sys.platform}
    if not up:
        result['down'] = hung_state()
        return result
    result['df'] = system_df()
    result['stale'] = stale_containers(days, keep)
    return result


def restart_hung(wait=180, grace=5, first_live_run=False):
    if plat.WINDOWS:
        return _restart_hung_windows(wait, grace, first_live_run)
    state = hung_state()
    if daemon_up():
        return {'ok': True, 'note': 'Docker is already up; nothing restarted'}
    if not state['hung']:
        return {'ok': False, 'error': 'Docker is down but not in the hung after-full-disk state; restart it from the menu bar', 'state': state}
    time.sleep(grace)  # a real hang is still a hang a few seconds later; a Quit in progress is not
    again = hung_state()
    if daemon_up() or not again['hung'] or set(again['pids']) != set(state['pids']):
        return {'ok': False, 'error': 'Docker changed state while checking; nothing was killed', 'state': again}
    killed = []
    for pid in state['pids']:
        rc, _, err = run(['kill', '-9', str(pid)])
        killed.append({'pid': pid, 'ok': rc == 0, 'err': err.strip()})
    time.sleep(3)
    run(['open', '-a', 'Docker'])
    deadline = time.time() + wait
    while time.time() < deadline:
        if daemon_up():
            return {'ok': True, 'killed': killed, 'up_after_s': int(wait - (deadline - time.time()))}
        time.sleep(3)
    return {'ok': False, 'killed': killed, 'error': f'Docker did not come up within {wait}s'}


def _reclaimed(text):
    m = re.findall(r'(?:Total reclaimed space|Total):\s*([\d.]+\s*[kMGT]?B)', text)
    return m[-1] if m else '0B'


def prune_images(days):
    rc, out, err = run(docker('image', 'prune', '-a', '-f', '--filter', f'until={int(days * 24)}h'),
                       timeout=1800)
    return {'ok': rc == 0, 'reclaimed': _reclaimed(out), 'err': err.strip()}


def prune(days):
    rc, out, err = run(docker('builder', 'prune', '-a', '-f', '--filter', f'until={int(days * 24)}h'),
                       timeout=1800)
    return {
        'images': prune_images(days),
        'build_cache': {'ok': rc == 0, 'reclaimed': _reclaimed(out), 'err': err.strip()},
    }


def remove_containers(names, days, keep, prune_after=False):
    """Remove named containers, only those still stale now; volumes stay.

    Plain `docker rm` for stopped ones, so a container that was started again since the check is
    refused by Docker instead of killed; `-f` only for one stuck restarting. Images are pruned
    afterwards only when the caller says the user approved that (prune_after).
    """
    stale = {c['name']: c for c in stale_containers(days, keep)}
    results = []
    for name in names:
        if name not in stale:
            results.append({'name': name, 'result': 'skipped', 'why': 'not stale now (running, kept, or too new)'})
            continue
        cmd = docker('rm', *(['-f'] if stale[name]['state'] == 'restarting' else []), name)
        rc, _, err = run(cmd, timeout=120)  # never -v: volumes hold data
        results.append({'name': name, 'result': 'removed' if rc == 0 else 'failed', 'why': err.strip()})
    removed = any(r['result'] == 'removed' for r in results)
    images = prune_images(days) if prune_after and removed else None
    return {'results': results, 'images': images}
