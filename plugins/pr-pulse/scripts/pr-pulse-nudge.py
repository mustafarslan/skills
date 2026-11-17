#!/usr/bin/env python3
"""pr-pulse-nudge.py <session id> <name> <cwd> <what> — one notification saying a Claude session
is waiting for the user, with an explicit "Open session" button. Started by the daemon."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import core       # noqa: E402
import sessionui  # noqa: E402


def main(argv):
    sid, name, cwd, what = (argv + ["", "", "", ""])[:4]
    _, slug, _ = core.repo_of(cwd) if cwd else (None, None, None)
    where = slug or (Path(cwd).name if cwd else "")
    msg = f"{name} is waiting for you ({what})." + (f"\n{where}" if where else "")
    if core.use_alerter():
        out = subprocess.run(["alerter", "--title", "Claude needs you", "--subtitle", name, "--message", msg,
                              "--actions", sessionui_label(), "--close-label", "Later",
                              "--group", f"pr-pulse-wait-{sid[:8]}", "--json", "--timeout", "3600",
                              "--sound", "default"] + core.icon_args(), capture_output=True, text=True).stdout
        try:
            r = json.loads(out or "{}")
        except ValueError:
            return 0
        if r.get("activationType") == "actionClicked" and r.get("activationValue") == sessionui_label():
            sessionui.open_session(sid, name)
    else:
        safe = msg.replace('"', '\\"')
        out = subprocess.run(["osascript", "-e", f'display dialog "{safe}" with title "Claude needs you" '
                              f'buttons {{"Later", "Open session"}} giving up after 3600'],
                             capture_output=True, text=True).stdout
        if "Open session" in out:
            sessionui.open_session(sid, name)
    return 0


def sessionui_label():
    return "Open session"


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
