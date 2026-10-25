#!/usr/bin/env python3
"""Undo exactly what one /retro run changed, and nothing else.

  restore.py RUN_ID [--dry-run] [--only PATH ...]
  restore.py --list

For each personal file the run touched it compares the file now with what retro wrote:
  - unchanged since retro   -> the original is copied back
  - edited after retro      -> only retro's edit is reversed (3-way `git merge-file`, bytes
                               untouched elsewhere), later edits stay; on a conflict the file is
                               left alone and the merge is saved under backups/RUN_ID/conflicts/
  - created by retro        -> deleted only if nobody edited it since; otherwise left alone
  - no record of what retro wrote (the run stopped mid-apply) -> a missing original is copied
                               back; anything else is left alone and reported as a problem
Every file it modifies or deletes is first copied to backups/RUN_ID/pre-restore/<time>/, so a
restore can itself be undone. Repo files are never touched: their edits live in a PR, so it
prints how to undo that (close it, or `git revert` its merge commit, which keeps later work)
and never pushes or closes anything itself. --only limits the restore to the given paths.
Exit 1 when any file needs a manual look; state is marked reverted only on a clean, full restore.
Always run --dry-run first.
"""
from __future__ import annotations

import datetime as dt
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from backup import backups_root, sha256  # noqa: E402


def list_runs() -> None:
    root = backups_root()
    for manifest in sorted(root.glob('*/manifest.json')) if root.exists() else []:
        entries = json.loads(manifest.read_text())['entries']
        print(f'{manifest.parent.name}: {len(entries)} files')


def plan(entry: dict, run_dir: Path) -> tuple[str, str]:
    """Decide what restoring this entry means: skip, copy-original, delete, merge, or problem."""
    path = Path(entry['path'])
    exists = path.exists()
    now = sha256(path) if exists else None
    if 'after_sha256' not in entry:
        if now == entry['sha256']:
            return 'skip', 'already the original'
        if not exists and not entry['created']:
            return 'copy-original', 'missing, and no record of what retro wrote; original copied back'
        if not exists:
            return 'skip', 'already gone'
        # Without retro's version there is no telling retro's edit from later work, so touch nothing.
        return 'problem', (f'no record of what retro wrote (run stopped mid-apply); left alone, '
                           f'original is at {run_dir / entry["backup"]}' if entry['backup'] else
                           'no record of what retro wrote; left alone')
    if entry['created']:
        if not exists:
            return 'skip', 'already gone'
        if now == entry['after_sha256']:
            return 'delete', 'created by retro, unchanged since'
        return 'skip', 'created by retro but edited since; left in place'
    if entry['after_sha256'] is None:  # Retro deleted it.
        if exists:
            return 'skip', 'deleted by retro but recreated since; left in place'
        return 'copy-original', 'deleted by retro'
    if not exists:
        return 'skip', 'deleted after retro by someone else; left alone'
    if now == entry['sha256']:
        return 'skip', 'already the original'
    if now == entry['after_sha256']:
        return 'copy-original', 'unchanged since retro'
    return 'merge', 'edited after retro; reversing only retro\'s edit'


def reverse_merge(path: Path, run_dir: Path, entry: dict) -> tuple[int, bytes]:
    """Current file with retro's edit (after -> original) taken back out. Returns (conflicts, bytes)."""
    # Bytes, not text: text mode would rewrite CRLF line endings across the whole file.
    result = subprocess.run(
        ['git', 'merge-file', '-p', '-L', 'now', '-L', 'retro-wrote', '-L', 'before-retro',
         str(path), str(run_dir / entry['after']), str(run_dir / entry['backup'])],
        capture_output=True)
    if result.returncode < 0 or result.returncode > 127:
        raise RuntimeError(result.stderr.decode(errors='replace').strip())
    return result.returncode, result.stdout


def restore(run_id: str, dry_run: bool, only: list[str]) -> int:
    run_dir = backups_root() / run_id
    manifest = json.loads((run_dir / 'manifest.json').read_text())
    wanted = {str(Path(p).expanduser().resolve()) for p in only}
    pre = run_dir / 'pre-restore' / dt.datetime.now().strftime('%Y%m%d-%H%M%S')
    prs, problems, matched = set(), 0, 0
    for entry in manifest['entries']:
        path = Path(entry['path'])
        if wanted and entry['path'] not in wanted:
            continue
        matched += 1
        if entry.get('repo'):
            prs.add(entry.get('pr') or f'(no PR recorded; branch cut in {entry["repo"]})')
            continue
        action, reason = plan(entry, run_dir)
        if action == 'merge':
            conflicts, merged = reverse_merge(path, run_dir, entry)
            if conflicts:
                action, reason = 'conflict', f'edited after retro and {conflicts} hunk(s) overlap; left alone'
                if not dry_run:
                    out = run_dir / 'conflicts' / path.relative_to(path.anchor)
                    out.parent.mkdir(parents=True, exist_ok=True)
                    out.write_bytes(merged)
                    reason += f'; merge with markers saved to {out}'
        if action in ('conflict', 'problem'):
            problems += 1
        print(f'{"[dry-run] " if dry_run else ""}{action:13} {path}  ({reason})')
        if dry_run or action in ('skip', 'conflict', 'problem'):
            continue
        if path.exists():
            keep = pre / path.relative_to(path.anchor)
            keep.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, keep)
        if action == 'delete':
            path.unlink()
        elif action == 'copy-original':
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(run_dir / entry['backup'], path)
            if sha256(path) != entry['sha256']:
                print(f'  ERROR: sha256 mismatch after restore: {path}', file=sys.stderr)
                problems += 1
        elif action == 'merge':
            path.write_bytes(merged)
    if wanted and not matched:
        print(f'--only matched nothing in the manifest of {run_id}: {sorted(wanted)}', file=sys.stderr)
        return 2
    for pr in sorted(prs):
        print(f'repo side: close {pr} if still open, or `git revert` its merge commit if merged '
              '(a revert keeps everything merged after it)')
    if dry_run:
        return 1 if problems else 0
    if problems:
        print(f'{problems} file(s) need a manual look; state not marked reverted', file=sys.stderr)
        return 1
    if wanted:
        print('partial restore (--only); state not marked reverted')
        return 0
    state = Path(__file__).resolve().parent / 'state.py'
    # Repo cards stay applied until their PR is closed or reverted; only personal ones are undone here.
    subprocess.run([sys.executable, str(state), 'mark-reverted', run_id, '--personal-only'], check=True)
    return 0


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ('-h', '--help'):
        print(__doc__)
        return 0
    if argv[0] == '--list':
        list_runs()
        return 0
    run_id, rest, dry_run, only = argv[0], argv[1:], False, []
    it = iter(rest)
    for arg in it:
        if arg == '--dry-run':
            dry_run = True
        elif arg == '--only':
            only.append(next(it))
        elif only and not arg.startswith('-'):
            only.append(arg)
        else:
            print(f'unknown argument: {arg}\n{__doc__}', file=sys.stderr)
            return 2
    return restore(run_id, dry_run, only)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
