"""pr-pulse store: one SQLite file shared by the daemon, the CLI and the hooks.

Python 3.9 stdlib only. Every connection runs in WAL mode with a busy timeout, so the
daemon and a session's CLI call can write at the same time without "database is locked".
"""
import json
import os
import sqlite3
import time
from pathlib import Path

HOME = Path(os.environ.get("PR_PULSE_HOME", str(Path.home() / ".claude" / "pr-pulse")))
DB_PATH = HOME / "pulse.db"
CONFIG_PATH = Path(os.environ.get(
    "PR_PULSE_CONFIG", str(Path.home() / ".config" / "pr-pulse" / "config.json")))

# Job statuses that hold a slot. The unique index below allows one active job per
# (pr_url, action), so the same PR can never be dispatched twice for the same thing.
ACTIVE = ("queued", "claimed", "delivered", "waiting_user")

DEFAULT_CONFIG = {
    "pool_size": 3,            # max PR jobs running at once (claimed/delivered)
    "pool_pull": 1,            # untagged Slack PRs pulled per free slot round (max 2)
    "feedback_rounds": 2,      # automatic /pr-feedback rounds with human activity, then hold
    "bot_rounds": 2,           # extra rounds started by review bots alone (after a human reviewed)
    "review_bots": ["coderabbitai", "claude", "copilot-pull-request-reviewer", "copilot",
                    "chatgpt-codex-connector", "codex"],
    "stale_minutes": 45,       # delivered job with no heartbeat -> re-queue once
    "stall_minutes": 120,      # ...even when its session looks busy: tell the user, free the slot
    "announce_nudge_minutes": 10,   # a PR opened but not announced after this -> one notification
    "worker_idle_minutes": 10,  # a finished worker, idle with no job this long, is stopped
    "use_alerter": True,        # true: answerable alerter banners; false: macOS dialogs with buttons
    # How review verdicts appear in the PR's Slack thread. "reply": a thread reply, "<name>'s review:
    # approved @author" (default). "emoji": a reaction instead, on the author's share message and on
    # the author's own re-review request ("fixed @you"): ✅ approved, ⚠️ changes requested, 💬
    # comments, ♻️ while a re-review is under way. Needs the reactions:write scope.
    "verdict_style": "reply",
    # Who posts announcements, verdict replies and reactions in Slack. "bot": the shared pr-pulse
    # app. "user": you, with your own Slack user token (pr-pulse secret set user-token). Reading
    # channels always uses the bot. With "user" and no working user token, nothing is posted as
    # the bot instead: you get a notification.
    "post_as": "bot",
    "tick_seconds": 60,
    "rereview_on_push": True,      # re-review when the author pushes and replies after your requested changes
    "rereview_poll_seconds": 300,  # how often that GitHub search runs
    "retention_days": 30,
    "notify_waiting_sessions": True,   # notify when ANY Claude session waits for you      # finished history older than this is deleted once a day
    # What a background worker may do without asking (the user: "pre-approve the routine").
    # Anything else - /pr-merge, gh pr merge, gh api graphql, installs - still asks; pr-pulse then
    # notifies "waiting for your approval — claude attach <name>".
    "worker_allowed_tools": [
        "Edit(./**)", "Write(./**)",
        "Bash(git status*)", "Bash(git diff*)", "Bash(git log*)", "Bash(git show*)",
        "Bash(git fetch*)", "Bash(git add*)", "Bash(git commit*)", "Bash(git rebase origin/*)",
        "Bash(git push)", "Bash(git push origin HEAD*)",
        "Bash(gh pr view*)", "Bash(gh pr diff*)", "Bash(gh pr checks*)", "Bash(gh pr list*)",
        "Bash(gh pr checkout*)", "Bash(gh pr edit*--add-reviewer*)", "Bash(gh pr comment*)",
        "Bash(gh pr review*)", "Bash(gh api repos/*/pulls/*/comments*)",
        "Bash(gh api repos/*/issues/*/comments*)", "Bash(gh api repos/*/pulls/*/reviews*)",
        "Bash(pr-pulse *)", "Bash(agy-ask *)",
        "Bash(npm test*)", "Bash(npm run test*)", "Bash(npm run lint*)", "Bash(npm run typecheck*)",
        "Bash(pnpm test*)", "Bash(pnpm run test*)", "Bash(pnpm run lint*)", "Bash(pnpm run typecheck*)",
        "Bash(pytest*)", "Bash(python -m pytest*)", "Bash(python3 -m pytest*)",
        "Bash(make test*)", "Bash(make lint*)", "Bash(go test*)",
    ],
    "worker_denied_tools": [
        "Bash(git push*--force*)", "Bash(git push*-f *)", "Bash(git push*+*)",
        "Bash(git reset --hard*)", "Bash(git clean*)", "Bash(gh repo*)", "Bash(rm -rf*)",
    ],   # denied = always refused. Merging is NOT here: it is simply not pre-approved, so it asks.
    "watch_channels": [],      # Slack channel ids read for shared PRs and re-review tags
    "verdict_channel": "",     # Slack channel id for review verdicts (falls back to thread)
    "github_to_slack": {},     # github login -> Slack user id
    "slack_user_id": "",       # the user's Slack user id
}

