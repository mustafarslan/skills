"""park: put every Claude session on this Mac to rest, and bring them back later.

  park doctor                               can park run here? (claude, Terminal permission, store)
  park plan [--only X]… [--exclude X]… [--label L]
                                            inventory + snapshot into a new park (nothing is stopped)
  park note --park N --sid S < text         a session's own "next action" note (with --notes)
  park shutdown --park N                    stop everything, in a detached coordinator
  park cancel --park N                      drop a planned park
  park list [--json]                        parks within retention
  park show [--park N]                      one park's sessions (default: newest)
  park pick [--park N] [--day D] [--name X] [--unresumed]
                                            what --resume would bring back, as JSON
  park resume --park N [--sid S]…           reopen sessions (all unresumed in park N, or the given ones)
  park gc                                   delete parks older than retention_days
  park config [KEY [VALUE]]                 show or set a setting

PARK_HOME overrides ~/.claude/park.
"""
import datetime as dt
import json
import os
import shlex
import signal
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import db          # noqa: E402
import inventory   # noqa: E402
import snapshot    # noqa: E402
import terminal    # noqa: E402

PR_PULSE = Path.home() / ".claude" / "pr-pulse" / "app" / "scripts" / "pr-pulse"
PR_PULSE_DB = Path.home() / ".claude" / "pr-pulse" / "pulse.db"


def log(msg):
    print(msg, flush=True)


def opt(args, name, default=None):
    return args[args.index(name) + 1] if name in args and args.index(name) + 1 < len(args) else default


def opts(args, name):
    return [args[i + 1] for i, a in enumerate(args) if a == name and i + 1 < len(args)]


# ---- plan -----------------------------------------------------------------------------------

def plan(con, only=(), exclude=(), label=None, self_sid=None, sessions=None, table=None, now=None, me=None):
    """Snapshot every live session into a new park. Stops nothing. Returns the summary dict."""
    now = now or time.time()
    table = inventory.process_table() if table is None else table
    inv = inventory.inventory(only, exclude, sessions, table)
    if not self_sid:
        # CLAUDE_CODE_SESSION_ID unset: the session running /park is the one whose pid is among our parents.
        # Without it the coordinator could stop that session mid-reply instead of last.
        mine = inventory.ancestors(table, os.getpid() if me is None else me)
        mine |= {table[p][0] for p in mine if p in table}     # and the parent of the topmost one we know
        self_sid = next((s["sid"] for s in inv if s["pid"] and int(s["pid"]) in mine), None)
    cur = con.execute("INSERT INTO parks(at, label, parked_by, partial) VALUES(?,?,?,?)",
                      (now, label, self_sid, int(bool(only or exclude))))
    park_id = cur.lastrowid
    summary = {"park": park_id, "parked": [], "skipped": [], "busy": [], "long_running": []}
    for s in inv:
        tp = snapshot.transcript(s["sid"])
        g = snapshot.git_state(s["cwd"], db.patches_dir(park_id) / f"{s['sid']}.patch")
        rearm = [{"kind": c["kind"], "command": snapshot.normalize(c["command"])}
                 for c in s["commands"] if c["kind"] in ("monitor", "shell")]
        if s["pr_pulse_joined"] and not any("inbox-watch.sh" in r["command"] for r in rearm):
            watch = snapshot.current_pr_pulse_watch()
            if watch:   # a joined PR session always gets its pr-pulse inbox watcher back
                rearm.append({"kind": "monitor", "command": f"{watch} {s['sid']}"})
        long_ = [c["command"] for c in s["commands"] if c["kind"] == "long"]
        not_restarted = [c["command"] if len(c["command"]) <= 200 else c["command"][:200] + " …"
                         for c in s["commands"] if c["kind"] in ("oneoff", "partial")]
        row = {"park_id": park_id, "sid": s["sid"], "name": s["name"], "kind": s["kind"], "pid": s["pid"],
               "tty": inventory.tty_of(s["pid"]) if s["kind"] == "interactive" and s["pid"] else "",
               "cwd": s["cwd"], **g, "untracked": json.dumps(g["untracked"]),
               "status_at_park": s["status"], "long_running": json.dumps(long_),
               "skipped_reason": s["skipped_reason"], "rearm": json.dumps(rearm),
               "crons": json.dumps(snapshot.crons(tp, now)), "last_message": snapshot.last_message(tp)}
        row["resume_prompt"] = snapshot.resume_prompt(row, now)
        cols = list(row)
        con.execute(f"INSERT INTO sessions({','.join(cols)}) VALUES({','.join('?' * len(cols))})",
                    [row[c] for c in cols])
        item = {"sid": s["sid"], "name": s["name"], "kind": s["kind"], "status": s["status"],
                "cwd": s["cwd"], "branch": g["branch"], "dirty": g["dirty"], "rearm": len(rearm),
                "crons": len(json.loads(row["crons"])), "self": s["sid"] == self_sid,
                "restart": [r["command"] for r in rearm],
                "not_restarted": not_restarted,
                "cron_prompts": [c["prompt"] for c in json.loads(row["crons"])],
                "untracked": len(g["untracked"])}
        if s["skipped_reason"]:
            summary["skipped"].append({**item, "reason": s["skipped_reason"]})
            continue
        summary["parked"].append(item)
        if s["status"] == "busy" and s["sid"] != self_sid:
            summary["busy"].append(s["name"])
        if long_:
            summary["long_running"].append({"name": s["name"], "commands": long_})
    summary["self"] = self_sid
    db.event(con, "park.planned", {"park": park_id, "sessions": len(summary["parked"])})
    return summary


