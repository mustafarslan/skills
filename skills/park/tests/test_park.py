"""park unit tests: a temporary store, fake `claude` and `osascript` on PATH, throwaway processes.
Nothing here touches real sessions, Terminal or pr-pulse."""
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TMP = Path(tempfile.mkdtemp(prefix="park-test-"))
os.environ["PARK_HOME"] = str(TMP / "home")
os.environ["PARK_NO_NOTIFY"] = "1"
os.environ["PARK_PR_PULSE_DB"] = str(TMP / "no-pr-pulse.db")
sys.path.insert(0, str(ROOT / "scripts"))
import db         # noqa: E402
import inventory  # noqa: E402
import park       # noqa: E402
import snapshot   # noqa: E402

WRAP = "/bin/zsh -c source /Users/x/.claude/shell-snapshots/snapshot-zsh-1-a.sh 2>/dev/null || true && eval '{}' < /dev/null && pwd -P >| /tmp/c"


def table(*rows):
    return {pid: (ppid, cmd) for pid, ppid, cmd in rows}


class InventoryTest(unittest.TestCase):
    SESSIONS = [
        {"pid": 100, "cwd": "/w/app", "kind": "interactive", "sessionId": "aaaa1111", "name": "app", "status": "idle"},
        {"pid": 200, "cwd": "/w/app/.claude/worktrees/pr-pulse-o--r-7", "kind": "background",
         "sessionId": "bbbb2222", "name": "pr-o-r-7-review", "status": "busy"},
        {"pid": 300, "cwd": "/w/docs", "kind": "background", "sessionId": "cccc3333", "name": "docs", "status": "busy"},
    ]
    TABLE = table(
        (101, 100, WRAP.format("/h/.claude/pr-pulse/app/scripts/inbox-watch.sh aaaa1111")),
        (102, 101, "bash /h/.claude/pr-pulse/app/scripts/inbox-watch.sh aaaa1111"),
        (103, 102, "sleep 5"),
        (104, 100, WRAP.format("sleep 30")),
        (105, 100, WRAP.format("npm run dev")),
        (301, 300, WRAP.format("cd apps/backend && pytest -n 2 tests")),
        (900, 1, "/Applications/Other.app/x"),
    )

    def test_commands_and_kinds(self):
        cmds = inventory.tool_commands(self.TABLE, 100, me=999)
        self.assertEqual(cmds, [{"kind": "shell", "command": "npm run dev"},
                                {"kind": "monitor", "command": "/h/.claude/pr-pulse/app/scripts/inbox-watch.sh aaaa1111"}]
                         if cmds[0]["command"] == "npm run dev" else
                         [{"kind": "monitor", "command": "/h/.claude/pr-pulse/app/scripts/inbox-watch.sh aaaa1111"},
                          {"kind": "shell", "command": "npm run dev"}])
        self.assertEqual(inventory.tool_commands(self.TABLE, 300, me=999),
                         [{"kind": "long", "command": "cd apps/backend && pytest -n 2 tests"}])

    def test_own_command_is_never_captured(self):
        t = dict(self.TABLE)
        t[110] = (100, WRAP.format("./park plan"))
        t[111] = (110, "python3 park.py plan")
        cmds = [c["command"] for c in inventory.tool_commands(t, 100, me=111)]
        self.assertNotIn("./park plan", cmds)

    def test_pr_pulse_workers_skipped_user_sessions_kept(self):
        inv = {s["name"]: s for s in inventory.inventory(sessions=self.SESSIONS, table=self.TABLE)}
        self.assertIn("pr-pulse worker", inv["pr-o-r-7-review"]["skipped_reason"])
        self.assertIsNone(inv["app"]["skipped_reason"])
        self.assertIsNone(inv["docs"]["skipped_reason"])

    def test_stopped_background_sessions_are_not_parked(self):
        stopped = [{"pid": None, "cwd": "/w/x", "kind": "background", "sessionId": "dddd4444", "name": "old",
                    "status": None}]
        inv = inventory.inventory(sessions=self.SESSIONS + stopped, table=self.TABLE)
        reasons = {s["name"]: s["skipped_reason"] for s in inv}
        self.assertIn("not running", reasons["old"])
        self.assertIsNone(reasons["docs"])

    def test_only_and_exclude(self):
        inv = {s["name"]: s for s in inventory.inventory(only=["doc"], sessions=self.SESSIONS, table=self.TABLE)}
        self.assertEqual(inv["app"]["skipped_reason"], "not in --only")
        self.assertIsNone(inv["docs"]["skipped_reason"])
        inv = {s["name"]: s for s in inventory.inventory(exclude=["aaaa"], sessions=self.SESSIONS, table=self.TABLE)}
        self.assertEqual(inv["app"]["skipped_reason"], "in --exclude")
        self.assertIsNone(inv["docs"]["skipped_reason"])