SCHEMA = [
    """CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS repos(
        path TEXT PRIMARY KEY,            -- main worktree root
        slug TEXT NOT NULL,               -- owner/name on GitHub
        announce INTEGER NOT NULL DEFAULT 0,
        pr_session TEXT,                  -- preferred registered session id for this repo
        added_at REAL NOT NULL)""",
    """CREATE INDEX IF NOT EXISTS repos_slug ON repos(slug)""",
    """CREATE TABLE IF NOT EXISTS sessions(
        sid TEXT PRIMARY KEY,
        name TEXT, cwd TEXT, slug TEXT, branch TEXT, kind TEXT,
        status TEXT,                      -- busy | idle | waiting | gone
        registered INTEGER NOT NULL DEFAULT 0,
        spawned INTEGER NOT NULL DEFAULT 0,   -- started by pr-pulse as a worker
        focus TEXT,                       -- JSON list of session names whose PRs it handles (none: general)
        seen_at REAL, registered_at REAL)""",
    """CREATE TABLE IF NOT EXISTS prs(
        url TEXT PRIMARY KEY,
        slug TEXT NOT NULL, n INTEGER NOT NULL,
        kind TEXT NOT NULL,               -- own | review
        title TEXT, author TEXT, state TEXT, is_draft INTEGER,
        head_sha TEXT, decision TEXT, ci TEXT,
        approved_sha TEXT, reviews_seen INTEGER NOT NULL DEFAULT 0,
        comments_seen INTEGER NOT NULL DEFAULT 0,
        feedback_rounds INTEGER NOT NULL DEFAULT 0,
        snapshot TEXT, updated_at REAL,
        merge_ok_sha TEXT,                -- head the user OK'd for merging after a moved head
        hold INTEGER NOT NULL DEFAULT 0,  -- 1 = over to the user: never auto-merge until released
        bots_seen INTEGER NOT NULL DEFAULT 0,   -- review-bot reviews+comments already handled
        bot_rounds INTEGER NOT NULL DEFAULT 0)  -- rounds started by bot activity alone""",
    """CREATE TABLE IF NOT EXISTS jobs(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        pr_url TEXT NOT NULL,
        action TEXT NOT NULL,             -- review | re-review | feedback | merge
        priority INTEGER NOT NULL,        -- lower runs first
        status TEXT NOT NULL DEFAULT 'queued',
        sid TEXT, note TEXT, attempts INTEGER NOT NULL DEFAULT 0,
        created_at REAL NOT NULL, updated_at REAL NOT NULL, heartbeat_at REAL,
        wt TEXT, head_sha TEXT)""",
    """CREATE UNIQUE INDEX IF NOT EXISTS jobs_one_active
        ON jobs(pr_url, action)
        WHERE status IN ('queued','claimed','delivered','waiting_user')""",
    """CREATE TABLE IF NOT EXISTS outbox(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id INTEGER, pr_url TEXT NOT NULL,
        kind TEXT NOT NULL,               -- review | reply | comment | decision
        draft TEXT NOT NULL,
        post_cmd TEXT,                    -- unused; kept for v1 stores
        status TEXT NOT NULL DEFAULT 'pending',   -- pending | ready | posted | dropped
        created_at REAL NOT NULL, posted_at REAL,
        lines TEXT,                       -- the user's own top lines, added in /pr-pulse:inbox
        target TEXT)""",
    """CREATE TABLE IF NOT EXISTS review_pool(
        pr_url TEXT PRIMARY KEY,
        channel TEXT, ts TEXT, sharer TEXT,
        shared_at REAL, status TEXT NOT NULL DEFAULT 'pool',  -- pool | pulled | gone
        last_check REAL, skip_reason TEXT)""",
    """CREATE TABLE IF NOT EXISTS slack_seen(channel TEXT, ts TEXT, PRIMARY KEY(channel, ts))""",
    """CREATE TABLE IF NOT EXISTS verdicts(
        pr_url TEXT, review_id TEXT, verdict TEXT, posted_at REAL,
        PRIMARY KEY(pr_url, review_id))""",
    """CREATE TABLE IF NOT EXISTS announced(url TEXT PRIMARY KEY, at TEXT)""",
    # Reactions pr-pulse added (verdict_style "emoji"), so a later round swaps only its own.
    """CREATE TABLE IF NOT EXISTS reactions(
        pr_url TEXT NOT NULL, channel TEXT NOT NULL, ts TEXT NOT NULL,
        kind TEXT NOT NULL,                -- share (the author's PR message) | rereview (their tag)
        emoji TEXT NOT NULL,
        at REAL NOT NULL,
        posted_as TEXT NOT NULL DEFAULT 'bot',   -- bot | user: only that identity can remove it
        PRIMARY KEY(channel, ts))""",
    """CREATE TABLE IF NOT EXISTS pr_origin(
        url TEXT PRIMARY KEY, sid TEXT NOT NULL,   -- the session that ran `gh pr create`
        at REAL)""",
    """CREATE TABLE IF NOT EXISTS loaded(
        sid TEXT PRIMARY KEY, root TEXT, seen_at REAL,   -- the plugin folder a session loaded
        notified_at REAL)""",
    """CREATE TABLE IF NOT EXISTS announcements(
        url TEXT PRIMARY KEY, opened_at REAL, sid TEXT, title TEXT,
        text TEXT,                              -- the announcement the session saved
        state TEXT NOT NULL DEFAULT 'open',     -- open | queued | posted | dropped | failed
        ts TEXT, channel TEXT,                  -- the Slack message, once the daemon posted it
        edit_text TEXT,                         -- a queued edit of the posted message
        posted_as TEXT NOT NULL DEFAULT 'bot',  -- bot | user: only that identity can edit it
        error TEXT, nudged_at REAL, updated_at REAL)""",
    """CREATE TABLE IF NOT EXISTS questions(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id INTEGER NOT NULL, sid TEXT,
        question TEXT NOT NULL,
        options TEXT NOT NULL DEFAULT '[]',     -- JSON list of choices
        allow_text INTEGER NOT NULL DEFAULT 0,  -- 1: the user may type their own answer
        status TEXT NOT NULL DEFAULT 'pending', -- pending | showing | answered | expired
        answer TEXT, answered_via TEXT,
        created_at REAL NOT NULL, shown_at REAL, answered_at REAL,
        summary TEXT,                           -- one line of context for the notification
        findings TEXT NOT NULL DEFAULT '[]',    -- [{severity, path, what, scope}]
        kind TEXT NOT NULL DEFAULT 'question',  -- question | draft (a parked draft shown as a notification)
        draft_id INTEGER, details TEXT)""",
    """CREATE TABLE IF NOT EXISTS events(
        id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL,
        kind TEXT NOT NULL, detail TEXT)""",
]
SCHEMA_VERSION = 11