def note(con, park_id, sid, text):
    row = con.execute("SELECT * FROM sessions WHERE park_id=? AND sid=?", (park_id, sid)).fetchone()
    if not row:
        raise SystemExit(f"no session {sid} in park {park_id}")
    at = con.execute("SELECT at FROM parks WHERE id=?", (park_id,)).fetchone()["at"]
    data = dict(row, note=text.strip())
    con.execute("UPDATE sessions SET note=?, resume_prompt=? WHERE park_id=? AND sid=?",
                (data["note"], snapshot.resume_prompt(data, at), park_id, sid))


# ---- shutdown -------------------------------------------------------------------------------

def pr_pulse_is_on():
    if not PR_PULSE.exists() or not PR_PULSE_DB.exists():
        return False
    out = inventory.run(["sqlite3", str(PR_PULSE_DB), "SELECT value FROM settings WHERE key='stopped'"]) or ""
    return out.strip() != "1"


def alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError, TypeError):
        return False


def wait_gone(pid, seconds):
    end = time.time() + seconds
    while time.time() < end:
        if not alive(pid):
            return True
        time.sleep(0.5)
    return not alive(pid)


def wait_quiet(path, seconds, quiet=2.0):
    """Wait until the transcript has not changed for `quiet` seconds (a cancelled turn has flushed)."""
    if not path:
        time.sleep(min(seconds, quiet))
        return
    end = time.time() + seconds
    while time.time() < end:
        try:
            if time.time() - path.stat().st_mtime >= quiet:
                return
        except OSError:
            return
        time.sleep(0.5)


def wait_idle(sid, seconds):
    end = time.time() + seconds
    while time.time() < end:
        s = next((s for s in inventory.claude_sessions() if s.get("sessionId") == sid), None)
        if not s or s.get("status") != "busy":
            return
        time.sleep(2)


def send(pid, sig):
    """Signal a pid. A process that exited in the meantime (or one we may not signal) is not an error:
    it must never abort the coordinator half-way, with pr-pulse off and sessions still up."""
    try:
        os.kill(int(pid), sig)
        return True
    except (OSError, ValueError, TypeError):
        return False