def wrap_real(command):
    """A wrapper line as ps shows it: quotes written '"'"', newlines as \012."""
    inner = command.replace("'", "'\"'\"'").replace("\n", "\\012")
    return ("/bin/zsh -c source /Users/x/.claude/shell-snapshots/snapshot-zsh-1-a.sh 2>/dev/null || true && "
            "{ \\builtin unalias -- 'which'; } >/dev/null 2>&1 || true && eval '" + inner +
            "' < /dev/null && pwd -P >| /tmp/c")


class CaptureTest(unittest.TestCase):
    def test_nested_quotes_come_back_whole(self):
        cmd = "cd /w; grep -o '\"[a-z_]*\"' facts.json | sort; timeout 118 bash -c 'until grep -q X f; do sleep 5; done'"
        self.assertEqual(inventory.eval_command(wrap_real(cmd)), cmd)

    def test_a_heredoc_without_dev_null_is_whole(self):
        cmd = "python3 - <<'E'\nprint('x')\nE"
        line = wrap_real(cmd).replace("' < /dev/null && pwd", "' && pwd")
        self.assertEqual(inventory.eval_command(line), cmd)

    def test_a_cut_off_line_is_never_a_command(self):
        line = wrap_real("while true; do curl -s localhost:3000; sleep 5; done")
        self.assertIsNone(inventory.eval_command(line[:line.index("< /dev/null") - 10]))
        t = {1: (100, line[:line.index("< /dev/null") - 10])}
        kinds = [c["kind"] for c in inventory.tool_commands(t, 100, me=999)]
        self.assertEqual(kinds, ["partial"])

    def test_kinds(self):
        cases = {
            "python3 - <<'EOF'\nprint(1)\nEOF": "oneoff",                       # inline script
            "until ! pgrep -f x >/dev/null; do sleep 10; done; tail -8 log": "oneoff",   # a wait that ends
            "for i in $(seq 1 50); do grep -q done log && break; sleep 10; done": "oneoff",
            "cd /w && tools/test.sh BoyAndBubble.Backpack.Model > log 2>&1": "long",
            "/tmp/s/batch-ship-queue.sh lanesb 46,90 lane-sync-head > run.log": "long",
            "xcodebuild -scheme App test": "long",
            "while true; do gh pr checks 5; sleep 60; done": "monitor",
            "/h/.claude/pr-pulse/app/scripts/inbox-watch.sh s1": "monitor",
            "tail -F server.log": "monitor",
            "npm run dev": "shell",
            "awk '{print $1}' f": "oneoff",
        }
        for cmd, kind in cases.items():
            self.assertEqual(inventory.classify(cmd), kind, cmd)

    def test_only_watchers_and_servers_are_restarted(self):
        t = {1: (100, wrap_real("tools/test.sh A > log")), 2: (100, wrap_real("until x; do sleep 1; done; cat log")),
             3: (100, wrap_real("npm run dev")), 4: (100, wrap_real("while true; do date; sleep 9; done"))}
        con = db.connect(TMP / f"k{time.time_ns()}.db")
        s = park.plan(con, sessions=[{"pid": 100, "cwd": "/w/none", "kind": "interactive", "sessionId": "k1",
                                      "name": "k", "status": "idle"}], table=t, self_sid="other")
        k = s["parked"][0]
        self.assertEqual(sorted(k["restart"]), ["npm run dev", "while true; do date; sleep 9; done"])
        self.assertEqual(k["not_restarted"], ["until x; do sleep 1; done; cat log"])
        self.assertEqual(s["long_running"], [{"name": "k", "commands": ["tools/test.sh A > log"]}])


