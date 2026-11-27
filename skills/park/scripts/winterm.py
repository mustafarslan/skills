"""Windows: Windows Terminal tabs, a console Ctrl+C for a session, and the process table. No admin needed.

What stands in for the Mac's pieces:
  SIGINT to a session      -> a Ctrl+C event on its console (a helper attaches to it; Node reads it as SIGINT)
  SIGTERM                  -> TerminateProcess
  Terminal.app's windows   -> Windows Terminal tabs; each resumed session opens as a tab of one window, "park"
  a window's tty           -> the tab's host: the process Windows Terminal started for that tab
  quitting Terminal        -> never: only the parked sessions' own tabs close, so nothing else is cut off

Also runnable as `python winterm.py ctrl-c PID` (the helper) and `python winterm.py launch JOB.json` (what a
resumed tab runs: it starts claude with its prompt passed whole, which no shell's quoting can promise).
"""
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_NO_WINDOW = 0x08000000
CREATE_BREAKAWAY_FROM_JOB = 0x01000000
STILL_ACTIVE = 259

# Processes Windows Terminal starts for a tab, and what may sit between that and claude. A tab whose chain holds
# anything else (an IDE's terminal, a script that started claude) is not park's to close.
TERMINALS = {"windowsterminal.exe"}
SHELLS = {"bash.exe", "sh.exe", "zsh.exe", "pwsh.exe", "powershell.exe", "cmd.exe", "nu.exe"}
LAUNCHERS = SHELLS | {"python.exe", "python3.exe", "pythonw.exe", "py.exe", "claude.exe", "node.exe"}
HELPERS = {"conhost.exe", "openconsole.exe"}

# Set by Claude Code for the session it runs in. A session started with them inherited thinks it is a child of
# this one: its transcript is not saved, among other things. Mac's Terminal starts each window with a fresh
# environment; on Windows a new tab inherits the caller's, so they are taken out before claude starts.
SESSION_ONLY_PREFIXES = ("CLAUDE",)


# ---- processes ------------------------------------------------------------------------------

def _k32():
    import ctypes
    from ctypes import wintypes
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.OpenProcess.restype = wintypes.HANDLE
    k.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    k.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    k.TerminateProcess.argtypes = (wintypes.HANDLE, wintypes.UINT)
    k.CloseHandle.argtypes = (wintypes.HANDLE,)
    k.AttachConsole.argtypes = (wintypes.DWORD,)
    k.GenerateConsoleCtrlEvent.argtypes = (wintypes.DWORD, wintypes.DWORD)
    k.SetConsoleCtrlHandler.argtypes = (ctypes.c_void_p, wintypes.BOOL)
    return k


def alive(pid):
    """Never os.kill(pid, 0) on Windows: signal 0 is CTRL_C_EVENT there."""
    import ctypes
    from ctypes import wintypes
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    k = _k32()
    h = k.OpenProcess(0x1000, False, pid)          # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return ctypes.get_last_error() == 5        # access denied: it exists, it isn't ours
    try:
        code = wintypes.DWORD()
        return bool(k.GetExitCodeProcess(h, ctypes.byref(code))) and code.value == STILL_ACTIVE
    finally:
        k.CloseHandle(h)


def terminate(pid, code=0):
    """TerminateProcess. Exit code 0, so Windows Terminal closes the tab as after a normal exit."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    k = _k32()
    h = k.OpenProcess(0x0001, False, pid)          # PROCESS_TERMINATE
    if not h:
        return False
    try:
        return bool(k.TerminateProcess(h, code))
    finally:
        k.CloseHandle(h)


def interrupt(pid):
    """A Ctrl+C on the console `pid` runs in, as if typed with the console in its usual mode. Sent by a detached
    helper, because attaching to another console means leaving one's own."""
    try:
        p = subprocess.run([sys.executable, "-I", str(Path(__file__).resolve()), "ctrl-c", str(int(pid))],
                           capture_output=True, timeout=15, creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP)
    except (OSError, subprocess.SubprocessError, TypeError, ValueError):
        return False
    return p.returncode == 0


def _ctrl_c(pid):
    k = _k32()
    k.FreeConsole()
    if not k.AttachConsole(int(pid)):
        return 1
    k.SetConsoleCtrlHandler(None, True)            # this helper ignores the event it sends
    ok = k.GenerateConsoleCtrlEvent(0, 0)          # CTRL_C_EVENT to every process on that console
    time.sleep(0.2)
    k.FreeConsole()
    return 0 if ok else 1


_cache = {"at": 0.0, "procs": {}}