# Step migrations for stores created by an older version: {to_version: [statements]}.
MIGRATIONS = {
    2: ["ALTER TABLE jobs ADD COLUMN wt TEXT", "ALTER TABLE jobs ADD COLUMN head_sha TEXT",
        "ALTER TABLE outbox ADD COLUMN lines TEXT", "ALTER TABLE outbox ADD COLUMN target TEXT",
        "ALTER TABLE prs ADD COLUMN merge_ok_sha TEXT",
        "ALTER TABLE prs ADD COLUMN hold INTEGER NOT NULL DEFAULT 0"],
    3: ["ALTER TABLE prs ADD COLUMN bots_seen INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE prs ADD COLUMN bot_rounds INTEGER NOT NULL DEFAULT 0"],
    4: [],   # the questions table comes from SCHEMA (CREATE TABLE IF NOT EXISTS)
    5: ["ALTER TABLE questions ADD COLUMN summary TEXT",
        "ALTER TABLE questions ADD COLUMN findings TEXT NOT NULL DEFAULT '[]'"],
    6: ["ALTER TABLE questions ADD COLUMN kind TEXT NOT NULL DEFAULT 'question'",
        "ALTER TABLE questions ADD COLUMN draft_id INTEGER",
        "ALTER TABLE questions ADD COLUMN details TEXT"],
    7: [],   # the announcements table comes from SCHEMA
    8: [],   # the loaded table comes from SCHEMA
    9: ["ALTER TABLE sessions ADD COLUMN focus TEXT",   # JSON list of session names it serves
        # PRs announced before 0.9.0 already know the session that opened them
        "INSERT OR IGNORE INTO pr_origin(url, sid, at) SELECT url, sid, opened_at FROM announcements "
        "WHERE COALESCE(sid, '') != ''"],
    10: [],  # the reactions table comes from SCHEMA
    11: ["ALTER TABLE reactions ADD COLUMN posted_as TEXT NOT NULL DEFAULT 'bot'",
         "ALTER TABLE announcements ADD COLUMN posted_as TEXT NOT NULL DEFAULT 'bot'"],
}


