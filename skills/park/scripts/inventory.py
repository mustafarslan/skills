"""Which Claude sessions run on this computer, what runs inside each, and which ones park leaves alone."""
import json
import os
import re
import shlex
import sqlite3
import subprocess
import sys
from pathlib import Path

WINDOWS = sys.platform == "win32"

# The Bash and Monitor tools wrap every command as:
#   zsh -c source <snapshot> ... && eval '<command>' < /dev/null && pwd -P >| <file>
# inside which a quote is written '"'"' and ps shows a newline as \012. On Windows (Git Bash) the line is
#   "C:\...\bash.exe" -c "source <snapshot> ... && { eval '<command>' < /dev/null; } && pwd -P >| <file>"
# a Windows command line, whose -c argument is taken out the Windows way first.
EVAL_AT = re.compile(r"(?:&&|\{) eval (?=')")
WRAPPER_MARK = "/shell-snapshots/snapshot-"
# The PowerShell tool hands its script over in an environment variable: its text never shows in a process list.
PWSH_MARK = "CLAUDE_CODE_SHELL_LAUNCHER_SCRIPT"
# Helpers a watcher runs between checks: not worth re-arming on their own.
NOISE = re.compile(r"^(sleep|ps|caffeinate|cat|tail|head|grep|jq|sqlite3|git|gh|curl|osascript|date)\b")
# Jobs that parking would cut off and that must never start again by themselves: tests, builds,
# shipping and deploys. Warned about at park, mentioned on resume, never re-run.
LONG_RUNNING = re.compile(
    r"\b(pytest|npm (run )?test|npm run build|turbo|jest|vitest|cargo (build|test)|go test|mvn|gradle|"
    r"docker (build|compose up)|make\b|alembic upgrade|xcodebuild|swift (build|test)|test\.sh|run-?tests?\b|"
    r"tools/test|ship|deploy|release|publish|git push|gh pr (create|merge)|terraform (apply|destroy)|kubectl apply)")
# Work that keeps running until stopped, and is worth starting again on resume.
LOOP = re.compile(r"(^|[;&|(]\s*)while\s+(true|:|sleep)\b|\btail -[fF]\b|\b(inbox-watch|pr-watch|fswatch|watchexec)\b|"
                  r"(^|[;&|]\s*)watch\s")
SERVER = re.compile(r"\b(npm|pnpm|yarn|bun) (run )?(dev|start|serve)\b|\bvite\b|\bnext (dev|start)\b|\buvicorn\b|"
                    r"\bgunicorn\b|\bflask run\b|\brails s(erver)?\b|\bhttp\.server\b|\bwebpack serve\b|\bstorybook\b")


