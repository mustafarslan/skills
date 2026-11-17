"""pr-pulse core: talk to `claude agents`, git and gh, and keep the store in sync.

Every external call goes through `run()`, so tests swap it for a fake.
"""
import json
import re
import subprocess
import time
from pathlib import Path

import db

SLUG_RE = re.compile(r"github\.com[:/]([^/\s]+)/([^/\s]+?)(?:\.git)?/?$")
PR_URL_RE = re.compile(r"https://github\.com/([^/\s]+)/([^/\s]+)/pull/(\d+)")


def run(args, cwd=None, timeout=30):
    """Run a command, return stdout or None on any failure. Never raises."""
    try:
        p = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    return p.stdout if p.returncode == 0 else None


# ---- sessions -----------------------------------------------------------------------

def list_sessions():
    out = run(["claude", "agents", "--json"], timeout=20)
    if not out:
        return None   # unknown, not "no sessions": callers must not mark everything gone
    try:
        data = json.loads(out)
    except ValueError:
        return None
    return data if isinstance(data, list) else None


_repo_cache = {}


def repo_of(cwd):
    """(main worktree root, owner/name, branch) for a directory, or (None, None, None)."""
    if not cwd:
        return None, None, None
    if cwd in _repo_cache and _repo_cache[cwd][0] > time.time() - 300:
        return _repo_cache[cwd][1]
    res = (None, None, None)
    common = run(["git", "-C", cwd, "rev-parse", "--path-format=absolute", "--git-common-dir"])
    if common:
        root = common.strip()
        root = root[:-5] if root.endswith("/.git") else root
        remote = run(["git", "-C", cwd, "remote", "get-url", "origin"]) or ""
        m = SLUG_RE.search(remote.strip())
        branch = (run(["git", "-C", cwd, "branch", "--show-current"]) or "").strip()
        if m:
            res = (root, f"{m.group(1)}/{m.group(2)}", branch)
    _repo_cache[cwd] = (time.time(), res)
    return res


def sync_sessions(con, sessions):
    """Upsert live sessions; mark the ones that disappeared as gone."""
    now = time.time()
    live = set()
    for s in sessions:
        sid = s.get("sessionId")
        if not sid:
            continue
        live.add(sid)
        _, slug, branch = repo_of(s.get("cwd"))
        status = s.get("status") or "unknown"
        con.execute(
            "INSERT INTO sessions(sid, name, cwd, slug, branch, kind, status, seen_at) "
            "VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(sid) DO UPDATE SET name=excluded.name, "
            "cwd=excluded.cwd, slug=excluded.slug, branch=excluded.branch, kind=excluded.kind, "
            "status=excluded.status, seen_at=excluded.seen_at",
            (sid, s.get("name"), s.get("cwd"), slug, branch, s.get("kind"), status, now))
    for row in con.execute("SELECT sid FROM sessions WHERE status != 'gone'").fetchall():
        if row["sid"] not in live:
            con.execute("UPDATE sessions SET status='gone' WHERE sid=?", (row["sid"],))
    return live


def suggest_mapping(con):
    """Group live sessions by repo and pick a suggested PR session for each.

    Preference: already registered > name mentions "pr" or "review" > idle > most recently seen.
    Returns [{slug, root, sessions:[...], suggested: sid|None, mapped: bool}].
    """
    rows = con.execute(
        "SELECT * FROM sessions WHERE status != 'gone' AND slug IS NOT NULL").fetchall()
    mapped = {r["slug"]: r for r in con.execute("SELECT * FROM repos").fetchall()}
    by_slug = {}
    for r in rows:
        by_slug.setdefault(r["slug"], []).append(dict(r))
    out = []
    for slug in sorted(set(by_slug) | set(mapped)):
        ss = by_slug.get(slug, [])

        def score(s):
            name = (s.get("name") or "").lower()
            named = 2 if "review" in name else (1 if re.search(r"(^|[-_ ])pr([-_ ]|$)", name) else 0)
            return (s["registered"], named, int(s["status"] == "idle"), s["seen_at"] or 0)
        ss.sort(key=score, reverse=True)
        root = mapped[slug]["path"] if slug in mapped else None
        if root is None and ss:
            root = repo_of(ss[0]["cwd"])[0]
        out.append({"slug": slug, "root": root, "sessions": ss,
                    "suggested": ss[0]["sid"] if ss else None, "mapped": slug in mapped})
    return out


# ---- GitHub -------------------------------------------------------------------------

PR_FIELDS = ("number,url,title,author,state,isDraft,headRefOid,reviewDecision,"
             "reviews,comments,statusCheckRollup")


