"""Find git worktrees, decide which are safe to remove, and remove them.

A worktree is never removed on a guess. Every keep reason below is checked at scan time and again
right before removal, and a tree that changed in between is skipped.
"""
import hashlib
import json
import os
import re
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import plat
from common import BUILD_DIRS, du_bytes, git, home, now, run, write_atomic

SCAN_FILE = 'last-scan.json'
SCAN_MAX_AGE = 3600  # a scan older than this can't authorise a removal


# ---------- facts about one worktree ----------

def list_worktrees(repo):
    """[(path, is_main)] for a repo's checkout. The first entry git prints is the main checkout."""
    rc, out, _ = git(repo, 'worktree', 'list', '--porcelain')
    if rc != 0:
        return []
    paths = []
    for block in out.split('\n\n'):
        lines = block.strip().splitlines()
        if not lines or not lines[0].startswith('worktree ') or 'bare' in lines[1:]:
            continue  # a bare repo's own folder is not a checkout
        paths.append(plat.native(lines[0][9:]))  # git prints C:/x on Windows
    return [(p, i == 0) for i, p in enumerate(paths)]  # the first checkout is kept as "main"


def _is_bare_repo(d):
    return all(os.path.exists(os.path.join(d, n)) for n in ('HEAD', 'objects', 'refs'))


def find_repos(roots, depth=2, max_dirs=2000):
    """Git repos found by walking each root folder: ([repo paths], [warnings]).

    A repo is a folder holding a .git folder, or a bare repo. A .git FILE is a linked worktree: those are
    listed through their main repo, never as repos of their own. The walk never follows symlinks, never
    leaves the root's disk, skips dot folders and build folders, and stops after max_dirs folders per root.
    """
    found, seen, warnings = [], set(), []

    def add(d):
        try:
            st = os.stat(d)
        except OSError:
            return
        if (st.st_dev, st.st_ino) not in seen:  # symlinks and case-insensitive disks give the same folder twice
            seen.add((st.st_dev, st.st_ino))
            found.append(os.path.realpath(d))

    for root in roots:
        root = os.path.expanduser(root)
        if not os.path.isdir(root):
            warnings.append(f'folder {root} is missing (unplugged disk?): skipped')
            continue
        dev = os.stat(root).st_dev
        visited = 0
        stack = [(root, 0)]
        while stack:
            d, level = stack.pop()
            visited += 1
            if visited > max_dirs:
                warnings.append(f'folder {root} has more than {max_dirs} folders within {depth} levels: '
                                f'stopped early; list the repos directly or use a narrower folder')
                break
            if os.path.isdir(os.path.join(d, '.git')) or _is_bare_repo(d):
                add(d)
                continue  # never look inside a repo
            if level >= depth:
                continue
            try:
                entries = sorted(os.scandir(d), key=lambda e: e.name)
            except OSError:
                continue
            for e in entries:
                if e.name.startswith('.') or e.name in BUILD_DIRS:
                    continue
                try:
                    if e.is_dir(follow_symlinks=False) and not plat.is_link_or_junction(e.path) and (
                            os.stat(e.path).st_dev == dev):
                        stack.append((e.path, level + 1))
                except OSError:
                    continue
    return found, warnings


def status_entries(path):
    """[(xy, path)] for tracked changes and untracked files, or None when git fails.

    -z keeps paths raw: without it git C-quotes non-ASCII names ("\\303\\251") and ' -> ' is ambiguous.
    """
    rc, out, _ = git(path, 'status', '--porcelain', '-z', '--untracked-files=all')
    if rc != 0:
        return None
    tokens = out.split('\0')
    entries, i = [], 0
    while i < len(tokens):
        tok = tokens[i]
        i += 1
        if len(tok) < 4:
            continue
        xy, name = tok[:2], tok[3:]
        entries.append((xy, name))
        if 'R' in xy or 'C' in xy:
            i += 1  # the rename's original path follows; it no longer exists in the tree
    return entries


def ignored_entries(path):
    """Gitignored files and folders outside the build folders (.env.local and the like).

    None when git fails: the caller must keep the tree, not read failure as "nothing ignored".
    Folders holding another checkout are left out: they are never copied into a backup, and
    nested_checkouts() keeps the tree that holds them.
    """
    rc, out, _ = git(path, 'ls-files', '-z', '--others', '--ignored', '--exclude-standard', '--directory')
    if rc != 0:
        return None
    keep = []
    for entry in out.split('\0'):
        parts = [p for p in entry.rstrip('/').split('/') if p]
        if not parts or any(p in BUILD_DIRS for p in parts):
            continue
        full = os.path.join(path, entry)
        if os.path.isdir(full) and _repos_inside(full):
            continue
        keep.append(entry.rstrip('/'))
    return keep


