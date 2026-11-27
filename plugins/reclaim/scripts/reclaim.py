"""reclaim CLI. Prints JSON. Read-only unless the subcommand name says it removes something.

  df                                  free space on /
  scan [--days N] [--no-merged]       worktrees with a verdict each (writes last-scan.json)
  remove PATH...                      remove worktrees the last scan approved (re-checks each)
  backup PATH                         back up one worktree's uncommitted work
  docker status [--days N]            up? hung? reclaimable space, stale containers
  docker restart-hung                 kill a Docker Desktop hung after a full disk, relaunch it
  docker prune [--days N]             unused images + build cache older than N days
  docker rm NAME...                   remove stale containers (never volumes), then their images
  docker disk                         Docker's disk image on the host: its size against what Docker holds
  docker compact [--release] [--shutdown-wsl] [--dry-run]
                                      Windows: shrink Docker's VHDX (Docker quit; one UAC prompt)
  config show | set KEY VALUE | detect | detect-roots | preview
"""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import backup as backup_mod  # noqa: E402
import docker  # noqa: E402
import plat  # noqa: E402
import vdisk  # noqa: E402
import worktrees  # noqa: E402
from common import VALIDATORS, emit, free_bytes, gb, git, load_config, save_config  # noqa: E402


def detect_repos(limit=300):
    """Main checkouts of the git repos your recent Claude sessions ran in, with worktree counts."""
    projects = Path.home() / '.claude' / 'projects'
    files = sorted(projects.glob('*/*.jsonl'), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]
    cwds = set()
    for f in files:
        with open(f, encoding='utf-8', errors='replace') as fh:
            for _, line in zip(range(40), fh):
                if '"cwd"' in line:
                    try:
                        cwd = json.loads(line).get('cwd')
                    except ValueError:
                        continue
                    if cwd:
                        cwds.add(cwd)
                        break
    repos = {}
    for cwd in cwds:
        if not os.path.isdir(cwd):
            continue
        rc, common_dir, _ = git(cwd, 'rev-parse', '--path-format=absolute', '--git-common-dir')
        if rc != 0:
            continue
        common_dir = common_dir.strip().rstrip('/')
        rc, bare, _ = git(cwd, 'rev-parse', '--is-bare-repository')
        # A bare repo's git dir is the repo itself; otherwise the main checkout is the git dir's parent.
        main = common_dir if (rc == 0 and bare.strip() == 'true') or not common_dir.endswith('/.git') \
            else os.path.dirname(common_dir)
        main = plat.native(main)  # git prints C:/x on Windows
        if main not in repos:
            repos[main] = len(worktrees.list_worktrees(main))
    return [{'repo': r, 'worktrees': n} for r, n in sorted(repos.items(), key=lambda x: -x[1])]


def detect_roots(repos):
    """Folders that hold the detected repos, most repos first: the candidates for 'scan whole folders'."""
    counts = {}
    for r in repos:
        parent = os.path.dirname(plat.strip_sep(r['repo']))
        counts[parent] = counts.get(parent, 0) + 1
    return [{'root': p, 'repos': n} for p, n in sorted(counts.items(), key=lambda x: (-x[1], x[0]))]


def resolve_repos(repos, roots):
    """Configured repos plus the repos found under the root folders, each once: (paths, warnings)."""
    found, warns = worktrees.find_repos(roots) if roots else ([], [])
    out, seen = [], set()
    for r in list(repos) + found:
        r = os.path.expanduser(r)
        try:
            st = os.stat(r)
            key = (st.st_dev, st.st_ino)
        except OSError:
            key = r  # a configured repo that is missing stays listed so the scan can say so
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out, warns


def system_root():
    """'/' on macOS and Linux, as before; on Windows the drive that holds the home folder."""
    if not plat.WINDOWS:
        return '/'
    return os.path.splitdrive(str(Path.home()))[0] + os.sep


