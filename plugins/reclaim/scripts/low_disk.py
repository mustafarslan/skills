"""SessionStart hook. Prints hook JSON when free space on / is below warn_gb, at most once an hour.

systemMessage is shown to the user; additionalContext lets Claude offer /reclaim. Silent when there is
no config, the hook is off, space is fine, or it already warned within the hour. Never raises.
"""
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import fallback_home, free_bytes, gb, home, load_config, remember_data_dir, write_atomic  # noqa: E402


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
    free = gb(free_bytes(os.path.splitdrive(str(Path.home()))[0] + os.sep if os.name == 'nt' else '/'))
    if free >= warn:
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
    msg = (f'reclaim: only {free:g} GB free on this machine (your warning level is {warn:g} GB). '
           'Run /reclaim to clear old worktrees and Docker data.')
    print(json.dumps({'systemMessage': msg,
                      'hookSpecificOutput': {'hookEventName': 'SessionStart', 'additionalContext': msg}}))


if __name__ == '__main__':
    try:
        main()
    except Exception:
        pass
