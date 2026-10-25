#!/usr/bin/env python3
"""State for /retro: last run, reminder bookkeeping, applied and rejected proposals.

Every write holds an flock and replaces the file atomically, so parallel sessions
(one per worktree) never interleave or leave half-written JSON.

  state.py show
  state.py remind --cwd DIR [--source startup]     # SessionStart hook; prints hook JSON or nothing
  state.py snooze DAYS
  state.py skip                                    # snooze one full interval; the window still starts at last_run
  state.py record RUN.json                         # merge a finished run; sets last_run (arms the reminder)
  state.py set-pr RUN_ID URL                       # a run's local branch was shared later as a draft PR
  state.py mark-reverted RUN_ID [--personal-only]  # --personal-only leaves entries with a PR applied

Which repo counts, and the reminder interval, come from config.py (~/.claude/retro/config.json);
`remind` stays silent without it. A state.json `interval_days` wins over the config's
`reminder_interval_days`. RETRO_HOME overrides ~/.claude/retro and RETRO_TODAY (YYYY-MM-DD)
overrides today, for tests.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import fcntl
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config  # noqa: E402
from config import DEFAULT_INTERVAL_DAYS, home  # noqa: E402


def state_path() -> Path:
    return home() / 'state.json'


def today() -> dt.date:
    forced = os.environ.get('RETRO_TODAY')
    return dt.date.fromisoformat(forced) if forced else dt.date.today()


def empty_state() -> dict:
    return {'version': 1, 'interval_days': None, 'last_run': None,
            'last_reminded': None, 'snooze_until': None, 'applied': [], 'rejected': []}


def load() -> dict:
    try:
        data = json.loads(state_path().read_text())
    except FileNotFoundError:
        return empty_state()
    merged = empty_state()
    merged.update(data)
    return merged


@contextlib.contextmanager
def locked():
    """Yield the current state; whatever the caller leaves in it is written back atomically."""
    home().mkdir(parents=True, exist_ok=True)
    with open(home() / '.state.lock', 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        state = load()
        yield state
        fd, tmp = tempfile.mkstemp(dir=home(), prefix='.state.', suffix='.json')
        with os.fdopen(fd, 'w') as fh:
            json.dump(state, fh, indent=2, ensure_ascii=False)
            fh.write('\n')
        os.replace(tmp, state_path())


def interval_days(state: dict) -> int:
    """state.json `interval_days` if set, else the config's `reminder_interval_days`, else the default."""
    if state.get('interval_days'):
        return int(state['interval_days'])
    try:
        return config.load()['reminder_interval_days']
    except config.ConfigError as _:
        return DEFAULT_INTERVAL_DAYS


def repo_folder_match(cwd: str) -> bool:
    """For a cwd with no git remote to ask (a removed worktree, no origin): its folder name."""
    return config.load()['repo_folder'] in Path(cwd).parts


def is_main_repo(cwd: str) -> bool:
    """True when cwd is a checkout of the configured repo; raises config.ConfigError without a config."""
    remote = config.load()['remote_regex']
    try:
        url = subprocess.run(['git', '-C', cwd, 'remote', 'get-url', 'origin'],
                             capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError) as _:
        url = ''
    if url:
        return bool(re.search(remote, url))
    # No git (or no origin): fall back to the folder name.
    return repo_folder_match(cwd)


def due_message(state: dict, now: dt.date) -> str | None:
    if not state.get('last_run'):
        return None  # Armed only by the first manual run.
    days = (now - dt.date.fromisoformat(state['last_run'])).days
    if days < interval_days(state):
        return None
    if state.get('snooze_until') and now < dt.date.fromisoformat(state['snooze_until']):
        return None
    if state.get('last_reminded') == now.isoformat():
        return None
    state_py = Path(__file__).resolve()
    return (f'{days} days since the last /retro (on {state["last_run"]}). Before working on the '
            "user's first request, ask once with AskUserQuestion: \"Run /retro now\" (then run the "
            'retro skill, and continue the original request afterwards) / "Snooze 3 days" / "Skip this '
            f'cycle". For snooze run `python3 {state_py} snooze 3`; for '
            f'skip run `python3 {state_py} skip`. If you cannot ask '
            '(non-interactive run), say nothing about it.')


def cmd_remind(cwd: str, source: str | None) -> None:
    if source and source != 'startup':
        return
    try:
        if not cwd or not is_main_repo(cwd):
            return
    except config.ConfigError as _:
        return  # Not set up (or unreadable config): stay silent, never break a session start.
    now = today()
    if due_message(load(), now) is None:
        return  # Cheap unlocked check first: almost every session start ends here.
    with locked() as state:
        message = due_message(state, now)  # Re-check under the lock: a parallel tab may have just fired.
        if message is None:
            return
        # Stamp before emitting: a tab closed before answering still counts as reminded today.
        state['last_reminded'] = now.isoformat()
    print(json.dumps({'hookSpecificOutput': {'hookEventName': 'SessionStart',
                                             'additionalContext': message}}))


def cmd_record(run_file: str) -> None:
    run = json.loads(Path(run_file).read_text())
    run_id = run['run_id']
    with locked() as state:
        for kind in ('applied', 'rejected'):
            for entry in run.get(kind, []):
                entry.setdefault('run_id', run_id)
                entry.setdefault('date', today().isoformat())
                if kind == 'applied':
                    entry.setdefault('status', 'applied')
                state[kind].append(entry)
        state['last_run'] = run.get('date', today().isoformat())
        state['snooze_until'] = None
    print(f'recorded {run_id}: {len(run.get("applied", []))} applied, '
          f'{len(run.get("rejected", []))} rejected; last_run={state["last_run"]}')


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ('-h', '--help'):
        print(__doc__)
        return 0
    cmd, args = argv[0], argv[1:]
    if cmd == 'show':
        print(json.dumps(load(), indent=2, ensure_ascii=False))
    elif cmd == 'remind':
        opts = dict(zip(args[::2], args[1::2]))
        if '--cwd' not in opts:
            # Hook mode: read Claude Code's SessionStart payload from stdin.
            try:
                payload = json.loads(sys.stdin.read() or '{}')
            except ValueError as _:
                payload = {}
            opts = {'--cwd': payload.get('cwd') or os.getcwd(), '--source': payload.get('source')}
        cmd_remind(opts['--cwd'], opts.get('--source'))
    elif cmd == 'snooze':
        with locked() as state:
            state['snooze_until'] = (today() + dt.timedelta(days=int(args[0]))).isoformat()
        print(f'snoozed until {state["snooze_until"]}')
    elif cmd == 'skip':
        with locked() as state:
            state['snooze_until'] = (today() + dt.timedelta(days=interval_days(state))).isoformat()
        print(f'skipped this cycle; next reminder from {state["snooze_until"]}')
    elif cmd == 'record':
        cmd_record(args[0])
    elif cmd == 'set-pr':
        with locked() as state:
            hits = [e for e in state['applied'] if e.get('run_id') == args[0] and e.get('branch')]
            for entry in hits:
                entry['pr'] = args[1]
        print(f'set pr on {len(hits)} repo entries of {args[0]}')
    elif cmd == 'mark-reverted':
        personal_only = '--personal-only' in args[1:]
        with locked() as state:
            hits = [e for e in state['applied'] if e.get('run_id') == args[0]
                    and not (personal_only and (e.get('pr') or e.get('branch')))]
            for entry in hits:
                entry['status'] = 'reverted'
        print(f'marked {len(hits)} applied entries of {args[0]} as reverted')
    else:
        print(f'unknown command: {cmd}\n{__doc__}', file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