def stop_interactive(row, busy_wait):
    """SIGINT (cancels a running turn; an idle session exits on it), wait for the transcript to settle,
    then SIGTERM if it is still there. Returns how it ended."""
    pid = row["pid"]
    if not pid or not alive(pid) or not send(pid, signal.SIGINT):
        return "already gone"
    wait_quiet(snapshot.transcript(row["sid"]), busy_wait if row["status_at_park"] == "busy" else 3)
    if wait_gone(pid, 3):
        return "stopped"
    send(pid, signal.SIGINT)
    if wait_gone(pid, 3):
        return "stopped"
    send(pid, signal.SIGTERM)
    return "stopped" if wait_gone(pid, 10) else "still running"


def verify(row, live):
    """(row with the session's current status, None) when its pid still belongs to this Claude session,
    else (None, why). A pid saved at plan time may since have exited or been reused by another process:
    only a pid that `claude agents` still reports for this session id is ever signalled."""
    if not live:
        return None, "not stopped: could not list running sessions to check its pid"
    cur = live.get(row["sid"])
    if not cur or not cur.get("pid"):
        return None, "already gone"
    if int(cur["pid"]) != int(row["pid"] or 0):
        return None, f"not stopped: its pid changed ({row['pid']} -> {cur['pid']})"
    return dict(row, status_at_park=cur.get("status") or row["status_at_park"]), None


def coordinate(con, park_id, self_pid=None, live=None):
    """The detached shutdown. Order: pr-pulse off, background sessions, interactive sessions,
    the session that ran /park last, then Terminal."""
    cfg = db.config(con)
    live = {s.get("sessionId"): s for s in (inventory.claude_sessions() if live is None else live)}
    park = con.execute("SELECT * FROM parks WHERE id=?", (park_id,)).fetchone()
    rows = [dict(r) for r in con.execute("SELECT * FROM sessions WHERE park_id=? AND skipped_reason IS NULL",
                                         (park_id,))]
    con.execute("UPDATE parks SET status='parking' WHERE id=?", (park_id,))
    partial = bool(park["partial"])     # a few sessions only: pr-pulse and other windows are left alone
    was_on = pr_pulse_is_on() and not partial
    if was_on:
        inventory.run([str(PR_PULSE), "stop"], timeout=60)
    con.execute("UPDATE parks SET pr_pulse_was_on=? WHERE id=?", (int(was_on), park_id))
    db.event(con, "park.pr_pulse", {"park": park_id, "was_on": was_on})
    results = {}
    if not partial:
        # pr-pulse's own workers are not reopened (pr-pulse requeues their jobs), but a full park still
        # stops the running ones, so nothing keeps working while pr-pulse is off.
        for w in con.execute("SELECT sid FROM sessions WHERE park_id=? AND pid IS NOT NULL AND "
                             "skipped_reason LIKE 'pr-pulse worker%'", (park_id,)):
            inventory.run(["claude", "stop", w["sid"][:8]], timeout=60)
            db.event(con, "park.stopped_pr_pulse_worker", {"sid": w["sid"]})
    for r in [r for r in rows if r["kind"] == "background"]:
        try:
            ok = inventory.run(["claude", "stop", r["sid"][:8]], timeout=60) is not None
            results[r["sid"]] = "stopped" if ok else "claude stop failed"
        except Exception as e:      # one session failing must not leave the rest running
            results[r["sid"]] = f"error: {e}"
    me = park["parked_by"]
    inter = [r for r in rows if r["kind"] != "background"]
    for r in sorted(inter, key=lambda r: r["sid"] == me):      # the /park session goes last
        try:
            if r["sid"] == me:
                wait_idle(me, 60)      # let it finish its last reply before it is stopped
            checked, why = verify(r, live)
            if why:
                results[r["sid"]] = why
                continue
            if r["sid"] == me:
                checked = dict(checked, status_at_park="idle")
            results[r["sid"]] = stop_interactive(checked, int(cfg.get("busy_wait_s") or 20))
        except Exception as e:
            results[r["sid"]] = f"error: {e}"
    for sid, how in results.items():
        con.execute("UPDATE sessions SET stopped=? WHERE park_id=? AND sid=?",
                    (int(how in ("stopped", "already gone")), park_id, sid))
    db.event(con, "park.stopped", {"park": park_id, "results": results})
    mode = "claude" if partial and cfg.get("quit_terminal", "all") == "all" else cfg.get("quit_terminal", "all")
    failed = [s for s, how in results.items() if how not in ("stopped", "already gone")]
    done = {s for s, how in results.items() if how in ("stopped", "already gone")}
    # A session that was not stopped is still running in its window: quitting Terminal would cut it off
    # without park's careful stop. Then Terminal stays open and only the stopped sessions' windows close.
    if mode == "all" and any(r["sid"] in failed for r in inter):
        mode = "claude"
        db.event(con, "park.terminal_kept", {"park": park_id, "not_stopped": failed})
    if mode == "all":
        terminal.quit_terminal()
    elif mode == "claude":
        terminal.close_windows([r["tty"] for r in inter if r.get("tty") and r["sid"] in done])
    con.execute("UPDATE parks SET status='parked' WHERE id=?", (park_id,))
    n = len(results) - len(failed)
    terminal.notify(f"Parked {n} session(s)." + (f" {len(failed)} didn't stop, so Terminal stays open: see park show."
                                                  if failed else "")
                    + " Run /park --resume to bring them back.")
    return results