def ci_state(rollup):
    """red | green | pending | none — same rule as ~/.claude/hooks/pr-watch.sh."""
    states = [(c.get("conclusion") or c.get("state") or "") for c in (rollup or [])]
    if not states:
        return "none"
    if any(s in ("FAILURE", "ERROR", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED") for s in states):
        return "red"
    if all(s in ("SUCCESS", "NEUTRAL", "SKIPPED") for s in states):
        return "green"
    return "pending"


def own_open_prs(slug):
    out = run(["gh", "pr", "list", "--repo", slug, "--author", "@me", "--state", "open",
               "--json", PR_FIELDS, "--limit", "50"], timeout=45)
    if out is None:
        return None
    try:
        return json.loads(out)
    except ValueError:
        return None


def upsert_pr(con, slug, pr, kind):
    """Store one PR snapshot. Returns (old_row or None, new_row dict)."""
    url = pr["url"]
    old = con.execute("SELECT * FROM prs WHERE url=?", (url,)).fetchone()
    new = {
        "url": url, "slug": slug, "n": pr["number"], "kind": kind,
        "title": pr.get("title"), "author": (pr.get("author") or {}).get("login"),
        "state": pr.get("state"), "is_draft": int(bool(pr.get("isDraft"))),
        "head_sha": pr.get("headRefOid"), "decision": pr.get("reviewDecision") or "",
        "ci": ci_state(pr.get("statusCheckRollup")),
        "reviews": len(pr.get("reviews") or []), "comments": len(pr.get("comments") or []),
    }
    con.execute(
        "INSERT INTO prs(url, slug, n, kind, title, author, state, is_draft, head_sha, decision, "
        "ci, snapshot, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(url) DO UPDATE SET "
        "title=excluded.title, state=excluded.state, is_draft=excluded.is_draft, "
        "merge_ok_sha=CASE WHEN prs.head_sha IS NOT excluded.head_sha THEN NULL ELSE prs.merge_ok_sha END, "
        "head_sha=excluded.head_sha, decision=excluded.decision, ci=excluded.ci, "
        "snapshot=excluded.snapshot, updated_at=excluded.updated_at",
        (url, slug, new["n"], kind, new["title"], new["author"], new["state"], new["is_draft"],
         new["head_sha"], new["decision"], new["ci"], json.dumps(pr), time.time()))
    return (dict(old) if old else None), new


def describe_change(old, new):
    """Short human list of what changed between two snapshots (empty when nothing did)."""
    if old is None:
        return ["tracked"]
    snap = json.loads(old["snapshot"] or "{}")
    changes = []
    if old["head_sha"] != new["head_sha"]:
        changes.append("new push")
    if (old["decision"] or "") != new["decision"]:
        changes.append(f"decision {old['decision'] or '-'} -> {new['decision'] or '-'}")
    if old["ci"] != new["ci"]:
        changes.append(f"CI {old['ci']} -> {new['ci']}")
    if len(snap.get("reviews") or []) != new["reviews"]:
        changes.append("new review")
    if len(snap.get("comments") or []) != new["comments"]:
        changes.append("new comment")
    return changes


def my_name(cfg):
    """The user's first name for prompts and verdicts: config my_name, else git user.name."""
    name = (cfg.get("my_name") or "").strip()
    if not name:
        full = (run(["git", "config", "--global", "--get", "user.name"]) or "").strip()
        name = full.split()[0] if full else ""
    return name or "the user"


SKILL_FOR = {"review": "pr-review", "re-review": "pr-review", "feedback": "pr-feedback",
             "merge": "pr-merge", "merge-check": None}


def skill_source(skill, repo_root=None):
    """Where a skill comes from for jobs in this repo: 'personal', 'plugin', 'repo', or None.

    The user's own version wins; otherwise the repo's (Claude Code loads a repo's
    .claude/skills in every session and worktree inside it)."""
    from pathlib import Path as _P
    home = _P.home() / ".claude"
    if (home / "skills" / skill / "SKILL.md").exists():
        return "personal"
    plugins = home / "plugins"
    if plugins.exists() and any(f.parent.name == skill for f in plugins.rglob("SKILL.md")):
        return "plugin"
    if repo_root:
        root = _P(repo_root)
        if (root / ".claude" / "skills" / skill / "SKILL.md").exists():
            return "repo"
        if run(["git", "-C", str(root), "cat-file", "-e", f"origin/HEAD:.claude/skills/{skill}/SKILL.md"]) is not None:
            return "repo"
    return None


ICON = Path(__file__).resolve().parent.parent / "assets" / "notification-256.png"


def icon_args():
    """alerter flags that put the pr-pulse logo on a notification (nothing if the file is missing)."""
    return ["--app-icon", str(ICON)] if ICON.exists() else []


def use_alerter():
    """alerter banners (the default) unless config "use_alerter" is false or alerter is missing;
    then macOS dialogs with real buttons. Banners stuck on screen several times on 2026-11-12 (cause
    not found yet); "use_alerter": false is the way out if that happens to someone."""
    import shutil
    try:
        import db
        on = bool(db.load_config().get("use_alerter", True))
    except (SystemExit, Exception):   # a bad config must never break a notification
        on = True
    return on and shutil.which("alerter") is not None
