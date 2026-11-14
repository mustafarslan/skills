"""park's own store: one SQLite file (WAL), ~/.claude/park/park.db. PARK_HOME overrides the folder."""
import json
import os
import shutil
import sqlite3
import time
from pathlib import Path

DEFAULTS = {
    "retention_days": 30,      # parks older than this are deleted, with their patches
    "quit_terminal": "all",    # "all": quit Terminal.app after parking | "none": leave it open
    "busy_wait_s": 20,         # how long a busy session gets to settle before it is stopped
    "notes": False,            # ask idle sessions for a "next action" note before parking
}

SCHEMA = (
    """CREATE TABLE IF NOT EXISTS parks(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        at REAL NOT NULL,
        label TEXT,
        status TEXT NOT NULL DEFAULT 'planned',   -- planned | parking | parked | cancelled
        pr_pulse_was_on INTEGER NOT NULL DEFAULT 0,
        partial INTEGER NOT NULL DEFAULT 0,       -- --only/--exclude: pr-pulse and other windows stay
        parked_by TEXT)""",
    """CREATE TABLE IF NOT EXISTS sessions(
        park_id INTEGER NOT NULL REFERENCES parks(id) ON DELETE CASCADE,
        sid TEXT NOT NULL,
        name TEXT, kind TEXT, pid INTEGER, tty TEXT,
        cwd TEXT, repo_root TEXT, branch TEXT, head TEXT,
        dirty INTEGER NOT NULL DEFAULT 0, patch_path TEXT, untracked TEXT NOT NULL DEFAULT '[]',
        unpushed INTEGER NOT NULL DEFAULT 0,
        status_at_park TEXT, long_running TEXT NOT NULL DEFAULT '[]',
        skipped_reason TEXT,                       -- set: this session is not parked or resumed
        rearm TEXT NOT NULL DEFAULT '[]',          -- [{kind, command}]
        crons TEXT NOT NULL DEFAULT '[]',          -- [{cron, recurring, prompt}]
        last_message TEXT, note TEXT, resume_prompt TEXT,
        stopped INTEGER NOT NULL DEFAULT 0, resumed_at REAL,
        PRIMARY KEY(park_id, sid))""",
    """CREATE TABLE IF NOT EXISTS events(ts REAL NOT NULL, kind TEXT NOT NULL, detail TEXT)""",
    """CREATE TABLE IF NOT EXISTS config(key TEXT PRIMARY KEY, value TEXT)""",
)


def home():
    return Path(os.environ.get("PARK_HOME") or Path.home() / ".claude" / "park")


def patches_dir(park_id):
    return home() / "patches" / str(park_id)


def connect(path=None):
    path = Path(path) if path else home() / "park.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path), timeout=30, isolation_level=None)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    for stmt in SCHEMA:
        con.execute(stmt)
    return con


def event(con, kind, detail=None):
    con.execute("INSERT INTO events(ts, kind, detail) VALUES(?,?,?)",
                (time.time(), kind, json.dumps(detail) if detail is not None else None))


def config(con):
    cfg = dict(DEFAULTS)
    for r in con.execute("SELECT key, value FROM config"):
        try:
            cfg[r["key"]] = json.loads(r["value"])
        except ValueError:
            cfg[r["key"]] = r["value"]
    return cfg


def set_config(con, key, value):
    if key not in DEFAULTS:
        raise KeyError(f"unknown setting {key!r}; known: {', '.join(DEFAULTS)}")
    con.execute("INSERT INTO config(key, value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, json.dumps(value)))


def gc(con, now=None):
    """Delete parks older than retention_days, their sessions, patches and old events.
    A parked park with a session never resumed is kept, patch and all, however old: its work may exist
    nowhere else. `park list` still shows it. Returns how many parks were removed."""
    now = now or time.time()
    days = float(config(con).get("retention_days") or DEFAULTS["retention_days"])
    cutoff = now - days * 86400
    old = [r["id"] for r in con.execute(
        "SELECT id FROM parks p WHERE at < ? AND NOT (status = 'parked' AND EXISTS ("
        "SELECT 1 FROM sessions s WHERE s.park_id = p.id AND s.skipped_reason IS NULL AND s.resumed_at IS NULL))",
        (cutoff,))]
    for pid in old:
        con.execute("DELETE FROM sessions WHERE park_id=?", (pid,))
        con.execute("DELETE FROM parks WHERE id=?", (pid,))
        shutil.rmtree(patches_dir(pid), ignore_errors=True)
    con.execute("DELETE FROM events WHERE ts < ?", (cutoff,))
    return len(old)
