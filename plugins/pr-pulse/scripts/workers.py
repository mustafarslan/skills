"""pr-pulse's own background workers: recognise them, open them, and stop the finished ones.

Two workers for the same PR and action share a name (pr-<owner>-<repo>-<n>-<action>), and a
finished worker used to stay alive forever. `claude attach <name>` then fails ("2 sessions
match… Use the id"), the leftovers hold memory, and `auto-review off` found none of them,
because the "started by pr-pulse" mark (sessions.spawned) was never set: the worker's own
`pr-pulse job start` replaced the job's name:<worker> placeholder before the daemon could bind it.

So:
- `mark_spawned` sets the mark from pr-pulse's own records (worker.spawned events) and from
  the worker worktree path, every tick; `job start` sets it at once.
- `attach_ref` is always the session id (its first 8 characters), never the name.
- `reap_idle` stops a worker that is idle, holds no active job, and has had no job activity for
  `worker_idle_minutes`. A busy worker, or one whose job waits for the user, is never stopped.
- `clear_name` stops a job-less leftover with the name a new worker is about to take.
"""
import json
import subprocess
import time

ACTIVE = ("claimed", "delivered", "waiting_user")
WORKTREE_MARK = "/.claude/worktrees/pr-pulse-"


def attach_ref(sid):
    return (sid or "")[:8]


def attach_cmd(sid):
    return f"claude attach {attach_ref(sid)}"


def worker_names(con, since_days=30):
    names = set()
    for r in con.execute("SELECT detail FROM events WHERE kind='worker.spawned' AND ts > ?",
                         (time.time() - since_days * 86400,)):
        try:
            n = json.loads(r[0]).get("name")
        except (ValueError, AttributeError, TypeError):
            continue
        if n:
            names.add(n)
    return names


def mark_spawned(con):
    """Mark live background sessions pr-pulse started as workers. Returns how many were marked."""
    names = worker_names(con)
    n = 0
    for s in con.execute("SELECT sid, name, cwd FROM sessions WHERE spawned=0 AND status != 'gone' "
                         "AND kind='background'").fetchall():
        if (s["name"] and s["name"] in names) or WORKTREE_MARK in (s["cwd"] or ""):
            con.execute("UPDATE sessions SET spawned=1 WHERE sid=?", (s["sid"],))
            n += 1
    return n


def has_active_job(con, sid):
    return bool(con.execute(f"SELECT 1 FROM jobs WHERE sid=? AND status IN {ACTIVE}", (sid,)).fetchone())


def _stop(sid):
    return subprocess.call(["claude", "stop", attach_ref(sid)], stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL) == 0


def reap_idle(con, cfg, now=None, stopper=None):
    """Stop finished workers. Returns the names stopped."""
    now = now or time.time()
    stopper = stopper or _stop
    quiet = float(cfg.get("worker_idle_minutes", 10)) * 60
    stopped = []
    for s in con.execute("SELECT sid, name FROM sessions WHERE spawned=1 AND status='idle' "
                         "AND kind='background'").fetchall():
        if has_active_job(con, s["sid"]) or (s["name"] and has_active_job(con, "name:" + s["name"])):
            continue   # holds a job, or was just started for one and has not bound to it yet
        last = con.execute("SELECT MAX(updated_at) FROM jobs WHERE sid=?", (s["sid"],)).fetchone()[0]
        if last and now - last < quiet:
            continue
        if stopper(s["sid"]):
            con.execute("UPDATE sessions SET status='gone' WHERE sid=?", (s["sid"],))
            stopped.append(s["name"] or attach_ref(s["sid"]))
            import db
            db.event(con, "worker.reaped", {"sid": s["sid"], "name": s["name"]})
    return stopped


def clear_name(con, name, live, stopper=None):
    """Before a new worker takes `name`: stop live sessions with that name that hold no active job.
    Returns (stopped, kept) session ids; a kept one holds a job and is never touched."""
    stopper = stopper or _stop
    stopped, kept = [], []
    for x in live or []:
        if x.get("name") != name:
            continue
        sid = x.get("sessionId", "")
        if has_active_job(con, sid):
            kept.append(sid)
        elif stopper(sid):
            stopped.append(sid)
    return stopped, kept
