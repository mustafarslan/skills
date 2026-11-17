"""Tell the user when ANY Claude session is waiting for them (a question or a permission
prompt), not only pr-pulse's own: one notification per session, with an explicit
"Open session" button. Skipped for the Terminal tab they are looking at; cleared once the
session stops waiting; repeated every REMIND seconds while it keeps waiting.
"""
import subprocess
import sys
import time
from pathlib import Path

import core
import db

REMIND = 3600
NUDGE = Path(__file__).resolve().parent / "pr-pulse-nudge.py"


def front_tty():
    """tty of the Terminal tab in front, or '' when Terminal isn't the front app."""
    front = core.run(["sh", "-c", 'lsappinfo info -only name "$(lsappinfo front)"']) or ""
    if "Terminal" not in front:
        return ""
    out = core.run(["osascript", "-e", 'tell application "Terminal" to return tty of selected tab of front window'])
    return (out or "").strip()


def session_tty(s):
    if s.get("kind") != "interactive" or not s.get("pid"):
        return ""
    t = (core.run(["ps", "-o", "tty=", "-p", str(s["pid"])]) or "").strip()
    return "/dev/" + t if t and t != "??" else ""


def group(sid):
    return f"pr-pulse-wait-{sid[:8]}"


PENDING = "pending_remove:"


def question_on_screen(con):
    return bool(con is not None and con.execute(
        "SELECT 1 FROM questions WHERE status='showing'").fetchone())


def clear(sid, con=None):
    """Take a session's 'waiting for you' banner down. Never while a question banner is up:
    `alerter --remove` on another group froze the question banner on screen (no buttons, no
    close; reproduced 2026-11-13 11:02). Then the removal waits for flush_removals()."""
    core.run(["pkill", "-f", f"pr-pulse-nudge.py {sid}"])
    if not core.run(["which", "alerter"]):
        return
    if question_on_screen(con):
        db.set_setting(con, PENDING + group(sid), time.time())
        return
    core.run(["alerter", "--remove", group(sid)])


def flush_removals(con):
    """Run the banner removals that waited for the question banner to go."""
    if question_on_screen(con):
        return 0
    rows = con.execute("SELECT key FROM settings WHERE key LIKE ?", (PENDING + "%",)).fetchall()
    for r in rows:
        if core.run(["which", "alerter"]):
            core.run(["alerter", "--remove", r["key"][len(PENDING):]])
        con.execute("DELETE FROM settings WHERE key=?", (r["key"],))
    return len(rows)


def watch(con, sessions, cfg, now=None, launch=None, front=None):
    """Called each tick with `claude agents --json`. Returns the session ids nudged now."""
    if not cfg.get("notify_waiting_sessions", True) or sessions is None:
        return []
    now = now or time.time()
    launch = launch or _launch
    flush_removals(con)
    waiting = {s["sessionId"]: s for s in sessions if s.get("status") == "waiting" and s.get("sessionId")}
    # sessions that stopped waiting (answered, or gone): forget them and clear their banner
    for row in con.execute("SELECT key FROM settings WHERE key LIKE 'waiting_seen:%'").fetchall():
        sid = row["key"].split(":", 1)[1]
        if sid not in waiting:
            con.execute("DELETE FROM settings WHERE key=?", (row["key"],))
            clear(sid, con)
    nudged = []
    ftty = None
    for sid, s in waiting.items():
        key = f"waiting_seen:{sid}"
        last = float(db.get_setting(con, key, "0"))
        if now - last < REMIND:
            continue
        if ftty is None:
            ftty = front() if front else front_tty()
        if ftty and session_tty(s) == ftty:
            continue   # they are looking at it right now
        db.set_setting(con, key, now)
        launch(s)
        db.event(con, "session.waiting", {"sid": sid, "name": s.get("name"), "for": s.get("waitingFor", "")})
        nudged.append(sid)
    return nudged


def _launch(s):
    subprocess.Popen([sys.executable, str(NUDGE), s["sessionId"], s.get("name") or s["sessionId"][:8],
                      s.get("cwd") or "", s.get("waitingFor") or "input needed"],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)
