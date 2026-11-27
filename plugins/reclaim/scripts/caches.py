"""Developer caches: npm, pnpm, yarn, pip, uv, NuGet, Cargo, Gradle, Maven, Go, Xcode, and folders you list.

Each cache is found at its usual place for this system (or where its own environment variable points),
sized, and cleared one of two ways, which the scan says:

  all     everything goes, through the tool's own command when it is installed (npm cache clean --force,
          pip cache purge, go clean -cache, dotnet nuget locals all --clear, ...), else the folder's contents
          through the shared delete routine. The next build downloads what it needs again.
  by age  only what has not changed for N days (cache_days): the tool's own prune (uv cache prune, pnpm
          store prune), or entries whose newest file is older than N days (Gradle, Maven, your folders).

A cache is skipped while any process of its tool runs: an agent may be building with it. Nothing is
cleared without the user's yes, per cache, in /reclaim.
"""
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import plat
from common import run

MAC = sys.platform == 'darwin'


def _home():
    return Path.home()


def _local():
    """%LOCALAPPDATA% on Windows, ~/Library/Caches on macOS, ~/.cache elsewhere."""
    if plat.WINDOWS:
        return Path(os.environ.get('LOCALAPPDATA') or (_home() / 'AppData' / 'Local'))
    if MAC:
        return _home() / 'Library' / 'Caches'
    return Path(os.environ.get('XDG_CACHE_HOME') or (_home() / '.cache'))


def _env_path(var, default):
    v = os.environ.get(var)
    return Path(v) if v else default


def _known():
    """The caches this system can have: id -> spec. Paths are candidates; only existing ones count."""
    h, local = _home(), _local()
    w, m = plat.WINDOWS, MAC
    cargo = _env_path('CARGO_HOME', h / '.cargo')
    gradle = _env_path('GRADLE_USER_HOME', h / '.gradle')
    specs = {
        'npm': {'label': 'npm cache', 'tools': ['npm', 'npx', 'npm-cli', 'npx-cli'],
                'paths': [local / 'npm-cache' / '_cacache'] if w else [h / '.npm' / '_cacache'],
                'how': 'all', 'cmd': ['npm', 'cache', 'clean', '--force']},
        'pnpm': {'label': 'pnpm store', 'tools': ['pnpm', 'pnpx'],
                 'paths': [local / 'pnpm' / 'store'] if w else
                          [h / 'Library' / 'pnpm' / 'store'] if m else [h / '.local' / 'share' / 'pnpm' / 'store'],
                 'how': 'by age', 'cmd': ['pnpm', 'store', 'prune'],
                 'note': 'pnpm store prune removes packages no project references'},
        'yarn': {'label': 'yarn cache', 'tools': ['yarn', 'yarnpkg'],
                 'paths': ([local / 'Yarn' / 'Cache'] if w else [local / 'Yarn'] if m else [local / 'yarn'])
                          + [h / '.yarn' / 'berry' / 'cache'],
                 'how': 'all', 'cmd': ['yarn', 'cache', 'clean']},
        'pip': {'label': 'pip cache', 'tools': ['pip', 'pip3'],
                'paths': [local / 'pip' / 'Cache'] if w else [local / 'pip'],
                'how': 'all', 'cmd': ['pip', 'cache', 'purge']},
        'uv': {'label': 'uv cache', 'tools': ['uv', 'uvx'],
               'paths': [_env_path('UV_CACHE_DIR', local / 'uv' / 'cache' if w else
                                   (h / '.cache' / 'uv'))],
               'how': 'by age', 'cmd': ['uv', 'cache', 'prune'], 'note': 'uv cache prune removes unused entries'},
        'nuget': {'label': 'NuGet packages and HTTP cache', 'tools': ['dotnet', 'nuget', 'msbuild'],
                  'paths': [_env_path('NUGET_PACKAGES', h / '.nuget' / 'packages'),
                            local / 'NuGet' / 'v3-cache' if w else h / '.local' / 'share' / 'NuGet' / 'v3-cache'],
                  'how': 'all', 'cmd': ['dotnet', 'nuget', 'locals', 'all', '--clear']},
        'cargo': {'label': 'Cargo downloads (registry and git checkouts)', 'tools': ['cargo', 'rustc'],
                  'paths': [cargo / 'registry' / 'cache', cargo / 'registry' / 'src', cargo / 'git' / 'checkouts'],
                  'how': 'all', 'cmd': None},
        'gradle': {'label': 'Gradle dependency and build cache', 'tools': ['gradle', 'gradlew'],
                   'cmd_has': ['GradleDaemon', 'GradleWrapperMain', 'GradleMain'],
                   'paths': [gradle / 'caches' / 'modules-2' / 'files-2.1', gradle / 'caches' / 'build-cache-1'],
                   'how': 'by age', 'cmd': None, 'entries': 'gradle'},
        'maven': {'label': 'Maven repository', 'tools': ['mvn', 'mvnw'], 'cmd_has': ['plexus-classworlds'],
                  'paths': [h / '.m2' / 'repository'], 'how': 'by age', 'cmd': None, 'entries': 'maven'},
        'go': {'label': 'Go build cache', 'tools': ['go'],
               'paths': [_env_path('GOCACHE', local / 'go-build')], 'how': 'all', 'cmd': ['go', 'clean', '-cache']},
    }
    if m:
        specs['xcode'] = {'label': 'Xcode DerivedData', 'tools': ['xcodebuild', 'Xcode'],
                          'paths': [h / 'Library' / 'Developer' / 'Xcode' / 'DerivedData'], 'how': 'all',
                          'cmd': None}
        specs['simulators'] = {'label': 'Unavailable iOS simulators', 'tools': ['Simulator', 'xcodebuild'],
                               'paths': [], 'how': 'all',
                               'cmd': ['xcrun', 'simctl', 'delete', 'unavailable'],
                               'note': 'simulators for runtimes no longer installed'}
    return specs


