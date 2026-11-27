"""Back up a worktree's uncommitted work before it is removed.

<backup_dir>/<name>-<YYYYmmdd-HHMM>/
  INFO.txt        worktree, branch, head, and how to restore
  tracked.patch   git diff HEAD --binary
  untracked.tgz   new files git doesn't track
  ignored.tgz     gitignored files outside build folders (.env.local and the like)

A backup counts only when every part was written and each archive lists back the files it should hold.
"""
import os
import subprocess
import time
from pathlib import Path

from common import free_bytes, git, run
from worktrees import ignored_entries

HEADROOM = 1_000_000_000  # keep at least 1 GB free after the backup


def _size(path, entries):
    total = 0
    for e in entries:
        p = os.path.join(path, e)
        if os.path.isdir(p):
            for root, _, files in os.walk(p):
                for f in files:
                    try:
                        total += os.lstat(os.path.join(root, f)).st_size
                    except OSError:
                        pass
        else:
            try:
                total += os.lstat(p).st_size
            except OSError:
                pass
    return total


def _tar(src, entries, dest):
    """tar the entries; return the number of files it lists back, or an error."""
    if not entries:
        return 0, None
    listfile = dest.with_suffix('.list')
    listfile.write_bytes(b'\0'.join(e.encode() for e in entries))
    rc, _, err = run(['tar', '-czf', str(dest), '--null', '-T', str(listfile)], cwd=src, timeout=1800)
    listfile.unlink()
    if rc != 0:
        return None, f'tar failed: {err.strip()}'
    rc, out, err = run(['tar', '-tzf', str(dest)], timeout=600)
    if rc != 0:
        return None, f'archive does not read back: {err.strip()}'
    return len([line for line in out.splitlines() if line.strip()]), None


def backup(path, backup_dir):
    path = str(path)
    name = os.path.basename(path.rstrip('/'))
    base = Path(os.path.expanduser(backup_dir)) / f"{name}-{time.strftime('%Y%m%d-%H%M%S')}"
    dest, n = base, 1
    while dest.exists():  # two trees with one name, or a retry after a failed backup
        n += 1
        dest = base.with_name(f'{base.name}-{n}')
    rc, untracked, err = git(path, 'ls-files', '--others', '--exclude-standard', '-z')
    if rc != 0:
        return {'ok': False, 'error': err.strip()}
    untracked = [u for u in untracked.split('\0') if u]
    ignored = ignored_entries(path)
    if ignored is None:
        return {'ok': False, 'error': 'could not list ignored files'}
    # bytes, not text: a patch of a non-UTF-8 file must round-trip exactly
    try:
        p = subprocess.run(['git', '-C', path, 'diff', 'HEAD', '--binary'], capture_output=True, timeout=600)
    except subprocess.TimeoutExpired:
        return {'ok': False, 'error': 'git diff timed out'}
    if p.returncode != 0:
        return {'ok': False, 'error': f'git diff failed: {p.stderr.decode(errors="replace").strip()}'}
    patch = p.stdout

    need = len(patch) + _size(path, untracked) + _size(path, ignored)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if free_bytes(str(dest.parent)) < need + HEADROOM:
        return {'ok': False, 'error': f'not enough free space for a {need // 1_000_000} MB backup'}
    dest.mkdir(parents=True, exist_ok=False)

    _, branch, _ = git(path, 'symbolic-ref', '-q', '--short', 'HEAD')
    _, head, _ = git(path, 'rev-parse', 'HEAD')
    (dest / 'tracked.patch').write_bytes(patch)
    # The index can differ from the working tree (staged, then edited again): keep it separately.
    try:
        sp = subprocess.run(['git', '-C', path, 'diff', '--cached', '--binary'], capture_output=True, timeout=600)
    except subprocess.TimeoutExpired:
        return {'ok': False, 'error': 'git diff --cached timed out', 'dir': str(dest)}
    if sp.returncode != 0:
        return {'ok': False, 'error': 'git diff --cached failed', 'dir': str(dest)}
    (dest / 'staged.patch').write_bytes(sp.stdout)
    n_untracked, err = _tar(path, untracked, dest / 'untracked.tgz')
    if err:
        return {'ok': False, 'error': err, 'dir': str(dest)}
    if n_untracked < len(untracked):
        return {'ok': False, 'error': f'untracked.tgz holds {n_untracked} of {len(untracked)} files', 'dir': str(dest)}
    n_ignored, err = _tar(path, ignored, dest / 'ignored.tgz')
    if err:
        return {'ok': False, 'error': err, 'dir': str(dest)}
    if n_ignored < len(ignored):
        return {'ok': False, 'error': f'ignored.tgz holds {n_ignored} of {len(ignored)} entries', 'dir': str(dest)}
    if (dest / 'tracked.patch').stat().st_size != len(patch):
        return {'ok': False, 'error': 'tracked.patch is short', 'dir': str(dest)}

    (dest / 'INFO.txt').write_text(
        f'worktree: {path}\nbranch: {branch.strip() or "(detached)"}\nhead: {head.strip()}\n'
        f'untracked files: {len(untracked)}\nignored entries: {len(ignored)}\n\n'
        'Restore:\n'
        f'  git worktree add <path> {branch.strip() or head.strip()}\n'
        '  cd <path> && git apply <this folder>/tracked.patch\n'
        '  (optional) git apply --cached <this folder>/staged.patch   # to restore what was staged\n'
        '  tar -xzf <this folder>/untracked.tgz && tar -xzf <this folder>/ignored.tgz\n'
    )
    return {'ok': True, 'dir': str(dest), 'untracked': len(untracked), 'ignored': len(ignored)}