def nested_checkouts(path):
    """Other repos or worktrees anywhere inside this tree. Removing the tree would delete them too
    (git removes ignored content without --force), whatever their own state."""
    found = []
    for root, dirs, files in plat.walk(path):
        if root != path and ('.git' in dirs or '.git' in files):
            found.append(plat.rel(root, path))
            dirs[:] = []
            continue
        for d in [d for d in dirs if d in BUILD_DIRS and d != '.git']:
            # Don't walk a build folder's bulk, but a checkout can sit just inside one (dist/proj).
            found.extend(plat.rel(r, path) for r in _repos_inside(os.path.join(root, d), depth=3))
        dirs[:] = [d for d in dirs if d not in BUILD_DIRS]
    return found


def _repos_inside(top, depth=6):
    """Roots of git checkouts (repos or worktrees) under top, not descending into them."""
    found, base = [], plat.depth(plat.strip_sep(top))
    for root, dirs, files in plat.walk(top):
        if '.git' in dirs or '.git' in files:
            found.append(root)
            dirs[:] = []
            continue
        if plat.depth(root) - base >= depth:
            dirs[:] = []
        else:
            dirs[:] = [d for d in dirs if d not in BUILD_DIRS]
    return found


def recent_edit(path, cutoff, entries):
    """First uncommitted or new file modified after cutoff, or None.

    Only work git doesn't hold counts. A tracked file that matches HEAD can carry a fresh mtime
    (checkouts and tools rewrite them) without anything to lose.
    """
    for entry in entries:
        top = os.path.join(path, entry)
        if os.path.isdir(top) and not plat.is_link_or_junction(top):
            for root, dirs, files in plat.walk(top):
                dirs[:] = [d for d in dirs if d not in BUILD_DIRS]
                for name in files:
                    f = os.path.join(root, name)
                    try:
                        if os.lstat(f).st_mtime > cutoff:
                            return f
                    except OSError:
                        continue
        else:
            try:
                if os.lstat(top).st_mtime > cutoff:
                    return top
            except OSError:
                continue
    return None


def last_checkout(path):
    """When this worktree's HEAD last moved (add, checkout, commit, reset), from its own reflog."""
    rc, out, _ = git(path, 'reflog', '-1', '--date=unix', '--format=%gd', 'HEAD')
    m = re.search(r'\{(\d+)\}', out) if rc == 0 else None
    return int(m.group(1)) if m else 0


def unreachable_detached(path):
    """True when HEAD is detached and no branch or tag holds it: removal would orphan commits."""
    rc, out, _ = git(path, 'for-each-ref', '--contains', 'HEAD', '--format=%(refname)',
                     'refs/heads', 'refs/remotes', 'refs/tags')
    return rc != 0 or not out.strip()  # a failed check counts as unreachable: keep


def commits_not_on_remote(path):
    """Commits HEAD has that no remote branch has, or None when git fails."""
    rc, out, _ = git(path, 'rev-list', '--count', 'HEAD', '--not', '--remotes')
    return int(out.strip()) if rc == 0 and out.strip().isdigit() else None


def is_ancestor(path, commit, of):
    rc, _, _ = git(path, 'merge-base', '--is-ancestor', commit, of)
    return rc == 0


def _proc_cwds(proc='/proc'):
    """cwd of every process via /proc (Linux), or None when /proc has nothing to read."""
    cwds, seen = {}, 0
    try:
        pids = [p for p in os.listdir(proc) if p.isdigit()]
    except OSError:
        return None
    for pid in pids:
        try:
            cwd = os.readlink(os.path.join(proc, pid, 'cwd'))
            with open(os.path.join(proc, pid, 'comm')) as f:
                cmd = f.read().strip()
        except OSError:
            continue  # gone, or another user's process
        seen += 1
        cwds.setdefault(os.path.realpath(cwd), set()).add(cmd)
    return cwds if seen else None