class TranscriptTest(unittest.TestCase):
    def write(self, rows):
        p = TMP / f"t{time.time_ns()}.jsonl"
        p.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
        return p

    def tool_use(self, tid, name, inp, ts):
        return {"type": "assistant", "timestamp": ts, "message": {"content": [
            {"type": "tool_use", "id": tid, "name": name, "input": inp}]}}

    def result(self, tid, text):
        return {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": tid, "content": text}]}}

    def test_live_crons_kept_deleted_and_expired_dropped(self):
        now = time.time()
        iso = lambda t: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))
        p = self.write([
            self.tool_use("t1", "CronCreate", {"cron": "*/10 * * * *", "recurring": True, "prompt": "sweep"}, iso(now - 3600)),
            self.result("t1", "Scheduled recurring job 9282baec (Every 10 minutes)."),
            self.tool_use("t2", "CronCreate", {"cron": "0 9 * * *", "recurring": True, "prompt": "old"}, iso(now - 3600)),
            self.result("t2", "Scheduled recurring job 15b8a37e (Every day)."),
            self.tool_use("t3", "CronDelete", {"id": "15b8a37e"}, iso(now - 1800)),
            self.tool_use("t4", "CronCreate", {"cron": "0 * * * *", "recurring": True, "prompt": "stale"}, iso(now - 8 * 86400)),
            self.result("t4", "Scheduled recurring job aaaaaaaa (Every hour)."),
            self.tool_use("t5", "CronCreate", {"cron": "30 14 10 11 *", "recurring": False, "prompt": "once"}, iso(now - 7200)),
            self.result("t5", "Scheduled one-shot job bbbbbbbb."),
        ])
        self.assertEqual([c["prompt"] for c in snapshot.crons(p, now)], ["sweep"])

    def test_last_message(self):
        p = self.write([{"type": "assistant", "message": {"content": [{"type": "text", "text": "first"}]}},
                        {"type": "assistant", "message": {"content": [{"type": "text", "text": "Next: run the tests."}]}}])
        self.assertEqual(snapshot.last_message(p), "Next: run the tests.")

    def test_old_pr_pulse_watcher_points_at_current_copy(self):
        orig = snapshot.current_pr_pulse_watch
        snapshot.current_pr_pulse_watch = lambda: "/h/.claude/pr-pulse/app/scripts/inbox-watch.sh"
        try:
            self.assertEqual(snapshot.normalize("/h/dev/claude-plugins/pr-pulse/scripts/inbox-watch.sh s1"),
                             "/h/.claude/pr-pulse/app/scripts/inbox-watch.sh s1")
            self.assertEqual(snapshot.normalize("/h/.claude/hooks/pr-watch.sh 84"), "/h/.claude/hooks/pr-watch.sh 84")
        finally:
            snapshot.current_pr_pulse_watch = orig


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.con = db.connect(TMP / f"s{time.time_ns()}.db")

    def add_park(self, at, status="parked", sessions=()):
        pid = self.con.execute("INSERT INTO parks(at, status) VALUES(?,?)", (at, status)).lastrowid
        for sid, name, kind in sessions:
            self.con.execute("INSERT INTO sessions(park_id, sid, name, kind, cwd, resume_prompt) VALUES(?,?,?,?,?,?)",
                             (pid, sid, name, kind, str(TMP), f"prompt {sid}"))
        return pid

    def test_gc_keeps_new_drops_old(self):
        now = time.time()
        old = self.add_park(now - 31 * 86400, sessions=[("s-old", "old", "interactive")])
        self.con.execute("UPDATE sessions SET resumed_at=? WHERE sid='s-old'", (now - 30 * 86400,))
        new = self.add_park(now - 29 * 86400, sessions=[("s-new", "new", "interactive")])
        db.patches_dir(old).mkdir(parents=True, exist_ok=True)
        self.assertEqual(db.gc(self.con, now), 1)
        self.assertEqual([r[0] for r in self.con.execute("SELECT id FROM parks")], [new])
        self.assertFalse(db.patches_dir(old).exists())
        self.assertEqual([r[0] for r in self.con.execute("SELECT sid FROM sessions")], ["s-new"])

    def test_gc_never_drops_a_park_with_unresumed_sessions(self):
        now = time.time()
        kept = self.add_park(now - 90 * 86400, sessions=[("s-left", "left", "interactive")])
        db.patches_dir(kept).mkdir(parents=True, exist_ok=True)
        cancelled = self.add_park(now - 90 * 86400, status="cancelled", sessions=[("s-c", "c", "interactive")])
        self.assertEqual(db.gc(self.con, now), 1)
        self.assertEqual([r[0] for r in self.con.execute("SELECT id FROM parks")], [kept])
        self.assertTrue(db.patches_dir(kept).exists())
        self.assertNotIn(cancelled, [r[0] for r in self.con.execute("SELECT id FROM parks")])

    def test_retention_is_configurable(self):
        db.set_config(self.con, "retention_days", 7)
        self.add_park(time.time() - 8 * 86400)
        self.assertEqual(db.gc(self.con), 1)
        with self.assertRaises(KeyError):
            db.set_config(self.con, "nonsense", 1)

    def test_default_pick_is_newest_unresumed_park(self):
        now = time.time()
        a = self.add_park(now - 86400, sessions=[("s1", "one", "interactive")])
        b = self.add_park(now - 3600, sessions=[("s2", "two", "interactive")])
        self.assertEqual(park.candidates(self.con)["park"], b)
        self.con.execute("UPDATE sessions SET resumed_at=? WHERE park_id=?", (now, b))
        self.assertEqual(park.candidates(self.con)["park"], a)
        self.con.execute("UPDATE sessions SET resumed_at=? WHERE park_id=?", (now, a))
        self.assertIsNone(park.candidates(self.con)["park"])

    def test_two_parks_on_one_day_ask_which(self):
        day = time.time() - 86400
        self.add_park(day, sessions=[("s1", "one", "interactive")])
        self.add_park(day + 60, sessions=[("s2", "two", "interactive")])
        out = park.candidates(self.con, day=park.day_of(day))
        self.assertEqual(len(out["choose"]), 2)
        single = self.add_park(time.time() - 3 * 86400, sessions=[("s3", "three", "interactive")])
        self.assertEqual(park.candidates(self.con, day=park.day_of(time.time() - 3 * 86400))["park"], single)

    def test_name_search_across_parks_newest_wins(self):
        now = time.time()
        self.add_park(now - 5 * 86400, sessions=[("s1", "pr-payments", "interactive")])
        newer = self.add_park(now - 86400, sessions=[("s1", "pr-payments", "interactive"), ("s9", "other", "interactive")])
        out = park.candidates(self.con, name="payments")
        self.assertEqual([(s["sid"], s["park"]) for s in out["sessions"]], [("s1", newer)])

    def test_missing_folder_falls_back_to_repo_root(self):
        pid = self.add_park(time.time(), sessions=[("s1", "one", "interactive")])
        self.con.execute("UPDATE sessions SET cwd=?, repo_root=? WHERE sid='s1'", ("/nope/gone", str(TMP)))
        d = park.candidates(self.con, park=pid)["sessions"][0]
        self.assertEqual(d["cwd"], str(TMP))
        self.assertIn("is gone", d["warning"])

    def test_resume_commands_never_fork(self):
        pid = self.add_park(time.time(), sessions=[("s-int", "int", "interactive"), ("s-bg", "bg", "background"),
                                                   ("s-live", "live", "interactive")])
        opened, bg = [], []
        res = dict(park.resume(self.con, pid, live_sids=["s-live"], opener=lambda c: opened.append(c) or True,
                               bg_runner=lambda a, cwd: bg.append(a) or True))
        self.assertEqual(len(opened), 1)
        self.assertIn("claude --resume s-int 'prompt s-int'", opened[0])   # shlex.quote leaves a plain id bare
        self.assertNotIn("--fork", opened[0])
        self.assertEqual(bg, [["claude", "--bg", "--resume", "s-bg", "prompt s-bg"]])
        self.assertEqual(res["live"], "already running, left alone")
        left = [r[0] for r in self.con.execute("SELECT sid FROM sessions WHERE resumed_at IS NULL")]
        self.assertEqual(left, ["s-live"])