def start_shutdown(park_id):
    """Run the coordinator detached, so it outlives the session that started it (that one is parked too)."""
    logf = open(db.home() / "coordinator.log", "a")
    subprocess.Popen([sys.executable, str(HERE / "park.py"), "coordinate", str(park_id)],
                     stdin=subprocess.DEVNULL, stdout=logf, stderr=logf, start_new_session=True,
                     env=dict(os.environ))


# ---- pick and resume ------------------------------------------------------------------------

def running_sids():
    """Sessions that are actually running. `claude agents` also lists stopped background sessions
    (no pid), and after a reboot every parked one looks like that: they must still be resumable."""
    return [s.get("sessionId") for s in inventory.claude_sessions() if s.get("pid")]


def day_of(ts):
    return dt.date.fromtimestamp(ts).isoformat()


def parse_day(s, today=None):
    today = today or dt.date.today()
    if s in ("today",):
        return today.isoformat()
    if s in ("yesterday",):
        return (today - dt.timedelta(days=1)).isoformat()
    return dt.date.fromisoformat(s).isoformat()


def candidates(con, park=None, day=None, name=None, unresumed=False, live_sids=None):
    """What a resume would reopen. Returns {"park": id or None, "sessions": [...]} or
    {"choose": [parks]} when a day holds several parks."""
    live = set(live_sids or [])
    parks = [dict(p) for p in con.execute("SELECT * FROM parks WHERE status='parked' ORDER BY at DESC")]
    q = "SELECT s.*, p.at AS parked_at FROM sessions s JOIN parks p ON p.id=s.park_id WHERE p.status='parked' AND s.skipped_reason IS NULL"
    if park:
        rows = con.execute(q + " AND s.park_id=?", (park,)).fetchall()
        chosen = park
    elif day:
        on_day = [p for p in parks if day_of(p["at"]) == day]
        if not on_day:
            return {"park": None, "sessions": [], "message": f"no park on {day}"}
        if len(on_day) > 1:
            return {"choose": [_park_line(con, p) for p in on_day]}
        chosen = on_day[0]["id"]
        rows = con.execute(q + " AND s.park_id=?", (chosen,)).fetchall()
    elif name or unresumed:
        rows = con.execute(q + " ORDER BY p.at DESC").fetchall()
        chosen = None
    else:
        chosen = next((p["id"] for p in parks if con.execute(
            "SELECT 1 FROM sessions WHERE park_id=? AND skipped_reason IS NULL AND resumed_at IS NULL",
            (p["id"],)).fetchone()), None)
        if chosen is None:
            return {"park": None, "sessions": [], "message": "nothing parked is waiting to be resumed"}
        rows = con.execute(q + " AND s.park_id=?", (chosen,)).fetchall()
    out, seen = [], set()
    for r in rows:
        r = dict(r)
        if r["sid"] in seen:
            continue                      # newest park wins for a session parked twice
        seen.add(r["sid"])
        if name and name.lower() not in (r["name"] or "").lower():
            continue
        if (unresumed or not park) and r["resumed_at"] and not name:
            continue
        out.append(describe(r, live))
    return {"park": chosen, "sessions": out}


