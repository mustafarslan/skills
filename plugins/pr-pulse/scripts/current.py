"""Keep every part of pr-pulse on the one installed version.

Three copies of pr-pulse can exist at once: the plugin folder Claude Code installed, the
folder an already-running session loaded (Claude Code pins it until /reload-plugins), and
the service's own copy (~/.claude/pr-pulse/app) that the daemon runs. They drifted apart
before: the daemon kept running old code after an update, and old sessions kept old hooks.

- `ensure_app()` copies the installed plugin over the service's copy whenever their CONTENT
  differs, the same version or not (the daemon calls it every tick, hooks call it too).
- `forward()` makes a script run from any loaded copy hand over to the service's copy, so a
  session that loaded an older pr-pulse still runs the current hooks and CLI.
- The handed-over call carries the folder the session loaded, so the service can tell which
  sessions still need /reload-plugins (for new commands, skills and hook matchers).

Stdlib only and fast: it runs before every pr-pulse hook.
"""
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

HOME = Path(os.environ.get("PR_PULSE_HOME", str(Path.home() / ".claude" / "pr-pulse")))
APP = HOME / "app"
INSTALLED = Path(os.environ.get("PR_PULSE_INSTALLED_JSON",
                                str(Path.home() / ".claude" / "plugins" / "installed_plugins.json")))
CACHE = Path.home() / ".claude" / "plugins" / "cache"
# .in_use: Claude Code writes .in_use/<pid> into a plugin folder for every session that loads it;
# counting it made each session start look like a new pr-pulse and restarted the service.
SKIP = {"tests", "__pycache__", ".DS_Store", "plan.md", ".source", ".fingerprint", ".in_use"}
FORWARDED = "PR_PULSE_FORWARDED"
LOADED_FROM = "PR_PULSE_LOADED_FROM"


def plugin_version(root):
    try:
        return json.loads((Path(root) / ".claude-plugin" / "plugin.json").read_text()).get("version", "")
    except (OSError, ValueError):
        return ""


def fingerprint(root):
    """sha256 of every shipped file (path + bytes). Runtime files never count, so an unchanged
    plugin is never re-copied."""
    root = Path(root)
    h = hashlib.sha256()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP)
        for name in sorted(filenames):
            if name in SKIP or name.endswith(".pyc"):
                continue
            p = Path(dirpath) / name
            h.update(str(p.relative_to(root)).encode() + b"\0")
            try:
                h.update(p.read_bytes())
            except OSError:
                pass
            h.update(b"\0")
    return h.hexdigest()


def installed_root():
    """The folder Claude Code says is installed (installed_plugins.json), else the newest
    pr-pulse in the plugin cache. Never the service's own copy."""
    try:
        data = json.loads(INSTALLED.read_text()).get("plugins", {})
        for key, entries in data.items():
            if key.split("@")[0] != "pr-pulse":
                continue
            for e in sorted(entries or [], key=lambda e: e.get("scope") != "user"):
                p = Path(e.get("installPath", ""))
                if (p / "scripts" / "pr-pulse").exists():
                    return p
    except (OSError, ValueError, AttributeError):
        pass
    best = None
    for pj in CACHE.glob("*/pr-pulse/*/.claude-plugin/plugin.json"):
        root = pj.parent.parent
        if best is None or _vkey(plugin_version(root)) > _vkey(plugin_version(best)):
            best = root
    return best


def _vkey(v):
    try:
        return tuple(int(x) for x in v.split("."))
    except ValueError:
        return ()


def app_fingerprint():
    try:
        return (APP / ".fingerprint").read_text().strip()
    except OSError:
        return fingerprint(APP) if APP.exists() else ""


VERSIONS = HOME / "app.versions"   # each synced copy lives here; APP is a symlink to one


def _verify(root, fp):
    return (root / "scripts" / "pr-pulsed.py").exists() and fingerprint(root) == fp


