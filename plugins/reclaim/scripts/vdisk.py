"""Docker's disk image on the host: how big it is, and (Windows) shrinking it.

macOS: Docker.raw is a sparse file on APFS. Its real size follows the data inside it, so there is nothing to
compact: reclaim reports its real and apparent size and how much a prune would free.

Windows (WSL 2 backend): Docker keeps its data in a VHDX (docker_data.vhdx; ext4.vhdx in older versions)
that grows and never shrinks by itself. A prune frees space inside it, not on the drive. `compact` shrinks
the file: Docker Desktop quit, its WSL distros stopped, the file checked as released (no process has it
open), then Optimize-VHD (Hyper-V tools) or `diskpart compact vdisk`, in one elevated PowerShell (one UAC
prompt). It writes its result to a file that reclaim reads back. Off until it has run live once on a
Windows PC: docker.LIVE_ON_WINDOWS['compact'].

WSL's sparse mode (`wsl --manage <distro> --set-sparse true`) is left out: it targets a distro's own disk,
not Docker's data disk, and has not been tried on one.
"""
import base64
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

import docker
import plat
from common import run

HERE = Path(__file__).resolve().parent
UNITS = {'B': 1, 'KB': 1e3, 'MB': 1e6, 'GB': 1e9, 'TB': 1e12}


def to_bytes(text):
    """'1.5GB' or '12.3kB (40%)' as bytes; 0 when it can't be read."""
    m = re.match(r'\s*([\d.]+)\s*([kKMGT]?B)', text or '')
    if not m:
        return 0
    try:
        return int(float(m.group(1)) * UNITS[m.group(2).upper()])
    except (ValueError, KeyError):
        return 0


def _json(path):
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def disk_paths():
    """[(path, kind)] for Docker's disk images that exist on this machine."""
    found = []
    if plat.WINDOWS:
        local = Path(os.environ.get('LOCALAPPDATA') or '.') / 'Docker' / 'wsl'
        roaming = Path(os.environ.get('APPDATA') or '.') / 'Docker'
        custom = []
        for f in ('settings-store.json', 'settings.json'):
            d = _json(roaming / f).get('CustomWslDistroDir')
            if isinstance(d, str) and d:
                custom.append(Path(d))
        for base in custom + [local]:
            for rel, kind in (('disk/docker_data.vhdx', 'data'), ('docker_data.vhdx', 'data'),
                              ('data/ext4.vhdx', 'data'), ('main/ext4.vhdx', 'distro')):
                p = base / rel
                if p.is_file() and str(p) not in [f for f, _ in found]:
                    found.append((str(p), kind))
        return found
    group = Path.home() / 'Library' / 'Group Containers' / 'group.com.docker'
    dirs = []
    for f in ('settings-store.json', 'settings.json'):
        data = _json(group / f)
        for key in ('DataFolder', 'dataFolder'):
            if isinstance(data.get(key), str):
                dirs.append(Path(data[key]))
    dirs.append(Path.home() / 'Library' / 'Containers' / 'com.docker.docker' / 'Data' / 'vms' / '0' / 'data')
    for d in dirs:
        p = d / 'Docker.raw'
        if p.is_file() and str(p) not in [f for f, _ in found]:
            found.append((str(p), 'data'))
    return found


def report():
    """Each disk image's size against what Docker says it holds, and whether a compact could run now."""
    disks = []
    for path, kind in disk_paths():
        try:
            size = os.stat(path).st_size
        except OSError:
            continue
        disks.append({'path': path, 'kind': kind, 'size': size, 'on_disk': plat.allocated_bytes(path)})
    out = {'platform': 'windows' if plat.WINDOWS else sys.platform, 'disks': disks}
    if docker.cli() and docker.daemon_up():
        df = docker.system_df()
        out['inside'] = {'used': sum(to_bytes(r.get('Size')) for r in df),
                         'reclaimable_by_prune': sum(to_bytes(r.get('Reclaimable')) for r in df)}
    data = [d for d in disks if d['kind'] == 'data']
    if plat.WINDOWS:
        out['compact'] = {'verified_on_windows': docker.LIVE_ON_WINDOWS['compact'],
                          'tool': 'Optimize-VHD' if hyperv_tools() else 'diskpart'}
        if data and out.get('inside'):
            out['compact']['about_free'] = max(0, (data[0]['on_disk'] or data[0]['size']) - out['inside']['used'])
    else:
        out['compact'] = {'needed': False,
                          'why': 'Docker.raw is sparse: its real size shrinks with the data, after a prune'}
    return out


def hyperv_tools():
    if not plat.WINDOWS:
        return False
    rc, out, _ = run([powershell_exe(), '-NoProfile', '-NonInteractive', '-Command',
                      "if (Get-Command Optimize-VHD -ErrorAction SilentlyContinue) { 'yes' } else { 'no' }"],
                     timeout=60)
    return rc == 0 and out.strip() == 'yes'


