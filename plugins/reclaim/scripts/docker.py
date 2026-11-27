"""Docker Desktop on macOS: is it up, is it hung after a full disk, and what can be pruned.

Volumes are never touched: no `-v`, no `volume prune`, no `system prune --volumes`.
"""
import fnmatch
import json
import os
import re
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from common import run

BACKEND_LOG = Path.home() / 'Library/Containers/com.docker.docker/Data/log/host/com.docker.backend.log'
# The processes that hold a hung Docker Desktop. vmnetd runs as root and is left alone.
HUNG_PATTERN = r'Docker\.app/Contents/(MacOS/com\.docker\.backend|Resources/cli-plugins/docker-agent)'


def daemon_up():
    rc, _, _ = run(['docker', 'info', '--format', '{{.ServerVersion}}'], timeout=20)
    return rc == 0


def _log_tail(lines=600):
    log = Path(os.environ.get('RECLAIM_DOCKER_LOG') or BACKEND_LOG)
    if not log.exists():
        return []
    with open(log, 'rb') as f:
        f.seek(0, 2)
        f.seek(max(0, f.tell() - 400_000))
        return f.read().decode(errors='replace').splitlines()[-lines:]


def hung_state():
    """Why Docker is down, from its own processes and log. 'hung' needs all three facts."""
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


def _finished_age_days(cid):
    rc, out, _ = run(['docker', 'inspect', '-f', '{{.State.FinishedAt}}|{{.Created}}', cid], timeout=30)
    if rc != 0:
        return None
    finished, created = out.strip().split('|')
    stamp = finished if not finished.startswith('0001') else created
    stamp = re.sub(r'\.\d+', '', stamp).replace('Z', '+00:00')
    try:
        t = datetime.fromisoformat(stamp)
    except ValueError:
        return None
    return (datetime.now(timezone.utc) - t).total_seconds() / 86400


def containers():
    rc, out, _ = run(['docker', 'ps', '-a', '--format', '{{json .}}'], timeout=60)
    if rc != 0:
        return []
    rows = []
    for line in out.splitlines():
        c = json.loads(line)
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
    rc, out, _ = run(['docker', 'system', 'df', '--format', '{{json .}}'], timeout=60)
    return [json.loads(line) for line in out.splitlines()] if rc == 0 else []


def status(days, keep):
    if not shutil.which('docker'):
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


def restart_hung(wait=180, grace=5):
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
    rc, out, err = run(['docker', 'image', 'prune', '-a', '-f', '--filter', f'until={int(days * 24)}h'],
                       timeout=1800)
    return {'ok': rc == 0, 'reclaimed': _reclaimed(out), 'err': err.strip()}


def prune(days):
    rc, out, err = run(['docker', 'builder', 'prune', '-a', '-f', '--filter', f'until={int(days * 24)}h'],
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
        cmd = ['docker', 'rm'] + (['-f'] if stale[name]['state'] == 'restarting' else []) + [name]
        rc, _, err = run(cmd, timeout=120)  # never -v: volumes hold data
        results.append({'name': name, 'result': 'removed' if rc == 0 else 'failed', 'why': err.strip()})
    removed = any(r['result'] == 'removed' for r in results)
    images = prune_images(days) if prune_after and removed else None
    return {'results': results, 'images': images}