def process_cwds():
    """cwd of every running process this user can see (/proc on Linux, else one lsof call).

    None when neither works or nothing came back: nobody can then say a tree is unused.
    Windows has neither: there the in-use probe in in_use() decides, and this map (read from this user's
    processes) only names who is in a folder.
    """
    if plat.WINDOWS:
        return plat.windows_cwds()
    if sys.platform.startswith('linux'):
        found = _proc_cwds()
        if found is not None:
            return found
    rc, out, _ = run(['lsof', '-a', '-d', 'cwd', '-Fpcn'], timeout=120)
    if rc in (124, 127) or not out.strip():
        return None
    cwds, cmd = {}, ''
    for line in out.splitlines():
        if line.startswith('c'):
            cmd = line[1:]
        elif line.startswith('n'):
            cwds.setdefault(os.path.realpath(line[1:]), set()).add(cmd)
    return cwds


def in_use(path, cwds):
    if cwds is None:
        return None
    real = os.path.realpath(path)
    names = sorted({c for d, cs in cwds.items() if plat.same_or_inside(d, real) for c in cs})
    if plat.WINDOWS:
        # The deciding check: a folder some process sits in can't be opened exclusively. It sees processes
        # of every user, elevated ones too; the map above only puts names to them.
        busy = plat.busy_dirs(path)
        if busy is None:
            return None
        if busy and not names:
            names = [f'another process (folder {busy[0]} is open)']
    return names


def parked_folders():
    """Folders where a paused session will resume, or None when no such tool is wired in.

    Extension point: if you use a tool that saves and later resumes Claude sessions, return the set
    of real paths of their working folders here, and reclaim keeps those worktrees. None means
    "not checked" and the scan reports park_checked = false.
    """
    return None


def gh_status(repos):
    """('ok', None) when PRs can be looked up, else (None, why). Asked once per scan.

    Without gh, a login, or a GitHub remote, the scan still works on age and unpushed commits and
    says PRs were not checked: it never keeps every tree just because it cannot ask.
    """
    if not shutil.which('gh'):
        return None, 'gh is not installed'
    rc, _, _ = run(['gh', 'auth', 'status'], timeout=30)
    if rc != 0:
        return None, 'gh is not logged in'
    # A lookup that fails later (network, a non-GitHub remote) still keeps that tree: only the stable
    # "no gh" and "not logged in" cases degrade, and the scan says so.
    return 'ok', None


def pr_facts(path, branch):
    """PRs for this worktree's branch (or, for a detached `...-<n>` folder, PR n)."""
    if branch:
        rc, out, _ = run(['gh', 'pr', 'list', '--head', branch, '--state', 'all', '--limit', '30',
                          '--json', 'number,state,headRefOid'], cwd=path, timeout=60)
    else:
        m = re.search(r'-(\d+)$', plat.base_name(path))
        if not m:
            return []
        rc, out, _ = run(['gh', 'pr', 'view', m.group(1), '--json', 'number,state,headRefOid'],
                         cwd=path, timeout=60)
        out = f'[{out}]' if rc == 0 else out
    if rc != 0:
        return None  # unknown, not "no PR"
    try:
        return json.loads(out or '[]')
    except ValueError:
        return None


def _ignored_stamp(path, entry):
    """Size and mtime of an ignored file, or count, total size and newest mtime of an ignored folder."""
    full = os.path.join(path, entry)
    try:
        if os.path.isdir(full) and not plat.is_link_or_junction(full):
            n = size = newest = 0
            for root, dirs, files in plat.walk(full):
                dirs[:] = [d for d in dirs if d not in BUILD_DIRS]
                for name in files:
                    try:
                        st = os.lstat(os.path.join(root, name))
                    except OSError:
                        continue
                    n += 1
                    size += st.st_size
                    newest = max(newest, st.st_mtime_ns)
            return f'{n}:{size}:{newest}'
        st = os.lstat(full)
        return f'{st.st_size}:{st.st_mtime_ns}'
    except OSError:
        return 'gone'


def hidden_changes(path):
    """True when files are marked skip-worktree (sparse checkout) or assume-unchanged: git status
    cannot see edits to them, so the tree is kept. None when git fails (also kept)."""
    rc, out, _ = git(path, 'ls-files', '-v', '-z')
    if rc != 0:
        return None
    return any(e[:1] == 'S' or e[:1].islower() for e in out.split('\0') if e)


def is_locked(path):
    rc, gitdir, _ = git(path, 'rev-parse', '--absolute-git-dir')
    return rc == 0 and os.path.exists(os.path.join(gitdir.strip(), 'locked'))