def specs(cfg):
    out = _known()
    for i, d in enumerate(cfg.get('cache_dirs') or []):
        out[f'dir{i + 1}'] = {'label': d, 'tools': [], 'paths': [Path(os.path.expanduser(d))], 'how': 'by age',
                              'cmd': None, 'entries': 'children'}
    return out


def _newest(path):
    """Newest mtime of anything under path (path itself for a file); links count as themselves."""
    try:
        newest = os.lstat(path).st_mtime
    except OSError:
        return None
    if os.path.isdir(path) and not plat.is_link_or_junction(path):
        for root, dirs, files in plat.walk(path):
            for n in dirs + files:
                try:
                    newest = max(newest, os.lstat(os.path.join(root, n)).st_mtime)
                except OSError:
                    continue
    return newest


def _entries(spec, path):
    """The units an age-based clear removes whole."""
    kind = spec.get('entries')
    if kind == 'maven':  # a version folder: it holds a .pom
        out = []
        for root, dirs, files in plat.walk(str(path)):
            if any(f.endswith('.pom') for f in files):
                out.append(root)
                dirs[:] = []
        return out
    if kind == 'gradle' and path.name == 'files-2.1':  # group/module/version
        out = []
        for g in _dirs(path):
            for mod in _dirs(g):
                out.extend(_dirs(mod))
        return out
    try:
        return [str(p) for p in path.iterdir()]
    except OSError:
        return []


def _dirs(p):
    try:
        return [c for c in Path(p).iterdir() if c.is_dir() and not plat.is_link_or_junction(str(c))]
    except OSError:
        return []


def _busy(spec, procs):
    found = plat.running(spec['tools'], procs) if spec['tools'] else []
    for needle in spec.get('cmd_has', []):
        found += [(r['pid'], r.get('name') or '') for r in procs if needle in (r.get('cmdline') or '')]
    return found


def _info(cid, spec, procs, cutoff):
    paths = [p for p in spec['paths'] if p.is_dir() and not plat.is_link_or_junction(str(p))]
    if not paths and not (cid == 'simulators' and plat.which('xcrun')):
        return None
    row = {'id': cid, 'label': spec['label'], 'how': spec['how'], 'paths': [str(p) for p in paths],
           'size': sum(plat.dir_size(p) for p in paths)}
    if spec.get('note'):
        row['note'] = spec['note']
    if spec['how'] == 'by age' and not (spec.get('cmd') and plat.which(spec['cmd'][0])):
        old = [e for p in paths for e in _entries(spec, p) if (_newest(e) or cutoff) < cutoff]
        row['old_entries'] = len(old)
    row['clears_with'] = ' '.join(spec['cmd']) if spec.get('cmd') and plat.which(spec['cmd'][0]) else \
        ('delete entries older than the cutoff' if spec['how'] == 'by age' else 'delete the folder contents')
    busy = _busy(spec, procs)
    if busy:
        row['busy'] = sorted({n for _, n in busy})[:5]
    return row


def scan(cfg, days=None):
    days = cfg.get('cache_days', 30) if days is None else days
    cutoff = time.time() - days * 86400
    procs = plat.processes()
    all_specs = specs(cfg)
    with ThreadPoolExecutor(max_workers=6) as pool:
        rows = [r for r in pool.map(lambda kv: _info(kv[0], kv[1], procs, cutoff), all_specs.items()) if r]
    return {'days': days, 'caches': sorted(rows, key=lambda r: -r['size'])}


def clear(cfg, ids, days=None):
    """Clear the named caches, each re-checked first: skipped while its tool runs."""
    days = cfg.get('cache_days', 30) if days is None else days
    cutoff = time.time() - days * 86400
    all_specs = specs(cfg)
    procs = plat.processes()
    results = []
    for cid in ids:
        spec = all_specs.get(cid)
        if not spec:
            results.append({'id': cid, 'result': 'skipped', 'why': 'not a cache reclaim knows'})
            continue
        busy = _busy(spec, procs)
        if busy:
            results.append({'id': cid, 'result': 'skipped',
                            'why': 'in use by ' + ', '.join(sorted({n for _, n in busy})[:3])})
            continue
        paths = [p for p in spec['paths'] if p.is_dir() and not plat.is_link_or_junction(str(p))]
        before = sum(plat.dir_size(p) for p in paths)
        row = {'id': cid}
        if spec.get('cmd') and plat.which(spec['cmd'][0]):
            rc, out, err = run(spec['cmd'], timeout=1800)
            row.update(result='cleared' if rc == 0 else 'failed', how=' '.join(spec['cmd']),
                       why='' if rc == 0 else (err or out).strip()[-500:])
        elif spec['how'] == 'by age':
            gone, failed = 0, []
            for p in paths:
                for e in _entries(spec, p):
                    if (_newest(e) or cutoff) < cutoff:
                        r = plat.delete_tree(e)
                        gone += r['ok']
                        if not r['ok']:
                            failed.append(r)
            row.update(result='cleared' if not failed else 'partly', how=f'deleted {gone} entries older than '
                       f'{days:g} days', why='; '.join(f['error'] for f in failed[:3]))
        else:
            failed = []
            for p in paths:
                for e in list(p.iterdir()):
                    r = plat.delete_tree(e)
                    if not r['ok']:
                        failed.append(r)
            row.update(result='cleared' if not failed else 'partly', how='deleted the folder contents',
                       why='; '.join(f['error'] for f in failed[:3]))
        row['freed'] = max(0, before - sum(plat.dir_size(p) for p in paths if p.is_dir()))
        results.append(row)
    return {'results': results}