class RunningSidsTest(unittest.TestCase):
    def test_stopped_sessions_are_not_running(self):
        orig = inventory.claude_sessions
        inventory.claude_sessions = lambda: [{"sessionId": "up", "pid": 10}, {"sessionId": "down", "pid": None}]
        try:
            self.assertEqual(park.running_sids(), ["up"])
        finally:
            inventory.claude_sessions = orig


class ResumePromptTest(unittest.TestCase):
    def test_prompt_lists_everything_to_restart(self):
        row = {"cwd": "/w/app", "repo_root": "/w/app", "branch": "feat", "head": "abc1234", "dirty": 2,
               "patch_path": "/p/x.patch", "unpushed": 1,
               "rearm": json.dumps([{"kind": "monitor", "command": "inbox-watch.sh s1"},
                                    {"kind": "shell", "command": "npm run dev"}]),
               "crons": json.dumps([{"cron": "*/10 * * * *", "recurring": True, "prompt": "sweep"}]),
               "long_running": json.dumps(["pytest tests"]), "note": "finish the migration", "last_message": "x"}
        p = snapshot.resume_prompt(row, time.time())
        self.assertFalse(p.startswith("/"), "a leading slash makes Claude read the prompt as a command")
        for part in ("branch feat at abc1234", "/p/x.patch", "Never reset", "Monitor tool: `inbox-watch.sh s1`",
                     "run_in_background: `npm run dev`", "CronCreate: cron `*/10 * * * *`", "`pytest tests`",
                     "finish the migration"):
            self.assertIn(part, p)


