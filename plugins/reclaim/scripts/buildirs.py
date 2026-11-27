"""Build folders inside worktrees that are kept but idle: node_modules, target, .venv, build, dist, ...

A worktree the scan keeps (an open PR, commits on no remote, ...) can still hold gigabytes that a rebuild
makes again. These are offered, per tree, only when:

- the tree is idle: nothing committed or checked out for N days, no uncommitted file edited since then;
- it is not kept because something uses it: no process in it, not this session's folder, no paused session;
- it is not a main checkout, unless buildirs_in_main is true;
- the folder is a build folder by name (BUILD_NAMES plus build_dir_names), not a link or junction, holds no
  other checkout, and git agrees it is disposable: `git ls-files` lists nothing in it and `git check-ignore`
  says it is ignored.

Everything is checked again right before the delete, which goes through the shared delete routine.
"""
import json
import os

import plat
import worktrees
from common import git, home, now, write_atomic

BUILD_NAMES = ('node_modules', 'target', '.venv', 'build', 'dist', '.gradle', 'Intermediate', 'Binaries',
               'DerivedDataCache')
SCAN_FILE = 'last-buildirs.json'
MAX_DEPTH = 4
# Keep reasons that mean the tree is in use or was worked on recently: its build folders are left alone.
NOT_IDLE = ('in use', 'this session runs here', 'a parked session', 'could not list running processes',
            'could not check which processes', 'edited since the cutoff', 'newer than the cutoff')


def _idle(row, in_main):
    if 'old' not in row or not row['old'] or row.get('recent_edit'):
        return False
    if row.get('main') and not in_main:
        return False
    return not any(r.startswith(x) for r in row.get('reasons', []) for x in NOT_IDLE)


def candidates(tree, names):
    """Build folders by name inside tree, up to MAX_DEPTH levels, never inside another checkout or a link."""
    found = []
    base = plat.depth(plat.strip_sep(tree))
    for root, dirs, _ in plat.walk(tree):
        keep = []
        for d in dirs:
            full = os.path.join(root, d)
            if d == '.git' or os.path.exists(os.path.join(full, '.git')):
                continue  # git's own folder, or another checkout
            if d in names:
                found.append(full)
            elif plat.depth(root) - base < MAX_DEPTH and d not in worktrees.BUILD_DIRS:
                keep.append(d)
        dirs[:] = keep
    return found


def why_not(tree, full, cwds):
    """None when full may be deleted now, else the reason it may not."""
    rel = plat.rel(full, tree)
    if not os.path.isdir(full):
        return 'gone'
    if plat.is_link_or_junction(full):
        return 'a link or junction: deleting it frees nothing'
    rc, out, _ = git(tree, 'ls-files', '-z', '--', rel)
    if rc != 0 or out.strip('\0'):
        return 'git tracks files in it'
    rc, _, _ = git(tree, 'check-ignore', '-q', '--', rel + '/')
    if rc != 0:
        return 'git does not ignore it'
    if worktrees._repos_inside(full, depth=3):
        return 'holds another checkout'
    names = worktrees.in_use(full, cwds)
    if names is None:
        return 'could not check whether a process uses it'
    if names:
        return 'in use by ' + ', '.join(names[:3])
    return None


def _trees(cfg, days):
    """The idle kept trees from the last worktree scan (and, with buildirs_in_main, every main checkout)."""
    f = home() / worktrees.SCAN_FILE
    if not f.exists():
        return None, 'no worktree scan yet: run scan first'
    last = json.loads(f.read_text())
    if now() - last['at'] > worktrees.SCAN_MAX_AGE:
        return None, 'the last worktree scan is over an hour old: run scan again'
    in_main = cfg.get('buildirs_in_main', False)
    rows = [r for r in last['rows'] if r.get('verdict') == 'keep' and _idle(r, in_main)]
    if in_main:
        seen = {os.path.realpath(r['path']) for r in last['rows']}
        cwds, parked = worktrees.process_cwds(), worktrees.parked_folders()
        for repo in last.get('repos', []):
            if os.path.realpath(repo) in seen or not os.path.isdir(repo):
                continue
            row = worktrees.inspect(plat.native(repo), True, last['cutoff'], cwds, parked, with_prs=False,
                                    current=os.path.realpath(os.getcwd()))
            if _idle(row, True):
                rows.append(row)
    return rows, None


def scan(cfg, days):
    trees, err = _trees(cfg, days)
    if err:
        return {'error': err}
    names = set(BUILD_NAMES) | set(cfg.get('build_dir_names') or [])
    cwds = worktrees.process_cwds()
    out = []
    for row in trees:
        tree = row['path']
        for full in candidates(tree, names):
            why = why_not(tree, full, cwds)
            if why is None:
                out.append({'tree': tree, 'folder': plat.rel(full, tree), 'path': full,
                            'size': plat.dir_size(full), 'tree_kept_because': row.get('reasons', [])[:3]})
    result = {'at': now(), 'folders': out}
    write_atomic(home() / SCAN_FILE, json.dumps(result, indent=2))
    return result


def remove(cfg, paths):
    f = home() / SCAN_FILE
    if not f.exists():
        return {'error': 'no build-folder scan yet: run buildirs scan first'}
    last = json.loads(f.read_text())
    if now() - last['at'] > worktrees.SCAN_MAX_AGE:
        return {'error': 'the last build-folder scan is over an hour old: run it again'}
    by_path = {os.path.realpath(r['path']): r for r in last['folders']}
    wt = json.loads((home() / worktrees.SCAN_FILE).read_text()) if (home() / worktrees.SCAN_FILE).exists() else {}
    cutoff = wt.get('cutoff', now() - cfg.get('days', 3) * 86400)
    cwds, parked = worktrees.process_cwds(), worktrees.parked_folders()
    results = []
    for given in paths:
        path = os.path.realpath(given)
        row = by_path.get(path)
        if not row:
            results.append({'path': given, 'result': 'skipped', 'why': 'the last build-folder scan did not offer it'})
            continue
        tree = row['tree']
        again = worktrees.inspect(tree, False, cutoff, cwds, parked, with_prs=False,
                                  current=os.path.realpath(os.getcwd()))
        if not _idle(dict(again, main=False), True):
            results.append({'path': row['path'], 'result': 'skipped', 'why': 'the tree is no longer idle: '
                            + '; '.join(r for r in again.get('reasons', []) if any(r.startswith(x) for x in NOT_IDLE))})
            continue
        why = why_not(tree, row['path'], cwds)
        if why:
            results.append({'path': row['path'], 'result': 'skipped', 'why': why})
            continue
        held = plat.held_files(row['path'])
        if held is None or held['count']:
            results.append({'path': row['path'], 'result': 'skipped',
                            'why': 'could not check for open files' if held is None else
                            'locked by ' + (', '.join(held['by'][:3]) or 'another program')})
            continue
        size = plat.dir_size(row['path'])
        done = plat.delete_tree(row['path'])
        if done['ok']:
            results.append({'path': row['path'], 'result': 'removed', 'freed': size})
        else:
            results.append({'path': row['path'], 'result': 'partly', 'left': done['left'], 'why': done['error']})
    return {'results': results}
