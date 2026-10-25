#!/usr/bin/env python3
"""Per-install settings for /retro: which repo, where its checkout lives, which issue tracker.

  config.py show      # print the resolved settings as JSON, or one error line (exit 1)
  config.py path      # print the file the settings are read from

Read from ~/.claude/retro/config.json. RETRO_HOME moves the folder; RETRO_CONFIG names the file.
Only `repo` is required; every other field has a default (see config.example.json and references/install.md):
  repo, repo_folder, remote_regex, default_checkout, base_branch, issue_tracker, issue_team,
  issue_prefix, instructions_file, instructions_cap_bytes, reminder_interval_days
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

DEFAULT_INTERVAL_DAYS = 14
REPO = re.compile(r'^[\w.-]+/[\w.-]+$')
TRACKERS = ('linear', 'none')


class ConfigError(Exception):
    """The message is the one line the user sees."""


def home() -> Path:
    return Path(os.environ.get('RETRO_HOME', Path.home() / '.claude' / 'retro'))


def config_path() -> Path:
    return Path(os.environ.get('RETRO_CONFIG') or home() / 'config.json').expanduser()


def _positive_int(raw: dict, key: str, default: int | None, path: Path) -> int | None:
    value = raw.get(key)
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ConfigError(f'retro: bad config at {path} — {key} must be a whole number of at least 1')
    return value


def _text(raw: dict, key: str, default: str, path: Path) -> str:
    value = raw.get(key)
    if value is None or value == '':
        return default
    if not isinstance(value, str):
        raise ConfigError(f'retro: bad config at {path} — {key} must be text')
    return value


def load() -> dict:
    """The settings with every default filled in; raises ConfigError (one line) when unusable."""
    path = config_path()
    try:
        raw = json.loads(path.read_text())
    except FileNotFoundError as _:
        raise ConfigError(f'retro: no config at {path} — run /retro --setup (see references/install.md)') from None
    except (OSError, ValueError) as _:
        raise ConfigError(f'retro: unreadable config at {path} — fix the JSON or run /retro --setup') from None
    if not isinstance(raw, dict):
        raise ConfigError(f'retro: bad config at {path} — expected a JSON object')
    repo = raw.get('repo')
    if not isinstance(repo, str) or not REPO.match(repo):
        raise ConfigError(f'retro: bad config at {path} — repo must look like OWNER/NAME')
    name = repo.split('/')[1]
    tracker = _text(raw, 'issue_tracker', 'none', path).lower()
    if tracker not in TRACKERS:
        raise ConfigError(f'retro: bad config at {path} — issue_tracker must be one of {", ".join(TRACKERS)}')
    cfg = {
        'repo': repo,
        'repo_folder': _text(raw, 'repo_folder', name, path),
        'remote_regex': _text(raw, 'remote_regex', rf'[/:]{re.escape(name)}(\.git)?/?$', path),
        'default_checkout': str(Path(_text(raw, 'default_checkout', f'~/code/{name}', path)).expanduser()),
        'base_branch': _text(raw, 'base_branch', 'main', path),
        'issue_tracker': tracker,
        'issue_team': _text(raw, 'issue_team', '', path),
        'issue_prefix': _text(raw, 'issue_prefix', '', path),
        'instructions_file': _text(raw, 'instructions_file', 'AGENTS.md', path),
        'instructions_cap_bytes': _positive_int(raw, 'instructions_cap_bytes', None, path),
        'reminder_interval_days': _positive_int(raw, 'reminder_interval_days', DEFAULT_INTERVAL_DAYS, path),
    }
    try:
        re.compile(cfg['remote_regex'])
    except re.error as _:
        raise ConfigError(f'retro: bad config at {path} — remote_regex is not a valid regex') from None
    return cfg


def require() -> dict:
    """For a script's entry point: the settings, or one line on stderr and exit 1."""
    try:
        return load()
    except ConfigError as err:
        sys.exit(str(err))


def main(argv: list[str]) -> int:
    if argv == ['show']:
        print(json.dumps(require(), indent=2, ensure_ascii=False))
    elif argv == ['path']:
        print(config_path())
    else:
        print(__doc__)
        return 0 if argv in (['-h'], ['--help']) else 2
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