@unittest.skipIf(sys.platform == "win32", "POSIX processes and a fake osascript; WindowsCoordinatorTest covers Windows")
class CoordinatorTest(unittest.TestCase):
    """The detached shutdown, with fake claude/osascript/pr-pulse and real throwaway processes."""

    def setUp(self):
        self.bin = TMP / f"bin{time.time_ns()}"
        self.bin.mkdir()
        self.calls = self.bin / "calls.log"
        for name in ("claude", "osascript"):
            f = self.bin / name
            f.write_text(f'#!/bin/sh\necho "{name} $*" >> "{self.calls}"\n'
                         + ('echo "[]"\n' if name == "claude" else ""))
            f.chmod(0o755)
        self.path = os.environ["PATH"]
        os.environ["PATH"] = f"{self.bin}:{self.path}"
        self.con = db.connect(TMP / f"c{time.time_ns()}.db")
        db.set_config(self.con, "busy_wait_s", 1)
        # Stand-ins for sessions, detached so they aren't our children (a killed child stays a zombie
        # and still looks alive; real sessions are never park's children either).
        self.procs = [int(subprocess.run(["sh", "-c", "sleep 60 >/dev/null 2>&1 & echo $!"],
                                         capture_output=True, text=True).stdout) for _ in range(2)]
        self.orig_on = park.pr_pulse_is_on
        park.pr_pulse_is_on = lambda: False

    def tearDown(self):
        os.environ["PATH"] = self.path
        park.pr_pulse_is_on = self.orig_on
        for p in self.procs:
            try:
                os.kill(p, signal.SIGKILL)
            except OSError:
                pass

    def test_order_background_first_then_interactive_then_self_then_terminal(self):
        a, me = self.procs
        pid = self.con.execute("INSERT INTO parks(at, parked_by) VALUES(?, 'self')", (time.time(),)).lastrowid
        for sid, kind, ppid in (("self", "interactive", me), ("other", "interactive", a),
                                ("bgsess01", "background", None)):
            self.con.execute("INSERT INTO sessions(park_id, sid, name, kind, pid, status_at_park) VALUES(?,?,?,?,?,'idle')",
                             (pid, sid, sid, kind, ppid))
        self.con.execute("INSERT INTO sessions(park_id, sid, name, kind, pid, skipped_reason) VALUES(?,?,?,?,?,?)",
                         (pid, "workerAA", "worker", "background", 4242, "pr-pulse worker (requeued)"))
        self.con.execute("INSERT INTO sessions(park_id, sid, name, kind, skipped_reason) VALUES(?,?,?,?,?)",
                         (pid, "stoppedB", "old", "background", "not running"))
        order = []
        orig = park.stop_interactive
        park.stop_interactive = lambda r, w: order.append(r["sid"]) or orig(r, w)
        live = [{"sessionId": "self", "pid": me, "status": "idle"}, {"sessionId": "other", "pid": a, "status": "idle"}]
        try:
            res = park.coordinate(self.con, pid, live=live)
        finally:
            park.stop_interactive = orig
        self.assertEqual(order, ["other", "self"])
        self.assertEqual(res["other"], "stopped")
        self.assertEqual(res["self"], "stopped")
        log = self.calls.read_text()
        self.assertIn("claude stop bgsess01", log)
        self.assertIn("claude stop workerAA", log)     # a running pr-pulse worker is stopped, not resumed
        self.assertNotIn("stoppedB", log)
        self.assertLess(log.index("claude stop bgsess01"), log.index("osascript"))
        self.assertIn('tell application "Terminal" to quit', log)
        self.assertEqual(self.con.execute("SELECT status FROM parks WHERE id=?", (pid,)).fetchone()[0], "parked")

    def test_partial_park_leaves_pr_pulse_and_other_windows(self):
        park.pr_pulse_is_on = lambda: True
        a = self.procs[0]
        pid = self.con.execute("INSERT INTO parks(at, partial) VALUES(?, 1)", (time.time(),)).lastrowid
        self.con.execute("INSERT INTO sessions(park_id, sid, name, kind, pid, tty, status_at_park) "
                         "VALUES(?, 'one', 'one', 'interactive', ?, '/dev/ttys099', 'idle')", (pid, a))
        self.con.execute("INSERT INTO sessions(park_id, sid, name, kind, pid, skipped_reason) "
                         "VALUES(?, 'workerAA', 'w', 'background', 4242, 'pr-pulse worker (requeued)')", (pid,))
        park.coordinate(self.con, pid, live=[{"sessionId": "one", "pid": a, "status": "idle"}])
        log = self.calls.read_text()
        self.assertNotIn("to quit", log)
        self.assertIn("/dev/ttys099", log)      # only a window made of its own tabs is closed
        self.assertNotIn("claude stop", log)    # and no pr-pulse worker is touched
        self.assertEqual(self.con.execute("SELECT pr_pulse_was_on FROM parks WHERE id=?", (pid,)).fetchone()[0], 0)

    def test_terminal_left_open_when_configured(self):
        db.set_config(self.con, "quit_terminal", "none")
        pid = self.con.execute("INSERT INTO parks(at) VALUES(?)", (time.time(),)).lastrowid
        park.coordinate(self.con, pid, live=[])
        self.assertFalse(self.calls.exists() and "quit" in self.calls.read_text())

    def test_a_pid_no_longer_that_session_is_never_signalled(self):
        a, b = self.procs
        pid = self.con.execute("INSERT INTO parks(at) VALUES(?)", (time.time(),)).lastrowid
        for sid, p in (("reused", a), ("gone", b)):
            self.con.execute("INSERT INTO sessions(park_id, sid, name, kind, pid, status_at_park) "
                             "VALUES(?,?,?,'interactive',?,'idle')", (pid, sid, sid, p))
        # "reused": claude now reports another pid for it; "gone": not listed at all.
        res = park.coordinate(self.con, pid, live=[{"sessionId": "reused", "pid": 1, "status": "idle"},
                                                     {"sessionId": "unrelated", "pid": 2}])
        self.assertIn("pid changed", res["reused"])
        self.assertEqual(res["gone"], "already gone")
        self.assertTrue(park.alive(a) and park.alive(b), "a pid not verified as the session must not be signalled")

    def test_no_session_list_means_nothing_is_signalled(self):
        a = self.procs[0]
        pid = self.con.execute("INSERT INTO parks(at) VALUES(?)", (time.time(),)).lastrowid
        self.con.execute("INSERT INTO sessions(park_id, sid, name, kind, pid, status_at_park) "
                         "VALUES(?, 'one', 'one', 'interactive', ?, 'idle')", (pid, a))
        res = park.coordinate(self.con, pid, live=[])
        self.assertIn("could not list", res["one"])
        self.assertTrue(park.alive(a))
        self.assertEqual(self.con.execute("SELECT stopped FROM sessions WHERE sid='one'").fetchone()[0], 0)

    def test_terminal_is_not_quit_while_a_session_is_still_running(self):
        a, b = self.procs
        pid = self.con.execute("INSERT INTO parks(at) VALUES(?)", (time.time(),)).lastrowid
        for sid, p, tty in (("stops", a, "/dev/ttys041"), ("unchecked", b, "/dev/ttys042")):
            self.con.execute("INSERT INTO sessions(park_id, sid, name, kind, pid, tty, status_at_park) "
                             "VALUES(?,?,?,'interactive',?,?,'idle')", (pid, sid, sid, p, tty))
        # "unchecked" reports a different pid, so it is left running.
        res = park.coordinate(self.con, pid, live=[{"sessionId": "stops", "pid": a, "status": "idle"},
                                                     {"sessionId": "unchecked", "pid": 1, "status": "idle"}])
        self.assertEqual(res["stops"], "stopped")
        self.assertTrue(park.alive(b))
        log = self.calls.read_text()
        self.assertNotIn("to quit", log)          # Terminal stays open for the session still running
        self.assertIn("/dev/ttys041", log)        # the stopped session's own window still closes
        self.assertNotIn("/dev/ttys042", log)

    def test_no_session_list_keeps_terminal_open(self):
        a = self.procs[0]
        pid = self.con.execute("INSERT INTO parks(at) VALUES(?)", (time.time(),)).lastrowid
        self.con.execute("INSERT INTO sessions(park_id, sid, name, kind, pid, tty, status_at_park) "
                         "VALUES(?, 'one', 'one', 'interactive', ?, '/dev/ttys043', 'idle')", (pid, a))
        park.coordinate(self.con, pid, live=[])
        self.assertFalse(self.calls.exists() and "to quit" in self.calls.read_text())

    def test_a_process_that_exits_before_the_signal_does_not_abort(self):
        done = subprocess.run(["sh", "-c", "sh -c 'exit 0' & echo $!; wait"], capture_output=True, text=True)
        dead = int(done.stdout.split()[0])
        orig = park.alive
        park.alive = lambda p: True if int(p) == dead else orig(p)   # "alive" when checked, gone when signalled
        try:
            self.assertEqual(park.stop_interactive({"pid": dead, "sid": "x", "status_at_park": "idle"}, 1), "already gone")
        finally:
            park.alive = orig