def describe(r, live):
    cwd, warn = r["cwd"], ""
    if not cwd or not Path(cwd).is_dir():
        fallback = r["repo_root"] if r["repo_root"] and Path(r["repo_root"]).is_dir() else str(Path.home())
        warn = f"{cwd or '(no folder)'} is gone; opens in {fallback}"
        cwd = fallback
    drift = ""
    if r["repo_root"] and Path(cwd).is_dir():
        head = snapshot.git(cwd, "rev-parse", "--short", "HEAD")
        branch = snapshot.git(cwd, "rev-parse", "--abbrev-ref", "HEAD")
        if (branch, head) != (r["branch"], r["head"]):
            drift = f"was {r['branch']}@{r['head']}, now {branch}@{head}"
    return {"park": r["park_id"], "sid": r["sid"], "name": r["name"], "kind": r["kind"], "cwd": cwd,
            "warning": warn, "drift": drift, "branch": r["branch"], "head": r["head"],
            "rearm": len(json.loads(r["rearm"] or "[]")), "crons": len(json.loads(r["crons"] or "[]")),
            "untracked": len(json.loads(r.get("untracked") or "[]")),
            "resumed_at": r["resumed_at"], "running_now": r["sid"] in live,
            "parked_at": time.strftime("%Y-%m-%d %H:%M", time.localtime(r["parked_at"]))}


def _park_line(con, p):
    n = con.execute("SELECT COUNT(*) FROM sessions WHERE park_id=? AND skipped_reason IS NULL", (p["id"],)).fetchone()[0]
    done = con.execute("SELECT COUNT(*) FROM sessions WHERE park_id=? AND resumed_at IS NOT NULL", (p["id"],)).fetchone()[0]
    return {"park": p["id"], "at": time.strftime("%Y-%m-%d %H:%M", time.localtime(p["at"])),
            "label": p["label"], "sessions": n, "resumed": done, "status": p["status"]}


def resume(con, park_id=None, sids=(), live_sids=None, opener=None, bg_runner=None):
    """Reopen sessions. Interactive: a new Terminal window each, `claude --resume <sid> <prompt>`.
    Background: `claude --bg --resume <sid> <prompt>`. No other flags: any flag forks a new session."""
    live = set(live_sids or [])
    opener = opener or terminal.open_window
    bg_runner = bg_runner or (lambda args, cwd: inventory.run(args, cwd=cwd, timeout=60) is not None)
    q = "SELECT s.*, p.at AS parked_at, p.pr_pulse_was_on FROM sessions s JOIN parks p ON p.id=s.park_id WHERE s.skipped_reason IS NULL"
    if sids:
        rows = [con.execute(q + " AND s.sid=? ORDER BY p.at DESC", (s,)).fetchone() for s in sids]
        rows = [dict(r) for r in rows if r]
    else:
        rows = [dict(r) for r in con.execute(q + " AND s.park_id=? AND s.resumed_at IS NULL", (park_id,))]
    results, pr_pulse = [], False
    for r in rows:
        d = describe(r, live)
        if d["running_now"]:
            results.append((r["name"], "already running, left alone"))
            continue
        prompt = r["resume_prompt"] or ""
        if r["kind"] == "background":
            ok = bg_runner(["claude", "--bg", "--resume", r["sid"], prompt], d["cwd"])
        else:
            ok = opener(f"cd {shlex.quote(d['cwd'])} && claude --resume {shlex.quote(r['sid'])} {shlex.quote(prompt)}")
        if ok:
            con.execute("UPDATE sessions SET resumed_at=? WHERE park_id=? AND sid=?", (time.time(), r["park_id"], r["sid"]))
            pr_pulse = pr_pulse or bool(r["pr_pulse_was_on"])
        results.append((r["name"], ("resumed" if ok else "failed to open") + (f" ({d['warning']})" if d["warning"] else "")
                        + (f"; drift: {d['drift']}" if d["drift"] else "")))
    if pr_pulse and PR_PULSE.exists() and not pr_pulse_is_on():
        inventory.run([str(PR_PULSE), "start"], timeout=60)
        results.append(("pr-pulse", "switched back on"))
    db.event(con, "park.resumed", {"park": park_id, "results": results})
    return results