def connect(path=None):
    p = Path(path) if path else DB_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(p), timeout=10, isolation_level=None)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=10000")
    if con.execute("PRAGMA user_version").fetchone()[0] < SCHEMA_VERSION:
        migrate(con)
    return con


def migrate(con):
    con.execute("BEGIN IMMEDIATE")
    try:
        have = con.execute("PRAGMA user_version").fetchone()[0]
        fresh = con.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='jobs'").fetchone()[0] == 0
        for stmt in SCHEMA:
            con.execute(stmt)
        if not fresh:
            for v in range(have + 1, SCHEMA_VERSION + 1):
                for stmt in MIGRATIONS.get(v, []):
                    try:
                        con.execute(stmt)
                    except sqlite3.OperationalError as e:
                        if "duplicate column" not in str(e):
                            raise   # an ADD COLUMN that already ran (or came from SCHEMA) is fine
        _import_posted_tsv(con)
        con.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise


def _import_posted_tsv(con):
    """v1 kept announced PRs in posted.tsv; carry them over once."""
    tsv = HOME / "posted.tsv"
    if not tsv.exists():
        return
    for line in tsv.read_text(errors="ignore").splitlines():
        parts = line.split("\t")
        if parts and parts[0].startswith("https://"):
            con.execute("INSERT OR IGNORE INTO announced(url, at) VALUES(?, ?)",
                        (parts[0], parts[1] if len(parts) > 1 else ""))


def event(con, kind, detail=""):
    if not isinstance(detail, str):
        detail = json.dumps(detail, sort_keys=True)
    con.execute("INSERT INTO events(ts, kind, detail) VALUES(?, ?, ?)", (time.time(), kind, detail))


def get_setting(con, key, default=None):
    row = con.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row[0] if row else default