def win_argv(line):
    """A Windows command line split into arguments as the C runtime (and Node and Python) split it."""
    args, cur, i, n, quoted, have = [], [], 0, len(line), False, False
    while i < n:
        c = line[i]
        if c == "\\":
            j = i
            while j < n and line[j] == "\\":
                j += 1
            if j < n and line[j] == '"':          # 2n backslashes + quote: n backslashes, then the quote acts
                cur.append("\\" * ((j - i) // 2))
                if (j - i) % 2:                     # 2n+1: n backslashes and a literal quote
                    cur.append('"')
                    j += 1
                i, have = j, True
                continue
            cur.append(line[i:j])                   # backslashes not before a quote are literal
            i, have = j, True
            continue
        if c == '"':
            if quoted and i + 1 < n and line[i + 1] == '"':
                cur.append('"')                     # "" inside quotes: a literal quote
                i += 2
                continue
            quoted, have = not quoted, True
            i += 1
            continue
        if c in " \t" and not quoted:
            if have:
                args.append("".join(cur))
                cur, have = [], False
            i += 1
            continue
        cur.append(c)
        have = True
        i += 1
    if have:
        args.append("".join(cur))
    return args


def script_of(cmd):
    """The shell script a wrapper line runs: the line itself (a Mac ps line), or the -c argument of a
    Windows command line (`"C:\\...\\bash.exe" -c "..."`)."""
    if cmd.startswith('"') or re.match(r"[A-Za-z]:[\\/]", cmd):
        argv = win_argv(cmd)
        if "-c" in argv[1:-1]:
            return argv[argv.index("-c") + 1]
    return cmd


def eval_command(cmd):
    """The command a Bash/Monitor wrapper runs, exactly as typed, or None when it can't be recovered whole.
    It counts as whole only when the wrapper's own trailer follows it (`< /dev/null && pwd -P`, or just
    `&& pwd -P` for a command that reads stdin, such as a heredoc; on Windows the same inside `{ …; }`):
    anything else means the process line was cut short, and a fragment must never be started again."""
    cmd = script_of(cmd)
    m = EVAL_AT.search(cmd)
    if not m:
        return None
    try:
        lex = shlex.shlex(cmd[m.end():], posix=True)
        lex.whitespace_split = True
        first, after, then = lex.get_token(), lex.get_token(), lex.get_token()
    except ValueError:
        return None
    if cmd[m.start()] == "{" and first and first.endswith(";") and after == "}" and then == "&&":
        first, after = first[:-1], "<"             # `{ eval '<command>'; } && pwd`: one that reads stdin
    if not first or not (after == "<" or (after == "&&" and then == "pwd")):
        return None
    return first.replace("\\012", "\n").replace("\\011", "\t")


def classify(real):
    """long: warn, never restart. monitor/shell: restart on resume. oneoff: it ends by itself (a wait
    loop, an inline script, an ordinary command); listed, not restarted."""
    if LONG_RUNNING.search(real):
        return "long"
    if "\n" in real or "<<" in real:
        return "oneoff"            # an inline script ran once; re-running it is never what was meant
    if LOOP.search(real):
        return "monitor"
    if SERVER.search(real):
        return "shell"
    return "oneoff"


def run(args, cwd=None, timeout=30, env=None):
    try:
        p = subprocess.run(args, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=timeout, env=env)
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
    """{pid: (ppid, command)} for every process, with full command lines (-ww: never cut to a width)."""
    if WINDOWS:
        import winterm
        return winterm.process_table()
    table = {}
    for line in (run(["ps", "-wwaxo", "pid=,ppid=,command="]) or "").splitlines():
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
    """Where the session's window is: its tty on the Mac, its Windows Terminal tab on Windows (winterm.host_of)."""
    if WINDOWS:
        import winterm
        return winterm.host_of(pid)
    t =(run(["ps", "-o", "tty=", "-p", str(pid)]) or "").strip()
    return "" if t in ("", "??") else "/dev/" + t


def ancestors(table, pid):
    out = set()
    while pid in table and pid not in out and pid > 1:
        out.add(pid)
        pid = table[pid][0]
    return out


def tool_commands(table, pid, me=None):
    """The commands this session's Bash/Monitor tools are running right now, as typed.
    Returns [{kind: monitor|shell|long|oneoff|partial, command}] (see classify; partial: the start of a
    command that could not be read whole, never restarted). The command running park itself (this
    process and its parents) is never one of them."""
    items, seen = [], set()
    mine = ancestors(table, os.getpid() if me is None else me)
    for p in descendants(table, pid):
        cmd = table[p][1]
        if PWSH_MARK in cmd and p not in mine and PWSH_MARK not in seen:
            seen.add(PWSH_MARK)          # one line for all of them: their text can't be told apart
            items.append({"kind": "partial", "command": "a PowerShell tool command (Windows doesn't show its text)"})
            continue
        if WRAPPER_MARK not in cmd or p in mine:
            continue
        real = eval_command(cmd)
        if real is None:
            m = EVAL_AT.search(cmd)
            frag = cmd[m.end():][:120] if m else ""
            if frag and frag not in seen:
                seen.add(frag)
                items.append({"kind": "partial", "command": frag + " …"})
            continue
        real = real.strip()
        if not real or real in seen or NOISE.match(real):
            continue
        seen.add(real)
        items.append({"kind": classify(real), "command": real})
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