def sync(src):
    """Make APP the content of src. Safe to run from many processes at once: it takes a lock,
    re-checks inside it, builds a private copy, verifies it, and switches the APP symlink in
    one atomic step, so APP is never missing or half-copied. Returns the version now in APP."""
    import fcntl
    src = Path(src)
    if APP.exists() and src.resolve() == APP.resolve():
        return plugin_version(APP)
    fp = fingerprint(src)
    HOME.mkdir(parents=True, exist_ok=True)
    with open(HOME / "app.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if APP.exists() and app_fingerprint() == fp and _verify(APP, fp):
            return plugin_version(APP)            # another process just did it
        VERSIONS.mkdir(exist_ok=True)
        dest = VERSIONS / fp[:16]
        if not _verify(dest, fp):
            tmp = VERSIONS / f".tmp.{os.getpid()}"
            if tmp.exists():
                shutil.rmtree(tmp)
            shutil.copytree(src, tmp, ignore=lambda d, names: [n for n in names if n in SKIP])
            if fingerprint(tmp) != fp:
                shutil.rmtree(tmp, ignore_errors=True)
                raise RuntimeError(f"copy of {src} changed while copying; not switched")
            (tmp / ".source").write_text(f"{src}\n")
            (tmp / ".fingerprint").write_text(fp + "\n")
            if dest.exists():
                shutil.rmtree(dest)
            tmp.rename(dest)
        link = HOME / f".app.link.{os.getpid()}"
        if link.is_symlink() or link.exists():
            link.unlink()
        link.symlink_to(dest)
        if APP.exists() and not APP.is_symlink():  # the folder older versions used: once
            old = HOME / f".app.old.{os.getpid()}"
            APP.rename(old)
            os.replace(link, APP)
            shutil.rmtree(old, ignore_errors=True)
        else:
            os.replace(link, APP)                  # atomic: readers see old or new, never neither
        # keep the newest two copies: a long-running watcher may still read the previous one
        keep = {dest.name}
        others = sorted((p for p in VERSIONS.iterdir() if p.is_dir() and not p.name.startswith(".")
                         and p.name not in keep), key=lambda p: p.stat().st_mtime, reverse=True)
        for p in others[1:]:
            shutil.rmtree(p, ignore_errors=True)
    return plugin_version(APP)


def ensure_app(verify=False):
    """If the service is set up and its copy differs in content from the installed plugin,
    replace it. verify=True also re-reads the copy itself instead of trusting its stamp (the
    daemon does this now and then, so a damaged copy heals). Returns the version copied, or None."""
    if not (APP / "scripts" / "pr-pulsed.py").exists():
        return None   # no service here: nothing to keep current
    src = installed_root()
    if not src or not src.exists() or src.resolve() == APP.resolve():
        return None
    want = fingerprint(src)
    have = fingerprint(APP) if verify else app_fingerprint()
    if want == have:
        return None
    return sync(src)


def forward(script_file, argv=None):
    """Called first thing by a Python entry point. From any copy other than the service's
    own, bring the service's copy up to date and run the same script there instead.
    Returns only when this copy should run itself (no service, or already the app)."""
    if os.environ.get(FORWARDED):
        return
    here = Path(script_file).resolve().parent.parent
    target = APP / "scripts" / Path(script_file).name
    if not target.exists() or here == APP.resolve():
        return
    try:
        ensure_app()
    except Exception:   # noqa: BLE001 - a failed sync must never break a hook or a command
        pass
    if not target.exists():
        return          # the service's copy is unusable: run this copy rather than fail
    os.environ[FORWARDED] = "1"
    os.environ.setdefault(LOADED_FROM, str(here))
    sys.stdout.flush()
    os.execv(sys.executable, [sys.executable, str(target)] + list(sys.argv[1:] if argv is None else argv))


def stale_sessions(con, notify=None, installed=None):
    """Live sessions that loaded an older pr-pulse folder than the installed one. Their hooks
    and CLI already run the current copy (current.forward), but new commands, skills and hook
    matchers only arrive with /reload-plugins. Notifies once per session and folder."""
    installed = installed if installed is not None else installed_root()
    if not installed:
        return []
    inst = str(Path(installed).resolve())
    out = []
    # Only the user's own sessions: pr-pulse's background workers are short-lived and stopped when
    # their job ends; the user never opened them and can't reload them (a notice named one, 11-13).
    for r in con.execute("SELECT l.sid, l.root, l.notified_at, s.name FROM loaded l JOIN sessions s ON "
                         "s.sid=l.sid WHERE s.status != 'gone' AND COALESCE(s.spawned, 0) = 0").fetchall():
        try:
            same = str(Path(r["root"]).resolve()) == inst
        except OSError:
            same = False
        if same:
            continue
        v = plugin_version(r["root"]) or "an older version"
        out.append((r["name"] or r["sid"][:8], v))
        if notify and not r["notified_at"]:
            notify(f"Session {r['name'] or r['sid'][:8]} still has pr-pulse {v} loaded "
                   f"(installed: {plugin_version(installed)}). Run /reload-plugins there.")
            con.execute("UPDATE loaded SET notified_at=? WHERE sid=?", (__import__("time").time(), r["sid"]))
    return out


def main(argv):
    """`current.py ensure` (used by the bash hooks): sync, print the version if it changed."""
    if argv[:1] == ["ensure"]:
        v = ensure_app()
        if v:
            print(v)
        return 0
    if argv[:1] == ["fingerprint"] and len(argv) > 1:
        print(fingerprint(argv[1]))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