def set_setting(con, key, value):
    con.execute("INSERT INTO settings(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))


TEAM_FILE = Path(__file__).resolve().parent.parent / "team.json"
TEAM_KEYS = ("announce_channel",)   # reading channels are opt-in per person (init step 5)


def load_team():
    """The team's shared Slack app and channels (team.json next to the plugin), or {}."""
    try:
        return json.loads(TEAM_FILE.read_text()).get("slack") or {}
    except (OSError, ValueError):
        return {}


def load_config(path=None):
    """Defaults, then the team's channels (team.json), then the user's own config."""
    cfg = dict(DEFAULT_CONFIG)
    team = load_team()
    for k in TEAM_KEYS:
        if team.get(k):
            cfg[k] = team[k]
    cfg["github_to_slack"] = dict(team.get("github_to_slack") or {})
    p = Path(path) if path else CONFIG_PATH
    if p.exists():
        try:
            mine = json.loads(p.read_text())
            team_map = cfg["github_to_slack"]
            cfg.update(mine)
            cfg["github_to_slack"] = {**team_map, **(mine.get("github_to_slack") or {})}
        except ValueError as e:
            raise SystemExit(f"pr-pulse: {p} is not valid JSON: {e}")
    cfg["pool_pull"] = max(1, min(2, int(cfg["pool_pull"])))
    return cfg


# ---- jobs ---------------------------------------------------------------------------

def enqueue(con, pr_url, action, priority, note="", head_sha=None, once_per_head=False):
    """Queue a job unless one is already active for (pr_url, action). Returns id or None.

    once_per_head: also refuse when a job for (pr_url, action) already finished or failed at
    this head commit, so a failed merge or a finished review is not retried every tick.
    """
    now = time.time()
    if once_per_head and head_sha and con.execute(
            "SELECT 1 FROM jobs WHERE pr_url=? AND action=? AND head_sha=? "
            "AND status IN ('done','failed','cancelled')", (pr_url, action, head_sha)).fetchone():
        return None
    try:
        cur = con.execute(
            "INSERT INTO jobs(pr_url, action, priority, note, head_sha, created_at, updated_at) "
            "VALUES(?, ?, ?, ?, ?, ?, ?)", (pr_url, action, priority, note, head_sha, now, now))
    except sqlite3.IntegrityError:
        return None
    event(con, "job.queued", {"id": cur.lastrowid, "pr": pr_url, "action": action})
    return cur.lastrowid


def claim(con, job_id, sid):
    """Atomically move a queued job to claimed. True only for the one caller that wins."""
    cur = con.execute(
        "UPDATE jobs SET status='claimed', sid=?, attempts=attempts+1, updated_at=?, "
        "heartbeat_at=? WHERE id=? AND status='queued'", (sid, time.time(), time.time(), job_id))
    return cur.rowcount == 1


def set_job(con, job_id, status, note=None):
    if status not in ACTIVE + ("done", "failed", "cancelled"):
        raise ValueError(f"unknown job status {status!r}")
    sets, args = ["status=?", "updated_at=?", "heartbeat_at=?"], [status, time.time(), time.time()]
    if note is not None:
        sets.append("note=?")
        args.append(note)
    cur = con.execute(f"UPDATE jobs SET {', '.join(sets)} WHERE id=?", args + [job_id])
    if cur.rowcount:
        event(con, f"job.{status}", {"id": job_id})
    return cur.rowcount == 1


def running_count(con):
    """Jobs that hold a pool slot. waiting_user does not: it is parked on the user."""
    return con.execute(
        "SELECT COUNT(*) FROM jobs WHERE status IN ('claimed','delivered')").fetchone()[0]


# ---- retention ------------------------------------------------------------------------

def prune(con, days=30, now=None):
    """Delete finished history older than `days`. Never touches anything still in play:
    active jobs, pending drafts, open PRs, live sessions, the repo mapping or settings.
    `announced` is kept (tiny, and it stops an old PR being announced twice).
    Returns {table: rows deleted}.
    """
    now = now or time.time()
    cut = now - days * 86400
    stmts = {
        "events": ("DELETE FROM events WHERE ts < ?", (cut,)),
        "jobs": ("DELETE FROM jobs WHERE status IN ('done','failed','cancelled') AND updated_at < ?", (cut,)),
        "outbox": ("DELETE FROM outbox WHERE status IN ('posted','dropped') "
                   "AND COALESCE(posted_at, created_at) < ?", (cut,)),
        "review_pool": ("DELETE FROM review_pool WHERE status IN ('pulled','gone') AND shared_at < ?", (cut,)),
        "slack_seen": ("DELETE FROM slack_seen WHERE CAST(ts AS REAL) < ?", (cut,)),
        "questions": ("DELETE FROM questions WHERE status IN ('answered','expired') AND created_at < ?", (cut,)),
        "announcements": ("DELETE FROM announcements WHERE state IN ('posted','dropped') "
                          "AND COALESCE(updated_at, opened_at) < ?", (cut,)),
        "verdicts": ("DELETE FROM verdicts WHERE posted_at IS NOT NULL AND posted_at < ?", (cut,)),
        "prs": ("DELETE FROM prs WHERE state != 'OPEN' AND updated_at < ? AND url NOT IN "
                "(SELECT pr_url FROM jobs) AND url NOT IN (SELECT pr_url FROM outbox WHERE status "
                "IN ('pending','ready'))", (cut,)),
        "sessions": ("DELETE FROM sessions WHERE status = 'gone' AND COALESCE(seen_at, 0) < ? "
                     "AND sid NOT IN (SELECT sid FROM jobs WHERE sid IS NOT NULL)", (cut,)),
    }
    out = {}
    con.execute("BEGIN IMMEDIATE")
    try:
        for table, (sql, args) in stmts.items():
            out[table] = con.execute(sql, args).rowcount
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    set_setting(con, "last_prune", now)
    if any(out.values()):
        event(con, "pruned", {k: v for k, v in out.items() if v})
    return out


def prune_if_due(con, cfg, now=None):
    now = now or time.time()
    if now - float(get_setting(con, "last_prune", "0")) < 86400:
        return None
    return prune(con, int(cfg.get("retention_days", 30)), now)
