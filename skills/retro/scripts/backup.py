#!/usr/bin/env python3
"""Snapshot files around /retro's edits, so restore.py can undo exactly those edits.

  backup.py RUN_ID PATH...                  # BEFORE editing personal files
  backup.py RUN_ID --after PATH...          # AFTER editing them: records what retro wrote
  backup.py RUN_ID --repo WT --pr URL PATH...   # repo files in retro's worktree: kept for reference;
                                            # restore prints how to undo the PR instead

Both snapshots are needed: restore compares the file now with what retro wrote, so it can
undo retro's edit without losing anything changed after the run. The first snapshot of a
path wins: backing it up again later in the run never overwrites the original.
Backups live in ~/.claude/retro/backups/RUN_ID/ (RETRO_HOME overrides).
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
from pathlib import Path


def backups_root() -> Path:
    return Path(os.environ.get('RETRO_HOME', Path.home() / '.claude' / 'retro')) / 'backups'


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_manifest(run_dir: Path) -> dict:
    try:
        return json.loads((run_dir / 'manifest.json').read_text())
    except FileNotFoundError:
        return {'run_id': run_dir.name, 'entries': []}


def save_manifest(run_dir: Path, manifest: dict) -> None:
    tmp = run_dir / '.manifest.json.tmp'
    tmp.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + '\n')
    os.replace(tmp, run_dir / 'manifest.json')


def snapshot(run_id: str, paths: list[str], repo: str | None = None, pr: str | None = None) -> dict:
    run_dir = backups_root() / run_id
    (run_dir / 'files').mkdir(parents=True, exist_ok=True)
    manifest = load_manifest(run_dir)
    known = {e['path'] for e in manifest['entries']}
    for raw in paths:
        path = Path(raw).expanduser().resolve()
        if str(path) in known:
            continue
        entry = {'path': str(path), 'created': not path.exists(), 'sha256': None, 'backup': None}
        if repo:
            entry.update(repo=str(Path(repo).resolve()), pr=pr)
        if path.exists():
            copy = run_dir / 'files' / path.relative_to(path.anchor)
            copy.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, copy)
            entry.update(sha256=sha256(path), backup=str(copy.relative_to(run_dir)))
        manifest['entries'].append(entry)
        known.add(str(path))
    if pr:
        # A PR URL known only after the edits were backed up still reaches every repo entry.
        for entry in manifest['entries']:
            if entry.get('repo') and not entry.get('pr'):
                entry['pr'] = pr
    save_manifest(run_dir, manifest)
    return manifest


def snapshot_after(run_id: str, paths: list[str]) -> dict:
    run_dir = backups_root() / run_id
    manifest = load_manifest(run_dir)
    by_path = {e['path']: e for e in manifest['entries']}
    for raw in paths:
        path = Path(raw).expanduser().resolve()
        entry = by_path.get(str(path))
        if entry is None:
            raise SystemExit(f'{path} was never backed up before editing; back it up first')
        if not path.exists():
            entry.update(after_sha256=None, after=None)  # Retro deleted it.
            continue
        copy = run_dir / 'after' / path.relative_to(path.anchor)
        copy.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, copy)
        entry.update(after_sha256=sha256(path), after=str(copy.relative_to(run_dir)))
    save_manifest(run_dir, manifest)
    return manifest


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[0] in ('-h', '--help'):
        print(__doc__)
        return 0 if argv and argv[0] in ('-h', '--help') else 2
    run_id, rest = argv[0], argv[1:]
    if rest[0] == '--after':
        manifest = snapshot_after(run_id, rest[1:])
        print(f'{run_id}: recorded what retro wrote for {len(rest) - 1} files')
        return 0
    repo = pr = None
    paths = []
    it = iter(rest)
    for arg in it:
        if arg == '--repo':
            repo = next(it)
        elif arg == '--pr':
            pr = next(it)
        else:
            paths.append(arg)
    manifest = snapshot(run_id, paths, repo, pr)
    print(f'{run_id}: {len(manifest["entries"])} files in {backups_root() / run_id}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
