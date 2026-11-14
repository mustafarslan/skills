"""Apple Terminal through osascript (Automation permission only, never Accessibility)."""
import os
import shutil
import subprocess


def _q(s):
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


def osa(script, timeout=20):
    try:
        p = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as e:
        return False, str(e)
    return p.returncode == 0, (p.stdout or p.stderr or "").strip()


def can_control():
    """(ok, message). Asking Terminal for its window count triggers the macOS Automation prompt
    the first time; a refusal comes back as error -1743."""
    ok, out = osa('tell application "Terminal" to count windows')
    if ok:
        return True, ""
    if "-1743" in out or "not allowed" in out.lower():
        return False, ("macOS doesn't let Claude control Terminal. System Settings → Privacy & Security → "
                       "Automation → allow Terminal for the app running Claude Code, then run /park again.")
    return False, f"could not talk to Terminal: {out[:160]}"


def open_window(command):
    """A new Terminal window running `command` (do script without a target opens a new window)."""
    return osa(f'tell application "Terminal"\nactivate\ndo script {_q(command)}\nend tell')[0]


def close_windows(ttys):
    """Close each Terminal window whose tabs all belong to `ttys` (parked sessions). A window that also
    holds another tab (a session that wasn't parked, a plain shell) stays open: Terminal can't close
    one tab from AppleScript, and closing the window would kill that tab too. Returns how many closed."""
    if not ttys:
        return 0
    wanted = "{" + ", ".join(_q(t) for t in ttys) + "}"
    ok, out = osa(f'''set wanted to {wanted}
set n to 0
tell application "Terminal"
  repeat with w in (get windows)
    set mine to true
    repeat with t in tabs of w
      if (tty of t as text) is not in wanted then set mine to false
    end repeat
    if mine then
      close w
      set n to n + 1
    end if
  end repeat
end tell
return n''')
    try:
        return int(out) if ok else 0
    except ValueError:
        return 0


def quit_terminal():
    """Quit Terminal. Terminal itself still asks when a shell runs something other than a login shell."""
    return osa('tell application "Terminal" to quit', timeout=60)[0]


def notify(msg):
    if os.environ.get("PARK_NO_NOTIFY") == "1":
        return
    if shutil.which("alerter"):
        subprocess.Popen(["alerter", "--title", "park", "--message", msg, "--timeout", "30"],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
        return
    osa(f'display notification {_q(msg)} with title "park"')