def blockers(procs=None):
    """Why a compact can't run now: Docker running or starting, a build or any docker command running."""
    procs = plat.processes(details=True) if procs is None else procs
    why = []
    if docker.win_docker_pids(procs):
        why.append('Docker Desktop is running or starting: quit it first (its menu: Quit Docker Desktop)')
    cli = plat.running(['docker', 'docker-compose', 'docker-buildx'], procs)
    if cli:
        why.append('a docker command is running (a build?): pids ' + ', '.join(str(p) for p, _ in cli[:5]))
    return why


def powershell_exe():
    return os.path.join(os.environ.get('SystemRoot') or r'C:\Windows', 'System32', 'WindowsPowerShell', 'v1.0',
                        'powershell.exe')


def ps_quote(s):
    return "'" + str(s).replace("'", "''") + "'"


def elevated_script(vhdx, result_file):
    """The PowerShell that starts compact.ps1 elevated (the one UAC prompt) and waits for it."""
    args = ' '.join(['-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
                     '-File', f'"{HERE / "compact.ps1"}"', '-Vhdx', f'"{vhdx}"', '-ResultFile', f'"{result_file}"'])
    return (f"$ErrorActionPreference = 'Stop'\n"
            f"try {{ $p = Start-Process -FilePath {ps_quote(powershell_exe())} -ArgumentList {ps_quote(args)} "
            f"-Verb RunAs -Wait -PassThru -WindowStyle Hidden }}\n"
            f"catch {{ Write-Output ('UAC: ' + $_.Exception.Message); exit 1223 }}\n"
            f"exit $p.ExitCode\n")


def elevate(script, timeout=3600):
    enc = base64.b64encode(script.encode('utf-16-le')).decode('ascii')
    return run([powershell_exe(), '-NoProfile', '-NonInteractive', '-EncodedCommand', enc], timeout=timeout)


def compact(first_live_run=False, release=False, shutdown_wsl=False, dry_run=False):
    """Shrink Docker's VHDX on Windows. Every precondition is checked first; any one that fails stops it."""
    if not plat.WINDOWS:
        return {'ok': False, 'error': 'nothing to compact here: Docker.raw on macOS is sparse and shrinks by itself'}
    if not (docker.LIVE_ON_WINDOWS['compact'] or first_live_run):
        return {'ok': False, 'report_only': True,
                'error': 'on Windows reclaim only reports the disk size until the compact has run live once '
                         '(DESIGN.md, "Windows: first live runs")', 'disk': report()}
    data = [p for p, kind in disk_paths() if kind == 'data']
    if not data:
        return {'ok': False, 'error': "Docker's data disk (docker_data.vhdx or ext4.vhdx) was not found"}
    vhdx = data[0]
    why = blockers()
    if why:
        return {'ok': False, 'error': 'not now', 'why': why}
    distros = docker.wsl_distros() or []
    mine = [d['name'] for d in distros if d['name'] in docker.WSL_DISTROS and d['state'].lower() == 'running']
    others = [d['name'] for d in distros if d['name'] not in docker.WSL_DISTROS and d['state'].lower() == 'running']
    if mine:
        if not release:
            return {'ok': False, 'needs': 'release', 'running': mine,
                    'error': "Docker's WSL distro is still running: ask, then run again with --release "
                             '(wsl --terminate, which stops only that distro)'}
        if not dry_run:
            for name in mine:
                run(['wsl', '--terminate', name], timeout=60)
    held = plat.exclusive_open_error(vhdx)
    if held and not dry_run:
        if not shutdown_wsl:
            return {'ok': False, 'needs': 'shutdown', 'other_running': others,
                    'error': 'the disk is still held by the WSL virtual machine: ask, naming the other running '
                             'distros, then run again with --shutdown-wsl (wsl --shutdown stops every distro)'}
        run(['wsl', '--shutdown'], timeout=120)
        if plat.exclusive_open_error(vhdx):
            return {'ok': False, 'error': 'the disk is still in use after wsl --shutdown; nothing was changed'}
    tmp = Path(tempfile.mkdtemp(prefix='reclaim-compact-'))
    result_file = tmp / 'result.json'
    script = elevated_script(vhdx, result_file)
    if dry_run:
        shutil.rmtree(tmp, ignore_errors=True)
        return {'dry_run': True, 'disk': vhdx, 'held_now': bool(held), 'would_release': mine,
                'would_run': script}
    before = plat.allocated_bytes(vhdx)
    try:
        code, out, err = elevate(script)
        try:
            result = json.loads(result_file.read_text(encoding='utf-8-sig'))
        except (OSError, ValueError):
            result = None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if code == 1223 or 'UAC' in out:
        return {'ok': False, 'error': 'the UAC prompt was declined or failed: nothing changed', 'detail': out.strip()}
    if result is None:
        return {'ok': False, 'error': f'the compact did not report back (exit {code})', 'detail': (out + err)[-2000:]}
    after = plat.allocated_bytes(vhdx)
    return {'ok': bool(result.get('ok')), 'disk': vhdx, 'before': before, 'after': after,
            'freed': (before - after) if before is not None and after is not None else None, 'result': result}