def recent_processes(max_age=10.0):
    """processes(), reused for a few seconds: a plan reads one table for all its sessions (each read takes ~1 s)."""
    if time.time() - _cache["at"] > max_age or not _cache["procs"]:
        _cache.update(at=time.time(), procs=processes())
    return _cache["procs"]


def processes():
    """{pid: {ppid, name, cmd, created}} for every process (created: a FILETIME, to tell a reused pid apart)."""
    ps = ("Get-CimInstance Win32_Process | ForEach-Object { [pscustomobject]@{p=[int]$_.ProcessId; "
          "pp=[int]$_.ParentProcessId; n=[string]$_.Name; c=[string]$_.CommandLine; "
          "t=$(if ($_.CreationDate) { $_.CreationDate.ToFileTimeUtc() } else { 0 })} } | ConvertTo-Json -Compress")
    try:
        p = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=60, creationflags=CREATE_NO_WINDOW)
        rows = json.loads(p.stdout or "[]")
    except (OSError, subprocess.SubprocessError, ValueError):
        return {}
    rows = rows if isinstance(rows, list) else [rows]
    out = {int(r["p"]): {"ppid": int(r["pp"]), "name": (r.get("n") or "").lower(), "cmd": r.get("c") or "",
                         "created": int(r.get("t") or 0)} for r in rows if r.get("p") is not None}
    _cache.update(at=time.time(), procs=out)
    return out


def process_table(procs=None):
    """{pid: (ppid, command)}, as inventory.process_table gives it on the Mac. A parent pid Windows still
    reports for a process whose parent has exited (and may since be reused) is dropped."""
    procs = processes() if procs is None else procs
    def ppid(p):
        parent = procs.get(p["ppid"])
        return p["ppid"] if parent and parent["created"] <= p["created"] else 0
    return {pid: (ppid(p), p["cmd"]) for pid, p in procs.items()}


def host_of(pid, procs=None):
    """The tab a session runs in, as `wt:<pid of the tab's own process>:<its start time>`, or "" when it is not a
    Windows Terminal tab park may close (another terminal, an IDE, something unexpected in between)."""
    procs = recent_processes() if procs is None else procs
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return ""
    seen = set()
    while pid in procs and pid not in seen:
        seen.add(pid)
        me, parent = procs[pid], procs.get(procs[pid]["ppid"])
        if me["name"] not in LAUNCHERS:
            return ""
        if parent and parent["name"] in TERMINALS and parent["created"] <= me["created"]:
            return f"wt:{pid}:{me['created']}"
        if not parent or parent["created"] > me["created"]:
            return ""                              # its parent is gone (the pid may be someone else's now)
        pid = me["ppid"]
    return ""


def _descendants(procs, pid):
    kids = {}
    for p, info in procs.items():
        kids.setdefault(info["ppid"], []).append(p)
    out, todo = [], list(kids.get(pid, []))
    while todo:
        p = todo.pop()
        if procs[p]["created"] < procs[pid]["created"]:
            continue                               # an older process whose parent pid merely matches
        out.append(p)
        todo += kids.get(p, [])
    return out


def closable(host, procs):
    """The pids to end (deepest first) to close this tab, or None when the tab holds something still running.
    Like Terminal.app quitting without a prompt: only shells sitting at a prompt (no child of their own) and
    park's launcher may be ended; anything else keeps the tab open."""
    try:
        _, root, created = host.split(":")
        root, created = int(root), int(created)
    except (AttributeError, ValueError):
        return None
    if root not in procs or procs[root]["created"] != created:
        return []                                  # already closed
    tree = [root] + _descendants(procs, root)
    kids = {p: [c for c in tree if procs[c]["ppid"] == p and procs[c]["name"] not in HELPERS] for p in tree}
    for p in tree:
        name = procs[p]["name"]
        if name in HELPERS:
            continue
        if name in SHELLS or name in ("python.exe", "python3.exe", "py.exe"):
            if name in SHELLS and any(procs[c]["name"] not in SHELLS | LAUNCHERS for c in kids[p]):
                return None
            continue
        return None                                # claude still up, a tool, a server: not ours to end
    return [p for p in reversed(tree) if procs[p]["name"] not in HELPERS]


def close_tabs(hosts, procs_fn=None, end=None):
    """Close each parked session's tab. Returns how many closed."""
    procs_fn, end = procs_fn or processes, end or terminate
    n = 0
    for h in hosts:
        if not h or not h.startswith("wt:"):
            continue
        pids = closable(h, procs_fn())
        if pids:
            for p in pids:
                end(p)
            n += 1
    return n


