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


if __name__ == "__main__":
    unittest.main()