def main(argv=None):
    ap = argparse.ArgumentParser(prog='reclaim')
    sub = ap.add_subparsers(dest='cmd', required=True)
    sub.add_parser('df')
    s = sub.add_parser('scan')
    s.add_argument('--days', type=float)
    s.add_argument('--no-merged', action='store_true')
    s.add_argument('--repo', action='append')
    r = sub.add_parser('remove')
    r.add_argument('paths', nargs='+')
    b = sub.add_parser('backup')
    b.add_argument('path')
    d = sub.add_parser('docker')
    d.add_argument('action', choices=['status', 'restart-hung', 'prune', 'rm', 'disk', 'compact'])
    d.add_argument('names', nargs='*')
    d.add_argument('--days', type=float)
    d.add_argument('--first-live-run', action='store_true',
                   help='Windows: run a step that has not run live on Windows yet, once, with its owner watching')
    d.add_argument('--release', action='store_true',
                   help="compact: stop Docker's own WSL distro first (wsl --terminate), after the user said yes")
    d.add_argument('--shutdown-wsl', action='store_true',
                   help='compact: run wsl --shutdown (stops every distro) if the disk is still held, after a yes')
    d.add_argument('--dry-run', action='store_true', help='compact: check everything, change nothing')
    d.add_argument('--prune-images', action='store_true',
                   help='with rm: also prune old unused images afterwards (only after the user approved it)')
    c = sub.add_parser('config')
    c.add_argument('action', choices=['show', 'set', 'detect', 'detect-roots', 'preview'])
    c.add_argument('key', nargs='?')
    c.add_argument('value', nargs='?')
    a = ap.parse_args(argv)
    cfg = load_config()
    given = getattr(a, 'days', None)
    days = cfg['days'] if given is None else given  # --days 0 is a real value

    if a.cmd == 'df':
        emit({'free_gb': gb(free_bytes(system_root()))})
    elif a.cmd == 'scan':
        repos, warns = resolve_repos(a.repo or cfg['repos'], [] if a.repo else cfg['roots'])
        if not repos:
            emit({'error': 'no repos configured: run /reclaim:init', 'warnings': warns})
            return 2
        emit(worktrees.scan(repos, days, merged=not a.no_merged, warnings=warns))
    elif a.cmd == 'remove':
        emit(worktrees.remove(a.paths, cfg['backup_dir'], backup_mod.backup))
    elif a.cmd == 'backup':
        emit(backup_mod.backup(a.path, cfg['backup_dir']))
    elif a.cmd == 'docker':
        keep = cfg['keep_containers']
        if a.action == 'status':
            emit(docker.status(days, keep))
        elif a.action == 'restart-hung':
            emit(docker.restart_hung(first_live_run=a.first_live_run))
        elif a.action == 'prune':
            emit(docker.prune(days))
        elif a.action == 'disk':
            emit(vdisk.report())
        elif a.action == 'compact':
            emit(vdisk.compact(first_live_run=a.first_live_run, release=a.release, shutdown_wsl=a.shutdown_wsl,
                               dry_run=a.dry_run))
        elif a.action == 'rm':
            if not a.names:
                emit({'error': 'name the containers to remove'})
                return 2
            emit(docker.remove_containers(a.names, days, keep, prune_after=a.prune_images))
    elif a.cmd == 'config':
        if a.action == 'show':
            emit(cfg)
        elif a.action == 'detect':
            emit(detect_repos())
        elif a.action == 'detect-roots':
            emit(detect_roots(detect_repos()))
        elif a.action == 'preview':
            repos, warns = resolve_repos(cfg['repos'], cfg['roots'])
            emit({'repos': repos, 'warnings': warns})
        elif a.action == 'set':
            if a.key not in VALIDATORS:
                emit({'error': f'unknown key {a.key}'})
                return 2
            if a.value is None:
                emit({'error': f'give a value for {a.key}'})
                return 2
            try:
                value = json.loads(a.value) if a.key != 'backup_dir' else a.value
            except ValueError:
                emit({'error': f'{a.key} needs a JSON value (for example 3, true, or ["a","b"]), got: {a.value}'})
                return 2
            if not VALIDATORS[a.key](value):
                emit({'error': f'{a.value} is not a valid value for {a.key}'})
                return 2
            cfg[a.key] = value
            save_config(cfg)
            emit(load_config())
    return 0


if __name__ == '__main__':
    sys.exit(main())
