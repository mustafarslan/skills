"""Shared helpers: running commands, the config file, free disk space."""
import json
import os
import sys
import time
from pathlib import Path

import plat

# Folders that are rebuilt from scratch, so their age and contents never matter.
BUILD_DIRS = {
    'node_modules', '.venv', 'venv', '.next', '.turbo', '__pycache__', '.pytest_cache',
    '.mypy_cache', '.ruff_cache', 'dist', 'build', 'coverage', '.git', 'target', '.cache',
}

def default_backup_dir():
    # macOS people look in ~/Desktop; elsewhere don't create a Desktop folder just for this.
    if sys.platform == 'darwin':
        return str(Path.home() / 'Desktop' / 'worktree-backups')
    return str(Path.home() / 'reclaim-backups')


DEFAULTS = {
    'repos': [],
    'roots': [],
    'backup_dir': default_backup_dir(),
    'days': 3,
    'keep_containers': [],
    'warn_gb': 15,
    'hook': True,
    'cache_days': 30,
    'cache_dirs': [],
}


def fallback_home():
    return Path.home() / '.claude' / 'plugins' / 'data' / 'reclaim'


def home():
    """Per-user data folder, the same one for the hook and the CLI.

    The SessionStart hook is given CLAUDE_PLUGIN_DATA (a folder named <plugin>-<marketplace>), but
    commands run through Bash are not. So the hook leaves a pointer (data-dir) in the fallback folder
    (see remember_data_dir) and the CLI follows it. RECLAIM_HOME overrides everything, for tests.
    """
    env = os.environ.get('RECLAIM_HOME') or os.environ.get('CLAUDE_PLUGIN_DATA')
    path = Path(env) if env else fallback_home()
    if not env:
        pointer = fallback_home() / 'data-dir'
        try:
            target = Path(pointer.read_text().strip())
            if target.is_absolute() and target.is_dir():
                path = target
        except OSError:
            pass
    path.mkdir(parents=True, exist_ok=True)
    return path


def remember_data_dir():
    """Called by the hook: record the folder Claude Code gave it, for the CLI to find."""
    env = os.environ.get('CLAUDE_PLUGIN_DATA')
    if not env or os.environ.get('RECLAIM_HOME'):
        return
    fb = fallback_home()
    try:
        fb.mkdir(parents=True, exist_ok=True)
        write_atomic(fb / 'data-dir', str(Path(env)) + '\n')
    except OSError:
        pass


def write_atomic(path, text):
    tmp = Path(str(path) + '.tmp')
    tmp.write_text(text)
    os.replace(tmp, path)


def run(cmd, cwd=None, check=False, timeout=120):
    """Run a command; return (returncode, stdout, stderr). Never raises for a missing binary."""
    return plat.run(cmd, cwd=cwd, check=check, timeout=timeout)


def git(path, *args, timeout=120):
    # Windows: paths past 260 characters (deep node_modules) work only with core.longpaths.
    extra = ['-c', 'core.longpaths=true'] if plat.WINDOWS else []
    return run(['git', '-C', str(path), *extra, *args], timeout=timeout)


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


VALIDATORS = {
    'repos': lambda v: isinstance(v, list) and all(isinstance(x, str) for x in v),
    'roots': lambda v: isinstance(v, list) and all(isinstance(x, str) for x in v),
    'backup_dir': lambda v: isinstance(v, str) and v != '',
    'days': lambda v: _is_num(v) and v >= 0,
    'keep_containers': lambda v: isinstance(v, list) and all(isinstance(x, str) for x in v),
    'warn_gb': lambda v: _is_num(v) and v >= 0,
    'hook': lambda v: isinstance(v, bool),
    'cache_days': lambda v: _is_num(v) and v >= 0,
    'cache_dirs': lambda v: isinstance(v, list) and all(isinstance(x, str) for x in v),
}


def load_config():
    """Defaults, overlaid with config.json. A broken file or a bad value never crashes: the default
    is used and the problem is listed under config_problems."""
    f = home() / 'config.json'
    cfg = dict(DEFAULTS)
    problems = []
    if f.exists():
        try:
            data = json.loads(f.read_text())
            if not isinstance(data, dict):
                raise ValueError('not an object')
        except (ValueError, OSError) as exc:
            data = {}
            problems.append(f'config.json is unreadable ({exc}); using defaults')
        for key, value in data.items():
            if key not in DEFAULTS:
                continue
            if VALIDATORS[key](value):
                cfg[key] = value
            else:
                problems.append(f'config.json: bad value for {key}; using the default')
    cfg['configured'] = f.exists()
    if problems:
        cfg['config_problems'] = problems
    return cfg


def save_config(cfg):
    cfg = {k: v for k, v in cfg.items() if k in DEFAULTS}
    write_atomic(home() / 'config.json', json.dumps(cfg, indent=2) + '\n')


def free_bytes(path='/'):
    return plat.free_bytes(path)


def gb(n):
    return round(n / 1e9, 1)


def du_bytes(path):
    """Size on disk (du on macOS and Linux; a walk that never follows a junction on Windows)."""
    return plat.dir_size(path)


def now():
    return time.time()


def emit(obj):
    print(json.dumps(obj, indent=2, default=str))
