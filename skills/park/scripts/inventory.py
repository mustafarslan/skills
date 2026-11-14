"""Which Claude sessions run on this Mac, what runs inside each, and which ones park leaves alone."""
import json
import os
import re
import sqlite3
import subprocess
from pathlib import Path

# The Bash and Monitor tools wrap every command as: zsh -c source <snapshot> ... && eval '<command>' ...
EVAL_RE = re.compile(r"\beval '((?:[^']|'\\'')*)'")
WRAPPER_MARK = "/shell-snapshots/snapshot-"
# Helpers a watcher runs between checks: not worth re-arming on their own.
NOISE = re.compile(r"^(sleep|ps|caffeinate|cat|tail|head|grep|jq|sqlite3|git|gh|curl|osascript|date)\b")
# Long jobs that parking would cut off (warned about, never re-run on their own).
LONG_RUNNING = re.compile(r"\b(pytest|npm (run )?test|npm run build|turbo|jest|vitest|cargo (build|test)|"
                          r"go test|mvn|gradle|docker (build|compose up)|make\b|alembic upgrade)")


def run(args, cwd=None, timeout=30):
    try:
        p = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    return p.stdout if p.returncode == 0 else None


def claude_sessions():
    """Live sessions from `claude agents --json`: [{pid, cwd, kind, sessionId, name, status}]."""
    out = run(["claude", "agents", "--json"], timeout=45)
    try:
        data = json.loads(out or "[]")
    except ValueError:
        return []
    return data if isinstance(data, list) else data.get("sessions") or []


def process_table():
    """{pid: (ppid, command)} for every process."""
    table = {}
    for line in (run(["ps", "-axo", "pid=,ppid=,command="]) or "").splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
            table[int(parts[0])] = (int(parts[1]), parts[2] if len(parts) > 2 else "")
    return table


def descendants(table, pid):
    kids = {}
    for p, (pp, _) in table.items():
        kids.setdefault(pp, []).append(p)
    out, todo = [], list(kids.get(pid, []))
    while todo:
        p = todo.pop()
        out.append(p)
        todo += kids.get(p, [])
    return out


def tty_of(pid):
    t = (run(["ps", "-o", "tty=", "-p", str(pid)]) or "").strip()
    return "" if t in ("", "??") else "/dev/" + t


def ancestors(table, pid):
    out = set()
    while pid in table and pid not in out and pid > 1:
        out.add(pid)
        pid = table[pid][0]
    return out


def tool_commands(table, pid, me=None):
    """The commands this session's Bash/Monitor tools are running right now, as typed.
    Returns [{kind: monitor|shell|long, command}] (kind monitor: a watcher that loops).
    The command running park itself (this process and its parents) is never one of them."""
    items, seen = [], set()
    mine = ancestors(table, os.getpid() if me is None else me)
    for p in descendants(table, pid):
        cmd = table[p][1]
        if WRAPPER_MARK not in cmd or p in mine:
            continue
        m = EVAL_RE.search(cmd)
        if not m:
            continue
        real = m.group(1).replace("'\\''", "'").strip()
        if not real or real in seen or NOISE.match(real):
            continue
        seen.add(real)
        if LONG_RUNNING.search(real):
            kind = "long"
        elif re.search(r"watch|monitor|tail -f|while |until |inbox-watch|pr-watch", real):
            kind = "monitor"
        else:
            kind = "shell"
        items.append({"kind": kind, "command": real})
    return items


def pr_pulse_sessions(db_path=None):
    """(spawned worker sids, joined sids) from pr-pulse's store, when pr-pulse is installed."""
    path = Path(db_path or os.environ.get("PARK_PR_PULSE_DB") or Path.home() / ".claude" / "pr-pulse" / "pulse.db")
    if not path.exists():
        return set(), set()
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
        spawned = {r[0] for r in con.execute("SELECT sid FROM sessions WHERE spawned=1")}
        joined = {r[0] for r in con.execute("SELECT sid FROM sessions WHERE registered=1")}
        con.close()
        return spawned, joined
    except sqlite3.Error:
        return set(), set()


def is_pr_pulse_worker(s, spawned):
    cwd = s.get("cwd") or ""
    return s.get("sessionId") in spawned or "/.claude/worktrees/pr-pulse-" in cwd


def matches(s, patterns):
    name, sid = (s.get("name") or "").lower(), (s.get("sessionId") or "").lower()
    return any(p.lower() in name or sid.startswith(p.lower()) for p in patterns)


def inventory(only=(), exclude=(), sessions=None, table=None, pr_pulse_db=None):
    """Every live session with what runs inside it, and `skipped_reason` for those park leaves alone."""
    sessions = claude_sessions() if sessions is None else sessions
    table = process_table() if table is None else table
    spawned, joined = pr_pulse_sessions(pr_pulse_db)
    out = []
    for s in sessions:
        sid = s.get("sessionId") or ""
        if not sid:
            continue
        cmds = tool_commands(table, int(s.get("pid") or 0)) if s.get("pid") else []
        skip = None
        if not s.get("pid"):
            skip = "not running (a stopped background session: nothing to park)"
        elif is_pr_pulse_worker(s, spawned):
            skip = "pr-pulse worker (pr-pulse requeues its jobs itself)"
        elif only and not matches(s, only):
            skip = "not in --only"
        elif exclude and matches(s, exclude):
            skip = "in --exclude"
        out.append({"sid": sid, "name": s.get("name") or sid[:8], "kind": s.get("kind") or "interactive",
                    "pid": s.get("pid"), "cwd": s.get("cwd") or "", "status": s.get("status") or "",
                    "pr_pulse_joined": sid in joined, "commands": cmds, "skipped_reason": skip})
    return out