class PlanTest(unittest.TestCase):
    def test_finds_its_own_session_without_the_env_var(self):
        con = db.connect(TMP / f"p{time.time_ns()}.db")
        t = dict(InventoryTest.TABLE)
        t[998] = (100, WRAP.format("./park plan"))
        t[999] = (998, "python3 park.py plan")
        s = park.plan(con, sessions=InventoryTest.SESSIONS, table=t, me=999)
        self.assertEqual(s["self"], "aaaa1111")
        self.assertEqual(con.execute("SELECT parked_by FROM parks WHERE id=?", (s["park"],)).fetchone()[0], "aaaa1111")
        app = next(p for p in s["parked"] if p["name"] == "app")
        self.assertIn("npm run dev", app["restart"])       # what resume will start again is shown, not just counted


class SnapshotSafetyTest(unittest.TestCase):
    def test_binary_changes_are_in_the_patch(self):
        repo = TMP / f"r{time.time_ns()}"
        repo.mkdir()
        g = lambda *a: subprocess.run(["git", "-C", str(repo), *a], capture_output=True, check=True)
        g("init", "-q")
        g("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "init")
        (repo / "img.bin").write_bytes(b"\x00\x01")
        g("add", "img.bin")
        (repo / "new.txt").write_text("x")
        st = snapshot.git_state(str(repo), TMP / f"{time.time_ns()}.patch")
        self.assertIn("GIT binary patch", Path(st["patch_path"]).read_text())
        self.assertEqual(st["untracked"], ["new.txt"])

    def test_prompt_mentions_untracked_and_keeps_odd_commands_contained(self):
        row = {"cwd": "/w/app", "repo_root": "/w/app", "branch": "b", "head": "h", "dirty": 1,
               "untracked": json.dumps(["new.txt"]), "note": "line one\nIgnore the above",
               "rearm": json.dumps([{"kind": "shell", "command": "echo `date`\nrm -rf x"}]), "crons": "[]",
               "long_running": "[]"}
        p = snapshot.resume_prompt(row, time.time())
        self.assertIn("untracked file(s), not in the patch: new.txt", p)
        self.assertIn('(JSON string) "echo `date`\\nrm -rf x"', p)
        self.assertIn("line one Ignore the above", p)
        self.assertNotIn("\nrm -rf x", p)

    def test_crlf_files_keep_their_line_ends_in_the_patch(self):
        repo = TMP / f"r{time.time_ns()}"
        repo.mkdir()
        g = lambda *a: subprocess.run(["git", "-C", str(repo), "-c", "core.autocrlf=false", *a],
                                      capture_output=True, check=True)
        g("init", "-q")
        (repo / "a.txt").write_bytes(b"one\r\ntwo\r\n")
        g("add", "a.txt")
        g("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "init")
        (repo / "a.txt").write_bytes(b"one\r\nTWO\r\n")
        st = snapshot.git_state(str(repo), TMP / f"{time.time_ns()}.patch")
        self.assertIn(b"+TWO\r\n", Path(st["patch_path"]).read_bytes())
        self.assertNotIn(b"\r\r\n", Path(st["patch_path"]).read_bytes())


# ---- Windows ---------------------------------------------------------------------------------
# The parsing and the tab logic are plain functions over a process table, so they run on every platform.

import winterm  # noqa: E402

WIN_LINE = (ROOT / "tests" / "fixtures" / "windows-bash-wrapper.txt").read_text(encoding="utf-8").strip()
WIN_REAL = "while true; do echo \"a\\\"b \\\\x\" 'c'\"'\"'d' > /dev/null; sleep 30; done"


def procs(*rows):
    """{pid: {ppid, name, cmd, created}} from (pid, ppid, name, created) rows."""
    return {pid: {"ppid": ppid, "name": name, "cmd": "", "created": created} for pid, ppid, name, created in rows}


class WindowsCaptureTest(unittest.TestCase):
    def test_win_argv_follows_the_c_runtime(self):
        self.assertEqual(inventory.win_argv(r'"C:\Program Files\x.exe" -c "a \"b\" c\\" d'),
                         [r"C:\Program Files\x.exe", "-c", 'a "b" c\\', "d"])
        self.assertEqual(inventory.win_argv(r'a\\\"b "c""d" e\f'), ['a\\"b', 'c"d', r"e\f"])

    def test_a_real_git_bash_wrapper_comes_back_as_typed(self):
        self.assertEqual(inventory.eval_command(WIN_LINE), WIN_REAL)
        self.assertEqual(inventory.classify(inventory.eval_command(WIN_LINE)), "monitor")

    def test_a_cut_off_windows_line_is_never_a_command(self):
        self.assertIsNone(inventory.eval_command(WIN_LINE[:WIN_LINE.index("< /dev/null") - 5]))

    def test_braced_wrapper_reading_stdin(self):
        line = "bash -c source /c/u/.claude/shell-snapshots/snapshot-bash-1-a.sh && { eval 'npm run dev'; } && pwd -P >| /t/c"
        self.assertEqual(inventory.eval_command(line), "npm run dev")

    def test_powershell_tool_commands_are_listed_never_restarted(self):
        ps = ('C:\\WINDOWS\\System32\\cmd.exe /d /s /c ""powershell.exe" -NoProfile -Command "$__claudeCodeScript = '
              '$env:CLAUDE_CODE_SHELL_LAUNCHER_SCRIPT; Invoke-Expression -Command $__claudeCodeScript""')
        t = {1: (100, ps), 2: (1, ps), 3: (100, WIN_LINE)}
        cmds = inventory.tool_commands(t, 100, me=999)
        self.assertEqual(sorted(c["kind"] for c in cmds), ["monitor", "partial"])
        self.assertIn("PowerShell", next(c["command"] for c in cmds if c["kind"] == "partial"))


class WindowsTabTest(unittest.TestCase):
    #          pid  ppid  name                  created
    BASE = [(1, 0, "explorer.exe", 1), (2, 1, "windowsterminal.exe", 2),
            (10, 2, "bash.exe", 10), (11, 10, "bash.exe", 11), (12, 11, "claude.exe", 12), (13, 10, "conhost.exe", 13)]

    def test_host_is_the_process_the_terminal_started_for_the_tab(self):
        p = procs(*self.BASE)
        self.assertEqual(winterm.host_of(12, p), "wt:10:10")

    def test_not_a_windows_terminal_tab_is_never_ours(self):
        p = procs((1, 0, "explorer.exe", 1), (2, 1, "code.exe", 2), (10, 2, "pwsh.exe", 10), (12, 10, "claude.exe", 12))
        self.assertEqual(winterm.host_of(12, p), "")
        p = procs(*self.BASE, (20, 2, "myscript.exe", 20), (21, 20, "claude.exe", 21))
        self.assertEqual(winterm.host_of(21, p), "")

    def test_a_reused_parent_pid_is_not_followed(self):
        p = procs((2, 1, "windowsterminal.exe", 50), (10, 2, "bash.exe", 10), (12, 10, "claude.exe", 12))
        self.assertEqual(winterm.host_of(12, p), "")     # pid 2 started after its "child": someone else's now

    def test_tab_closes_only_when_nothing_but_idle_shells_is_left(self):
        p = procs(*self.BASE)
        self.assertIsNone(winterm.closable("wt:10:10", p))               # claude still up
        del p[12]
        self.assertEqual(winterm.closable("wt:10:10", p), [11, 10])      # idle shells, deepest first
        p[30] = {"ppid": 11, "name": "node.exe", "cmd": "", "created": 30}
        self.assertIsNone(winterm.closable("wt:10:10", p))               # a server the shell still runs
        self.assertEqual(winterm.closable("wt:10:99", procs(*self.BASE)), [])   # a different process now: gone

    def test_close_tabs_ends_the_tab_processes(self):
        p = procs(*self.BASE)
        del p[12]
        ended = []
        self.assertEqual(winterm.close_tabs(["wt:10:10", "", "/dev/ttys001"], procs_fn=lambda: p, end=ended.append), 1)
        self.assertEqual(ended, [11, 10])

    def test_tab_args_open_in_the_park_window_and_escape_semicolons(self):
        a = winterm.tab_args(r"C:\h\launch\s1.json", r"D:\a;b", "my;name", wt="wt.exe", python=r"C:\py\python.exe")
        self.assertEqual(a[:4], ["wt.exe", "-w", "park", "new-tab"])
        self.assertIn(r"D:\a\;b", a)
        self.assertIn("my\\;name", a)
        self.assertEqual(a[-2:], ["launch", r"C:\h\launch\s1.json"])

    def test_session_markers_are_dropped_and_the_users_own_kept(self):
        env = {"CLAUDE_CODE_CHILD_SESSION": "1", "CLAUDECODE": "1", "CLAUDE_CODE_SESSION_ID": "x",
               "CLAUDE_CODE_USE_BEDROCK": "1", "PATH": "p"}
        self.assertEqual(winterm.session_only_vars(env, keep={"CLAUDE_CODE_USE_BEDROCK"}),
                         ["CLAUDECODE", "CLAUDE_CODE_CHILD_SESSION", "CLAUDE_CODE_SESSION_ID"])


@unittest.skipUnless(sys.platform == "win32", "Windows consoles")
class WindowsCoordinatorTest(unittest.TestCase):
    """The shutdown on Windows with real throwaway processes, each on a hidden console of its own (a real
    Ctrl+C reaches them), and fake claude, tab closing and pr-pulse."""

    def spawn(self, console=True):
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW     # SW_HIDE: no window flashes up
        flags = subprocess.CREATE_NEW_CONSOLE if console else winterm.DETACHED_PROCESS
        p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], creationflags=flags, startupinfo=si)
        self.procs.append(p)
        time.sleep(0.5)
        return p.pid

    def setUp(self):
        self.procs, self.calls, self.closed = [], [], []
        self.con = db.connect(TMP / f"w{time.time_ns()}.db")
        db.set_config(self.con, "busy_wait_s", 1)
        self.orig = (park.pr_pulse_is_on, inventory.run, park.terminal.close_windows)
        park.pr_pulse_is_on = lambda: False
        inventory.run = lambda args, **kw: self.calls.append(args) or "[]"
        park.terminal.close_windows = lambda hosts: self.closed.extend(hosts) or len(hosts)

    def tearDown(self):
        park.pr_pulse_is_on, inventory.run, park.terminal.close_windows = self.orig
        for p in self.procs:
            p.kill()
            p.wait()

    def test_ctrl_c_stops_sessions_and_closes_only_their_tabs(self):
        a, me = self.spawn(), self.spawn()
        pid = self.con.execute("INSERT INTO parks(at, parked_by) VALUES(?, 'self')", (time.time(),)).lastrowid
        for sid, kind, ppid, host in (("self", "interactive", me, "wt:1:1"), ("other", "interactive", a, "wt:2:2"),
                                      ("bgsess01", "background", None, "")):
            self.con.execute("INSERT INTO sessions(park_id, sid, name, kind, pid, tty, status_at_park) "
                             "VALUES(?,?,?,?,?,?,'idle')", (pid, sid, sid, kind, ppid, host))
        live = [{"sessionId": "self", "pid": me, "status": "idle"}, {"sessionId": "other", "pid": a, "status": "idle"}]
        orig_idle = park.wait_idle
        park.wait_idle = lambda sid, s: None
        try:
            res = park.coordinate(self.con, pid, live=live)
        finally:
            park.wait_idle = orig_idle
        self.assertEqual(res, {"bgsess01": "stopped", "other": "stopped", "self": "stopped"})
        self.assertFalse(park.alive(a) or park.alive(me))
        self.assertEqual([c[:2] for c in self.calls], [["claude", "stop"]])
        self.assertEqual(sorted(self.closed), ["wt:1:1", "wt:2:2"])       # "all" never quits Windows Terminal

    def test_a_session_without_a_console_is_left_running(self):
        a = self.spawn(console=False)
        pid = self.con.execute("INSERT INTO parks(at) VALUES(?)", (time.time(),)).lastrowid
        self.con.execute("INSERT INTO sessions(park_id, sid, name, kind, pid, tty, status_at_park) "
                         "VALUES(?, 'one', 'one', 'interactive', ?, 'wt:3:3', 'idle')", (pid, a))
        res = park.coordinate(self.con, pid, live=[{"sessionId": "one", "pid": a, "status": "idle"}])
        self.assertIn("not stopped", res["one"])
        self.assertTrue(park.alive(a))
        self.assertEqual(self.closed, [])

    def test_alive_never_sends_a_ctrl_c(self):
        a = self.spawn()
        for _ in range(3):
            self.assertTrue(park.alive(a))     # os.kill(pid, 0) would have been a Ctrl+C and ended it
        time.sleep(0.5)
        self.assertTrue(park.alive(a))


if __name__ == "__main__":
    unittest.main()