def forget_worktree(repo, path):
    """Drop git's record of one missing worktree. Unlike `git worktree prune` it touches no other entry
    (a worktree on an unplugged disk looks missing too)."""
    rc, common, _ = git(repo, 'rev-parse', '--path-format=absolute', '--git-common-dir')
    if rc != 0:
        return False
    admin = os.path.join(common.strip(), 'worktrees')
    try:
        names = os.listdir(admin)
    except OSError:
        return False
    for name in names:
        d = os.path.join(admin, name)
        try:
            target = open(os.path.join(d, 'gitdir')).read().strip()
        except OSError:
            continue
        if os.path.realpath(os.path.dirname(target)) == os.path.realpath(path) or \
                os.path.dirname(target) == path:
            if os.path.exists(os.path.join(d, 'locked')):
                return False
            shutil.rmtree(d, ignore_errors=True)
            return True
    return False


def fingerprint(path, head, status, ignored):
    """Changes when HEAD, the set of changed/ignored files, or any changed file's size or mtime does."""
    h = hashlib.sha256()
    h.update((head or '').encode())
    for xy, name in status or []:
        try:
            st = os.lstat(os.path.join(path, name))
            stamp = f'{st.st_size}:{st.st_mtime_ns}'
        except OSError:
            stamp = 'gone'
        h.update(f'{xy} {name} {stamp}\0'.encode())
    for e in ignored or []:
        h.update(f'{e} {_ignored_stamp(path, e)}\0'.encode())  # an edited .env.local changes this
    return h.hexdigest()[:16]


# ---------- verdict ----------

def inspect(path, is_main, cutoff, cwds, parked, with_prs=True, current=None):
    row = {'path': path, 'main': is_main}
    if not os.path.isdir(path):
        parent = os.path.dirname(plat.strip_sep(path))
        if not os.path.isdir(parent) or not os.listdir(parent):
            # The parent is gone, or an empty mount point: more likely an unplugged disk than a deleted worktree.
            row.update(verdict='keep', reasons=['folder and its parent are missing or empty (unplugged disk?)'])
        else:
            row.update(verdict='prune', reasons=['folder is gone'])
        return row
    rc, head, _ = git(path, 'rev-parse', 'HEAD')
    head = head.strip()
    rc_b, branch, _ = git(path, 'symbolic-ref', '-q', '--short', 'HEAD')
    branch = branch.strip() if rc_b == 0 else ''
    rc_t, last_commit, _ = git(path, 'log', '-1', '--format=%ct')
    last_commit = int(last_commit.strip() or 0) if rc_t == 0 else 0
    status = status_entries(path)
    ignored = ignored_entries(path)
    nested = nested_checkouts(path)
    hidden = hidden_changes(path)
    locked = is_locked(path)
    tracked = [n for xy, n in status or [] if xy != '??']
    untracked = [n for xy, n in status or [] if xy == '??']
    changed = tracked + untracked
    # Ignored files (.env, built binaries) are backed up but are not activity: tools rewrite them.
    edited = recent_edit(path, cutoff, changed)
    last_moved = last_checkout(path)
    row.update(
        branch=branch or None, head=head, last_commit=last_commit, last_checkout=last_moved,
        recent_edit=edited, tracked=len(tracked), untracked=len(untracked), ignored=ignored or [],
        local_commits=commits_not_on_remote(path), in_use=in_use(path, cwds),
        fingerprint=fingerprint(path, head, status, ignored),
    )
    prs = pr_facts(path, branch) if with_prs else []
    open_prs = [p['number'] for p in prs or [] if p.get('state') == 'OPEN']
    merged = [p for p in prs or [] if p.get('state') == 'MERGED']
    # A merged PR from a fork can share a branch name like "main": never treat those as merged work.
    shared_name = branch in ('main', 'master', 'develop', 'dev', 'trunk', 'release')
    merged_safe = [] if shared_name else [
        p['number'] for p in merged if is_ancestor(path, head, p.get('headRefOid', ''))]
    row.update(open_prs=open_prs, merged_prs=merged_safe, pr_lookup_failed=prs is None)

    keep = []
    real = os.path.realpath(path)
    if is_main:
        keep.append('main checkout')
    if current and plat.same_or_inside(current, real):
        keep.append('this session runs here')
    if row['in_use'] is None:
        keep.append('could not check which processes use it' if plat.WINDOWS else
                    'could not list running processes (lsof)')
    elif row['in_use']:
        keep.append('in use by ' + ', '.join(row['in_use'][:3]))
    if parked is not None and any(plat.same_or_inside(p, real) for p in parked):
        keep.append('a parked session will resume here')
    if open_prs:
        keep.append('open PR #' + ', #'.join(map(str, open_prs)))
    # A merged, clean tree holds nothing the PR doesn't, so fresh mtimes (a checkout, a build) don't
    # keep it. Uncommitted edits in a merged tree are kept: someone is still working there.
    if edited and not (merged_safe and not tracked and not untracked):
        keep.append('edited since the cutoff')
    if locked:
        keep.append('worktree is locked')
    if hidden:
        keep.append('has skip-worktree or assume-unchanged files (sparse checkout?)')
    elif hidden is None:
        keep.append('could not list hidden files')
    if status is None:
        keep.append('git status failed')
    if ignored is None:
        keep.append('listing ignored files failed')
    if nested and not is_main:
        keep.append('holds another checkout: ' + ', '.join(nested[:3]))
    if row['local_commits'] is None:
        keep.append('could not count commits on no remote')
    if not branch and unreachable_detached(path):
        keep.append('detached HEAD no branch holds')
    if row['local_commits'] and not merged_safe:
        keep.append(f"{row['local_commits']} commit(s) on no remote")
    if prs is None and with_prs:
        keep.append('PR lookup failed')
    old = max(last_commit, last_moved) < cutoff
    if not keep and not old and not merged_safe:
        keep.append('newer than the cutoff')
    row['why'] = ('merged PR #' + str(merged_safe[0])) if merged_safe else ('old' if old else '')
    row['parked_check'] = parked is not None
    row['old'] = old
    if keep:
        row.update(verdict='keep', reasons=keep)
    elif tracked or untracked or ignored:
        row.update(verdict='backup+remove', reasons=[row['why']])
    else:
        row.update(verdict='remove', reasons=[row['why']])
    return row


