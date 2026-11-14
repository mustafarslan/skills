"""What a parked session needs to come back: its worktree state, what was running inside it, its crons,
and the prompt that tells the resumed session to check drift and start that work again."""
import json
import re
import time
from pathlib import Path

import inventory

CRON_TTL_S = 7 * 86400          # session crons auto-expire after 7 days
JOB_ID_RE = re.compile(r"job ([0-9a-f]{6,})")
PR_PULSE_WATCH = re.compile(r"\S*pr-pulse\S*/scripts/inbox-watch\.sh")


def git(cwd, *args):
    return (inventory.run(["git", "-C", cwd, *args]) or "").strip()


def git_state(cwd, patch_file):
    """Branch, HEAD, dirty files and unpushed commits. Uncommitted work is copied to a patch;
    nothing is committed, stashed or pushed."""
    st = {"repo_root": "", "branch": "", "head": "", "dirty": 0, "patch_path": None,
          "untracked": [], "unpushed": 0}
    if not cwd or not Path(cwd).is_dir():
        return st
    root = git(cwd, "rev-parse", "--show-toplevel")
    if not root:
        return st
    st["repo_root"] = root
    st["branch"] = git(cwd, "rev-parse", "--abbrev-ref", "HEAD")
    st["head"] = git(cwd, "rev-parse", "--short", "HEAD")
    status = git(cwd, "status", "--porcelain")
    st["untracked"] = [l[3:] for l in status.splitlines() if l.startswith("??")]
    st["dirty"] = len(status.splitlines())
    ahead = git(cwd, "rev-list", "--count", "@{u}..HEAD")
    st["unpushed"] = int(ahead) if ahead.isdigit() else 0
    # --binary keeps binary changes; with no commit yet (unborn HEAD) the staged work is what can be saved.
    base = ["diff", "--binary", "HEAD"] if st["head"] and st["head"] != "HEAD" else ["diff", "--binary", "--cached"]
    diff = inventory.run(["git", "-C", cwd, *base]) or ""
    if diff.strip():
        Path(patch_file).parent.mkdir(parents=True, exist_ok=True)
        Path(patch_file).write_text(diff)
        st["patch_path"] = str(patch_file)
    return st


def transcript(sid, projects=None):
    root = Path(projects or Path.home() / ".claude" / "projects")
    hits = sorted(root.glob(f"*/{sid}.jsonl"), key=lambda p: p.stat().st_mtime)
    return hits[-1] if hits else None


def _lines(path):
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                yield json.loads(line)
            except ValueError:
                continue


def crons(path, now=None):
    """Session crons still alive: created, not deleted, not expired, not a one-shot that already fired."""
    if not path:
        return []
    now = now or time.time()
    created, deleted, ids = {}, set(), {}
    for row in _lines(path):
        content = (row.get("message") or {}).get("content")
        for c in content if isinstance(content, list) else []:
            if c.get("type") == "tool_use" and c.get("name") == "CronCreate":
                created[c.get("id")] = {"input": c.get("input") or {}, "at": row.get("timestamp")}
            elif c.get("type") == "tool_use" and c.get("name") == "CronDelete":
                deleted.add((c.get("input") or {}).get("id"))
            elif c.get("type") == "tool_result" and c.get("tool_use_id") in created:
                m = JOB_ID_RE.search(json.dumps(c.get("content")))
                if m:
                    ids[c["tool_use_id"]] = m.group(1)
    out = []
    for tu, info in created.items():
        jid = ids.get(tu)
        if jid and jid in deleted:
            continue
        at = _ts(info.get("at"))
        if at and now - at > CRON_TTL_S:
            continue
        inp = info["input"]
        if not inp.get("recurring", True) and at and now - at > 3600:
            continue        # a one-shot: it has fired (or was meant to) long ago
        out.append({"cron": inp.get("cron", ""), "recurring": bool(inp.get("recurring", True)),
                    "prompt": inp.get("prompt", "")})
    return out