# ---- cli ------------------------------------------------------------------------------------

def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    cmd, args = argv[0], argv[1:]
    con = db.connect()
    if cmd != "coordinate":
        removed = db.gc(con)
        if removed:
            log(f"(cleaned up {removed} park(s) older than {db.config(con)['retention_days']} days)")
    if cmd == "doctor":
        problems = []
        if not inventory.run(["claude", "--version"]):
            problems.append("claude is not on PATH")
        ok, why = terminal.can_control()
        if not ok:
            problems.append(why)
        print(json.dumps({"ok": not problems, "problems": problems, "store": str(db.home()),
                          "pr_pulse": PR_PULSE.exists(), "config": db.config(con)}, indent=1))
        return 0 if not problems else 1
    if cmd == "plan":
        s = plan(con, opts(args, "--only"), opts(args, "--exclude"), opt(args, "--label"),
                 os.environ.get("CLAUDE_CODE_SESSION_ID"))
        print(json.dumps(s, indent=1))
        return 0
    if cmd == "note":
        note(con, int(opt(args, "--park")), opt(args, "--sid"), sys.stdin.read())
        log("noted")
        return 0
    if cmd == "shutdown":
        pid = int(opt(args, "--park"))
        if not con.execute("SELECT 1 FROM parks WHERE id=? AND status='planned'", (pid,)).fetchone():
            raise SystemExit(f"park {pid} is not a planned park")
        start_shutdown(pid)
        log(f"Parking now (park {pid}). Sessions close one by one; this one goes last.")
        return 0
    if cmd == "coordinate":
        coordinate(con, int(args[0]))
        return 0
    if cmd == "cancel":
        con.execute("UPDATE parks SET status='cancelled' WHERE id=? AND status='planned'", (int(opt(args, "--park")),))
        log("cancelled")
        return 0
    if cmd == "list":
        parks = [_park_line(con, dict(p)) for p in con.execute("SELECT * FROM parks WHERE status != 'cancelled' ORDER BY at DESC")]
        if "--json" in args:
            print(json.dumps(parks, indent=1))
        else:
            for p in parks:
                log(f"park {p['park']:>3}  {p['at']}  {p['sessions']} session(s), {p['resumed']} resumed  {p['status']}"
                    + (f"  {p['label']}" if p["label"] else ""))
        return 0
    if cmd == "show":
        pid = opt(args, "--park") or (con.execute("SELECT id FROM parks ORDER BY at DESC LIMIT 1").fetchone() or [None])[0]
        rows = [dict(r) for r in con.execute("SELECT * FROM sessions WHERE park_id=?", (pid,))]
        print(json.dumps(rows, indent=1, default=str))
        return 0
    if cmd == "pick":
        live = running_sids()
        day = parse_day(opt(args, "--day")) if opt(args, "--day") else None
        print(json.dumps(candidates(con, int(opt(args, "--park")) if opt(args, "--park") else None, day,
                                    opt(args, "--name"), "--unresumed" in args, live), indent=1))
        return 0
    if cmd == "resume":
        live = running_sids()
        park_id = int(opt(args, "--park")) if opt(args, "--park") else None
        for name, how in resume(con, park_id, opts(args, "--sid"), live):
            log(f"{name}: {how}")
        terminal.notify("Sessions are back. Each one checks its folder and restarts its watchers first.")
        return 0
    if cmd == "gc":
        log("cleanup done")
        return 0
    if cmd == "config":
        if len(args) >= 2:
            try:
                val = json.loads(args[1])
            except ValueError:
                val = args[1]
            db.set_config(con, args[0], val)
        print(json.dumps(db.config(con), indent=1))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