def scan(repos, days, merged=True, current=None, with_size=True, warnings=None):
    cutoff = now() - days * 86400
    cwds = process_cwds()
    parked = parked_folders()
    current = os.path.realpath(current or os.getcwd())
    gh_ok, gh_why = gh_status(repos)
    warnings = list(warnings or [])
    if gh_ok is None:
        warnings.append(f'PRs were not checked ({gh_why}): the verdicts use age and unpushed commits only')
    if cwds is None:
        warnings.append('running processes could not be checked: every worktree is kept' if plat.WINDOWS else
                        'running processes could not be listed (no lsof or /proc): every worktree is kept')
    trees = []
    for repo in repos:
        listed = list_worktrees(repo)
        if len(listed) == 1 and listed[0][1] and os.path.isdir(listed[0][0]):
            continue  # only the main checkout: nothing to clean, and it is never removed
        for path, is_main in listed:
            trees.append((repo, path, is_main))

    def one(item):
        repo, path, is_main = item
        row = inspect(path, is_main, cutoff, cwds, parked, with_prs=gh_ok is not None, current=current)
        row['repo'] = repo
        if not merged and row['verdict'] not in ('keep', 'prune') and not row.get('old'):
            row.update(verdict='keep', reasons=['merged, but merged removal is off'])
        if with_size and row['verdict'] != 'prune' and row['verdict'] != 'keep':
            row['size'] = du_bytes(path)
        return row

    with ThreadPoolExecutor(max_workers=6) as pool:
        rows = list(pool.map(one, trees))
    result = {'at': now(), 'days': days, 'cutoff': cutoff, 'park_checked': parked is not None,
              'prs_checked': gh_ok is not None, 'warnings': warnings, 'rows': rows, 'repos': list(repos)}
    write_atomic(home() / SCAN_FILE, json.dumps(result, indent=2))
    return result


# ---------- removal ----------