# ---- Windows Terminal -----------------------------------------------------------------------

def wt_path():
    return shutil.which("wt") or shutil.which("wt.exe")


def can_control():
    if wt_path():
        return True, ""
    return False, ("Windows Terminal (wt.exe) isn't installed or its alias is off. Install it from the Microsoft "
                   "Store, or turn on Settings → Apps → Advanced app settings → App execution aliases → wt.exe.")


def persistent_names():
    """Variable names set in the user's or the machine's own environment (the registry), which stay."""
    names = set()
    try:
        import winreg
        for root, sub in ((winreg.HKEY_CURRENT_USER, "Environment"),
                          (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment")):
            try:
                with winreg.OpenKey(root, sub) as key:
                    i = 0
                    while True:
                        try:
                            names.add(winreg.EnumValue(key, i)[0].upper())
                        except OSError:
                            break
                        i += 1
            except OSError:
                pass
    except ImportError:
        pass
    return names


def session_only_vars(env=None, keep=None):
    """This session's own variables: CLAUDE* names not in the user's persistent environment."""
    env = os.environ if env is None else env
    keep = persistent_names() if keep is None else keep
    return sorted(k for k in env if k.upper().startswith(SESSION_ONLY_PREFIXES) and k.upper() not in keep)


def launch_dir():
    home = Path(os.environ.get("PARK_HOME") or Path.home() / ".claude" / "park")
    return home / "launch"


def tab_args(job_path, cwd, title, wt="wt.exe", python=None):
    """wt.exe arguments for one resumed tab in the window named "park". wt splits its own command line at
    `;`, so a `;` in a path is written `\\;`."""
    esc = lambda s: str(s).replace(";", "\\;")
    python = python or sys.executable
    return [wt, "-w", "park", "new-tab", "--title", esc(title), "-d", esc(cwd),
            esc(python), "-I", esc(Path(__file__).resolve()), "launch", esc(job_path)]


def open_tab(cwd, sid, prompt, title, claude=None, env=None):
    """Write the job, then open it as a tab. The job holds the exact argv, so the prompt (newlines, quotes,
    backticks) reaches claude whole."""
    claude = claude or shutil.which("claude") or "claude"
    d = launch_dir()
    d.mkdir(parents=True, exist_ok=True)
    job = d / f"{sid}.json"
    job.write_text(json.dumps({"cwd": cwd, "argv": [claude, "--resume", sid, prompt],
                               "unset": session_only_vars(env)}), encoding="utf-8")
    env = {k: v for k, v in (os.environ if env is None else env).items() if k not in set(session_only_vars(env))}
    try:
        p = subprocess.run(tab_args(job, cwd, title, wt=wt_path() or "wt.exe"), env=env, capture_output=True,
                           timeout=30, creationflags=CREATE_NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return False
    return p.returncode == 0


def _launch(job_path):
    """Run inside the new tab: claude with its argv as saved, then a shell, as a Terminal window leaves one."""
    import signal
    job = json.loads(Path(job_path).read_text(encoding="utf-8"))
    try:
        Path(job_path).unlink()
    except OSError:
        pass
    env = {k: v for k, v in os.environ.items() if k not in set(job.get("unset") or [])}
    os.chdir(job["cwd"])
    signal.signal(signal.SIGINT, signal.SIG_IGN)   # a Ctrl+C is claude's; this launcher only waits for it
    subprocess.call(job["argv"], env=env)
    shell = shutil.which("pwsh") or shutil.which("powershell") or "cmd"
    return subprocess.call([shell, "-NoLogo"] if "cmd" not in Path(shell).name.lower() else [shell], env=env)


def notify(msg):
    if os.environ.get("PARK_NO_NOTIFY") == "1":
        return
    xml = msg.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("'", "&apos;")
    ps = ("[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType=WindowsRuntime] | "
          "Out-Null; [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType=WindowsRuntime] | "
          "Out-Null; $x = New-Object Windows.Data.Xml.Dom.XmlDocument; "
          f"$x.LoadXml('<toast><visual><binding template=\"ToastGeneric\"><text>park</text><text>{xml}</text>"
          "</binding></visual></toast>'); "
          "$id = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe'; "
          "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($id).Show("
          "[Windows.UI.Notifications.ToastNotification]::new($x))")
    try:
        subprocess.Popen(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW)
    except OSError:
        pass


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "ctrl-c":
        sys.exit(_ctrl_c(sys.argv[2]))
    if len(sys.argv) == 3 and sys.argv[1] == "launch":
        sys.exit(_launch(sys.argv[2]))
    print(__doc__)
    sys.exit(2)
