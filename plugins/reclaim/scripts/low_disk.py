"""SessionStart hook. Prints hook JSON when free space is below warn_gb on a drive that matters (the
system's, or one holding a repo, a repo folder, the backups or Docker's disk), at most once an hour.

systemMessage is shown to the user; additionalContext lets Claude offer /reclaim. Silent when there is
no config, the hook is off, space is fine, or it already warned within the hour. Never raises.
"""
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import drives, fallback_home, home, load_config, remember_data_dir, watched_paths, write_atomic  # noqa: E402


def main():
    remember_data_dir()  # always: the CLI finds this hook's data folder through it
    data = home()
    cfg = load_config()
    if not cfg['configured']:
        # Settings saved before the pointer existed sit in the fallback folder: use them.
        old = fallback_home() / 'config.json'
        if data != fallback_home() and old.exists():
            os.environ['RECLAIM_HOME'] = str(fallback_home())
            data = fallback_home()
            cfg = load_config()
    if not cfg['configured'] or cfg['hook'] is False:
        return
    warn = cfg['warn_gb']
    try:
        import vdisk  # file checks only: where Docker's disk image is
        disks = [p for p, _ in vdisk.disk_paths()]
    except Exception:
        disks = []
    low = [d for d in drives(watched_paths(cfg, disks)) if d['free_gb'] < warn]
    if not low:
        return
    stamp = data / 'last-warning'
    try:
        last = float(stamp.read_text().strip())
    except (OSError, ValueError):
        last = 0
    if time.time() - last < 3600:
        return
    try:
        write_atomic(stamp, str(int(time.time())) + '\n')
    except OSError:
        pass
    where = ', '.join(f"{d['free_gb']:g} GB on {d['volume']} ({', '.join(d['holds'])})" for d in low)
    msg = (f'reclaim: only {where} free (your warning level is {warn:g} GB). '
           'Run /reclaim to clear old worktrees, build folders, caches and Docker data.')
    print(json.dumps({'systemMessage': msg,
                      'hookSpecificOutput': {'hookEventName': 'SessionStart', 'additionalContext': msg}}))


if __name__ == '__main__':
    try:
        main()
    except Exception:
        pass