def remove(paths, backup_dir, backup_fn):
    """Remove worktrees the last scan approved, re-checking each one first. Never falls back to --force."""
    f = home() / SCAN_FILE
    if not f.exists():
        return {'error': 'no scan yet: run scan first'}
    last = json.loads(f.read_text())
    if now() - last['at'] > SCAN_MAX_AGE:
        return {'error': 'the last scan is over an hour old: run scan again'}
    by_path = {os.path.realpath(r['path']): r for r in last['rows']}
    cwds = process_cwds()
    parked = parked_folders()
    out = []
    for given in paths:
        path = os.path.realpath(given)  # /var vs /private/var, symlinked homes
        try:
            out.append(_remove_one(path, by_path.get(path), last, cwds, parked, backup_dir, backup_fn))
        except Exception as exc:  # one tree's surprise must not lose the report for the others
            out.append({'path': path, 'result': 'failed', 'why': f'{type(exc).__name__}: {exc}'})
    # No blanket `git worktree prune` here: `git worktree remove` clears its own entry, and a global
    # prune would also drop entries for worktrees on an unplugged disk, which nobody approved.
    return {'results': out}


def _remove_one(path, before, last, cwds, parked, backup_dir, backup_fn):
    if not before or before['verdict'] not in ('remove', 'backup+remove', 'prune'):
        return {'path': path, 'result': 'skipped', 'why': 'the last scan did not approve it'}
    if before['verdict'] == 'prune':
        if os.path.exists(path):
            return {'path': path, 'result': 'skipped', 'why': 'the folder is back'}
        if not forget_worktree(before['repo'], path):
            return {'path': path, 'result': 'skipped', 'why': 'could not find or clear its git record (locked?)'}
        return {'path': path, 'result': 'pruned'}
    now_row = inspect(path, before['main'], last['cutoff'], cwds, parked,
                      current=os.path.realpath(os.getcwd()))
    if now_row['verdict'] == 'keep':
        return {'path': path, 'result': 'skipped', 'why': '; '.join(now_row['reasons'])}
    if now_row['fingerprint'] != before['fingerprint']:
        return {'path': path, 'result': 'skipped', 'why': 'changed since the scan'}
    force = []
    backup = None
    if now_row['verdict'] == 'backup+remove':
        backup = backup_fn(path, backup_dir)
        if not backup.get('ok'):
            return {'path': path, 'result': 'skipped', 'why': 'backup failed: ' + backup.get('error', '')}
        # The backup can take minutes: anything that moved meanwhile isn't in it, so check again.
        after = inspect(path, before['main'], last['cutoff'], process_cwds(), parked,
                        current=os.path.realpath(os.getcwd()))
        if after['verdict'] == 'keep' or after['fingerprint'] != now_row['fingerprint']:
            return {'path': path, 'result': 'skipped', 'why': 'changed during the backup (backup kept)',
                    'backup': backup.get('dir')}
        if now_row['tracked'] or now_row['untracked']:
            force = ['--force']  # only after a verified backup that still matches the tree
    if plat.WINDOWS:
        # Windows can't delete a file another process has open: a delete would stop partway. Check every
        # file first and keep the tree whole when one is held.
        held = plat.held_files(path)
        if held is None:
            return {'path': path, 'result': 'skipped', 'why': 'could not check for files other programs hold open',
                    'backup': backup and backup.get('dir')}
        if held['count']:
            who = ', '.join(held['by'][:3]) or 'another program'
            return {'path': path, 'result': 'skipped', 'backup': backup and backup.get('dir'),
                    'why': f"locked by {who}: {held['count']} file(s) held open, first {held['files'][0]}"}
    rc, _, err = git(before['repo'], 'worktree', 'remove', *force, path, timeout=600)
    if rc != 0:
        return _partial(path, {'path': path, 'result': 'failed', 'why': err.strip(),
                               'backup': backup and backup.get('dir')})
    if plat.WINDOWS and os.path.lexists(path):
        # git leaves a junction (and the folders above it) behind: it never follows one, nor removes it.
        # Remove those links and the folders they leave empty, never entering a link; any real file stays.
        plat.delete_tree(path, files=False)
        if os.path.lexists(path):
            return _partial(path, {'path': path, 'result': 'failed', 'why': 'git removed the worktree but not all '
                                   'of its folder', 'backup': backup and backup.get('dir')})
    return {'path': path, 'result': 'removed', 'backup': backup and backup.get('dir')}


def _partial(path, row):
    """A removal that stopped partway: say exactly what is left. Commits stay in git and the uncommitted work
    is in the backup; nothing can be put back into the folder from it, so say that too."""
    if os.path.isdir(path):
        left = [f for _, _, files in plat.walk(path) for f in files]
        row['left'] = {'files': len(left), 'folder': path}
        row['safe'] = 'the commits are in git' + (
            ' and the uncommitted work is in the backup' if row.get('backup') else '')
    return row
