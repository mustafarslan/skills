"""Bring a Claude session to the front from a notification click (Apple Terminal).

Background session: a new Terminal window running `claude attach <id>` (by id: two workers for
the same PR can share a name, and `claude attach <name>` then refuses).
Interactive session: select the Terminal tab whose tty is the session's tty.
"""
import subprocess

import core


def _osa(script):
    return subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=15)


def _q(s):
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


def find(sid, name=None):
    live = core.list_sessions() or []
    for s in live:              # the id first: a name may belong to several sessions
        if sid and s.get("sessionId") == sid:
            return s
    named = [s for s in live if name and s.get("name") == name]
    return named[0] if len(named) == 1 else None


def open_session(sid, name=None):
    """Returns a one-line result for the log."""
    s = find(sid, name)
    if not s:
        return "session is not running"
    if s.get("kind") == "background":
        ref = s.get("sessionId", "")[:8] or s.get("name")
        _osa(f'tell application "Terminal"\nactivate\ndo script {_q("claude attach " + ref)}\nend tell')
        return f"opened claude attach {ref}"
    tty = (core.run(["ps", "-o", "tty=", "-p", str(s.get("pid", ""))]) or "").strip()
    if not tty or tty == "??":
        return "could not find the session's terminal"
    dev = "/dev/" + tty
    r = _osa(f'''tell application "Terminal"
  repeat with w in windows
    repeat with t in tabs of w
      if tty of t is {_q(dev)} then
        set selected tab of w to t
        set index of w to 1
        activate
        return "ok"
      end if
    end repeat
  end repeat
end tell
return "not found"''')
    return "focused its Terminal tab" if "ok" in (r.stdout or "") else "its Terminal tab was not found"