def _ts(s):
    if not s:
        return None
    try:
        from datetime import datetime
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def last_message(path, limit=600):
    """The session's last words to the user: usually where it stopped and what comes next."""
    if not path:
        return ""
    last = ""
    for row in _lines(path):
        if row.get("type") != "assistant":
            continue
        for c in (row.get("message") or {}).get("content") or []:
            if isinstance(c, dict) and c.get("type") == "text" and c.get("text", "").strip():
                last = c["text"].strip()
    return last if len(last) <= limit else last[:limit].rsplit(" ", 1)[0] + " …"


def current_pr_pulse_watch():
    p = Path.home() / ".claude" / "pr-pulse" / "app" / "scripts" / "inbox-watch.sh"
    return str(p) if p.exists() else None


def normalize(command):
    """A pr-pulse inbox watcher from an older or development copy points at today's copy."""
    now = current_pr_pulse_watch()
    return PR_PULSE_WATCH.sub(now, command) if now else command


def code(s):
    """Text for a `code span` in the prompt. A command with a backtick or a newline can't sit in one
    without changing its meaning or spilling into the instructions around it: give it as a JSON string."""
    s = str(s)
    return f"`{s}`" if "`" not in s and "\n" not in s and "\r" not in s else "(JSON string) " + json.dumps(s)


def one_line(s):
    return " ".join(str(s).split())


def resume_prompt(row, parked_at):
    """The first message a resumed session gets: check, re-arm, recreate, continue."""
    when = time.strftime("%Y-%m-%d %H:%M", time.localtime(parked_at))
    # Never start with "/": Claude Code would read the whole prompt as a slash command.
    lines = [f"Resumed by park (this session was parked {when}). Before anything else:"]
    n = 1
    if row.get("repo_root"):
        want = f"branch {row['branch']} at {row['head']}"
        extra = []
        if row.get("dirty"):
            extra.append(f"{row['dirty']} changed file(s)" + (f", saved in {row['patch_path']}" if row.get("patch_path") else ""))
        if row.get("unpushed"):
            extra.append(f"{row['unpushed']} unpushed commit(s)")
        untracked = json.loads(row.get("untracked") or "[]") if isinstance(row.get("untracked"), str) else (row.get("untracked") or [])
        if untracked:
            shown = ", ".join(one_line(u) for u in untracked[:10]) + (" …" if len(untracked) > 10 else "")
            extra.append(f"{len(untracked)} untracked file(s), not in the patch: {shown}")
        lines.append(f"{n}. Check {code(row['cwd'])} is still on {want}" + (f" ({'; '.join(extra)})" if extra else "") +
                     ". Report any drift in one line. Never reset, stash or overwrite to make it match; ask me.")
        n += 1
    rearm = [r for r in json.loads(row.get("rearm") or "[]") if r["kind"] in ("monitor", "shell")]
    for r in rearm:
        tool = "the Monitor tool" if r["kind"] == "monitor" else "Bash with run_in_background"
        lines.append(f"{n}. Start again with {tool}: {code(r['command'])}")
        n += 1
    for c in json.loads(row.get("crons") or "[]"):
        lines.append(f"{n}. Recreate with CronCreate: cron {code(c['cron'])}, recurring {str(c['recurring']).lower()}, "
                     f"prompt: {json.dumps(c['prompt'])}")
        n += 1
    long_ = json.loads(row.get("long_running") or "[]")
    if long_:
        lines.append(f"{n}. These were still running when parked and were cut off; don't rerun them on your own, "
                     "tell me: " + "; ".join(code(c) for c in long_))
        n += 1
    if row.get("note"):
        lines.append(f"{n}. Your own note before parking: {one_line(row['note'])}")
        n += 1
    lines.append("Then say in one line what you restarted, and continue where you left off"
                 + (" (your last message is above)." if row.get("last_message") else ".")
                 + " If there was no next step, wait for me.")
    return "\n".join(lines)
