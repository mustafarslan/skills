"""Every part of pr-pulse runs the installed plugin: the service's copy follows it by content
(also for a same-version change), any loaded copy hands over to the service's copy, and
sessions that loaded an older folder are reported. Both directions of each gate."""
import importlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def make_plugin(path, version, extra=""):
    shutil.copytree(ROOT, path, ignore=shutil.ignore_patterns("tests", "__pycache__"))
    pj = path / ".claude-plugin" / "plugin.json"
    d = json.loads(pj.read_text())
    d["version"] = version
    pj.write_text(json.dumps(d))
    if extra:
        (path / "prompts" / "extra.md").write_text(extra)
    return path


class CurrentTest(unittest.TestCase):
    def setUp(self):
        self._env = dict(os.environ)
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(self._env)))
        self.tmp = Path(tempfile.mkdtemp())
        os.environ["PR_PULSE_HOME"] = str(self.tmp / "home")
        os.environ["PR_PULSE_INSTALLED_JSON"] = str(self.tmp / "installed.json")
        os.environ.pop("PR_PULSE_FORWARDED", None)
        os.environ.pop("PR_PULSE_LOADED_FROM", None)
        import current
        self.c = importlib.reload(current)
        self.v1 = make_plugin(self.tmp / "cache" / "0.9.0", "0.9.0")

    def install(self, root):
        (self.tmp / "installed.json").write_text(json.dumps(
            {"plugins": {"pr-pulse@m": [{"scope": "user", "installPath": str(root)}]}}))

    def test_fingerprint_ignores_runtime_files_only(self):
        fp = self.c.fingerprint(self.v1)
        (self.v1 / "scripts" / "__pycache__").mkdir(exist_ok=True)
        (self.v1 / "scripts" / "__pycache__" / "x.pyc").write_text("x")
        (self.v1 / ".fingerprint").write_text("x")
        self.assertEqual(self.c.fingerprint(self.v1), fp)
        (self.v1 / "prompts" / "job.md").write_text("changed")
        self.assertNotEqual(self.c.fingerprint(self.v1), fp)

    def test_no_service_means_nothing_is_synced(self):
        self.install(self.v1)
        self.assertIsNone(self.c.ensure_app())
        self.assertFalse(self.c.APP.exists())

    def test_same_version_with_changed_content_is_synced(self):
        self.install(self.v1)
        self.c.sync(self.v1)
        self.assertIsNone(self.c.ensure_app())          # identical: no-op
        self.assertIsNone(self.c.ensure_app())          # ...twice in a row
        (self.v1 / "prompts" / "job.md").write_text("same version, new text")
        self.assertEqual(self.c.ensure_app(), "0.9.0")
        self.assertEqual((self.c.APP / "prompts" / "job.md").read_text(), "same version, new text")
        self.assertIsNone(self.c.ensure_app())

    def test_installed_copy_wins_even_when_older(self):
        newer = make_plugin(self.tmp / "cache" / "1.0.0", "1.0.0")
        self.c.sync(newer)
        self.install(self.v1)                             # rolled back to 0.9.0
        self.assertEqual(self.c.ensure_app(), "0.9.0")

    def test_old_copy_hands_over_and_app_runs_itself(self):
        self.install(self.v1)
        self.c.sync(self.v1)
        old = make_plugin(self.tmp / "cache" / "0.8.0", "0.8.0")
        env = dict(os.environ)
        real = (self.c.APP / "scripts" / "pr-pulse").read_text()
        (self.c.APP / "scripts" / "pr-pulse").write_text(
            "import os, sys\nprint('app copy ran', sys.argv[1:], os.environ['PR_PULSE_LOADED_FROM'])\n")
        r = subprocess.run([sys.executable, str(old / "scripts" / "pr-pulse"), "auto-review", "status"],
                           env=env, capture_output=True, text=True)
        self.assertEqual(r.stdout.strip(), f"app copy ran ['auto-review', 'status'] {old.resolve()}", r.stderr)
        (self.c.APP / "scripts" / "pr-pulse").write_text(real)
        probe = ("import os,sys;sys.path.insert(0,sys.argv[1]);import current;"
                 "current.forward(sys.argv[2], []);print('ran-here', os.environ.get('PR_PULSE_LOADED_FROM',''))")
        # forward() from the app copy itself returns (never forwards to itself)
        out = subprocess.run([sys.executable, "-c", probe, str(self.c.APP / "scripts"),
                              str(self.c.APP / "scripts" / "pr-pulse")], env=env, capture_output=True,
                             text=True).stdout
        self.assertTrue(out.startswith("ran-here"))

    def test_without_a_service_a_copy_runs_itself(self):
        probe = ("import sys;sys.path.insert(0,sys.argv[1]);import current;"
                 "current.forward(sys.argv[2], []);print('ran-here')")
        out = subprocess.run([sys.executable, "-c", probe, str(self.v1 / "scripts"),
                              str(self.v1 / "scripts" / "pr-pulse")], capture_output=True, text=True).stdout
        self.assertEqual(out.strip(), "ran-here")

    def test_bash_hook_hands_over(self):
        self.install(self.v1)
        self.c.sync(self.v1)
        (self.c.APP / "scripts" / "toggle.sh").write_text('echo "app copy ran: $PR_PULSE_LOADED_FROM"\n')
        old = make_plugin(self.tmp / "cache" / "0.8.0", "0.8.0")
        out = subprocess.run(["bash", str(old / "scripts" / "toggle.sh"), "status", "s1"],
                             capture_output=True, text=True, env=dict(os.environ)).stdout
        self.assertEqual(out.strip(), f"app copy ran: {old.resolve()}")

    def test_parallel_syncs_end_in_one_complete_copy(self):
        self.install(self.v1)
        self.c.sync(make_plugin(self.tmp / "cache" / "0.8.0", "0.8.0"))
        code = ("import sys;sys.path.insert(0,sys.argv[1]);import current;current.ensure_app()")
        procs = [subprocess.Popen([sys.executable, "-c", code, str(ROOT / "scripts")], env=dict(os.environ))
                 for _ in range(8)]
        self.assertEqual([p.wait(timeout=60) for p in procs], [0] * 8)
        self.assertTrue(self.c.APP.is_symlink())
        self.assertEqual(self.c.fingerprint(self.c.APP), self.c.fingerprint(self.v1))
        self.assertEqual(self.c.plugin_version(self.c.APP), "0.9.0")
        self.assertFalse([p for p in self.c.HOME.iterdir() if p.name.startswith(".app.")])  # no leftovers
        self.assertFalse([p for p in self.c.VERSIONS.iterdir() if p.name.startswith(".tmp")])

    def test_a_damaged_copy_with_a_valid_stamp_heals_on_verify(self):
        self.install(self.v1)
        self.c.sync(self.v1)
        (self.c.APP / "scripts" / "announce.py").write_text("broken")
        self.assertIsNone(self.c.ensure_app())                 # the stamp alone says fine
        self.assertEqual(self.c.ensure_app(verify=True), "0.9.0")
        self.assertEqual((self.c.APP / "scripts" / "announce.py").read_text(),
                         (self.v1 / "scripts" / "announce.py").read_text())

    def test_old_folder_becomes_a_symlink_once(self):
        shutil.copytree(self.v1, self.c.APP)                    # how 0.7.6 and older left it
        self.install(make_plugin(self.tmp / "cache" / "1.0.0", "1.0.0"))
        self.assertEqual(self.c.ensure_app(), "1.0.0")
        self.assertTrue(self.c.APP.is_symlink())

    def test_daemon_restarts_only_on_a_changed_copy(self):
        import importlib.util
        spec = importlib.util.spec_from_loader("pd_cur", loader=None)
        d = importlib.util.module_from_spec(spec)
        d.__file__ = str(ROOT / "scripts" / "pr-pulsed.py")
        exec(compile((ROOT / "scripts" / "pr-pulsed.py").read_text(), d.__file__, "exec"), d.__dict__)
        d.current = self.c
        self.install(self.v1)
        self.c.sync(self.v1)
        start = self.c.app_fingerprint()
        calls, told = [], []
        self.assertEqual(d.self_update(start, ["x"], execv=lambda *a: calls.append(a), notify=told.append), "same")
        self.assertEqual(calls, [])
        (self.v1 / "prompts" / "job.md").write_text("changed")
        self.assertEqual(d.self_update(start, ["x"], execv=lambda *a: calls.append(a), notify=told.append),
                         "restart")
        self.assertEqual(calls[0][1][1], str(self.c.APP / "scripts" / "pr-pulsed.py"))
        self.c.ensure_app = lambda verify=False: (_ for _ in ()).throw(OSError("disk full"))
        self.assertEqual(d.self_update(start, ["x"], execv=lambda *a: calls.append(a), notify=told.append),
                         "failed")
        self.assertIn("disk full", told[-1])

    def test_post_guard_records_the_loaded_folder_and_never_hands_over(self):
        import db
        con = db.connect(self.c.HOME / "pulse.db")
        ev = json.dumps({"tool_name": "Bash", "tool_input": {"command": "ls"}, "session_id": "s1"})
        r = subprocess.run([sys.executable, str(ROOT / "scripts" / "post-guard.py")], input=ev, text=True,
                           capture_output=True, env=dict(os.environ))
        self.assertEqual((r.returncode, r.stdout), (0, ""))
        row = con.execute("SELECT root FROM loaded WHERE sid='s1'").fetchone()
        self.assertEqual(row[0], str(ROOT))

    def test_stale_sessions_are_reported_once(self):
        con = sqlite3.connect(":memory:")
        con.row_factory = sqlite3.Row
        con.execute("CREATE TABLE sessions(sid TEXT, name TEXT, status TEXT, spawned INTEGER DEFAULT 0)")
        con.execute("CREATE TABLE loaded(sid TEXT PRIMARY KEY, root TEXT, seen_at REAL, notified_at REAL)")
        old = make_plugin(self.tmp / "cache" / "0.8.0", "0.8.0")
        con.executemany("INSERT INTO sessions VALUES(?,?,?,?)",
                        [("a", "old-one", "idle", 0), ("b", "current-one", "busy", 0), ("c", "gone-one", "gone", 0),
                         ("w", "pr-o-r-1-feedback", "busy", 1)])
        con.executemany("INSERT INTO loaded VALUES(?,?,?,NULL)",
                        [("a", str(old), time.time()), ("b", str(self.v1), time.time()),
                         ("c", str(old), time.time()), ("w", str(old), time.time())])   # a worker: never told
        told = []
        out = self.c.stale_sessions(con, notify=told.append, installed=self.v1)
        self.assertEqual(out, [("old-one", "0.8.0")])
        self.assertEqual(len(told), 1)
        self.assertIn("/reload-plugins", told[0])
        self.c.stale_sessions(con, notify=told.append, installed=self.v1)
        self.assertEqual(len(told), 1)                    # once per session and folder


if __name__ == "__main__":
    unittest.main()


class InUseMarkerTest(unittest.TestCase):
    def test_claude_codes_in_use_markers_do_not_change_the_fingerprint(self):
        import current
        tmp = Path(tempfile.mkdtemp()) / "p"
        make_plugin(tmp, "1.0.0")
        fp = current.fingerprint(tmp)
        (tmp / ".in_use").mkdir()
        (tmp / ".in_use" / "12345").write_text("{}")   # a session started
        self.assertEqual(current.fingerprint(tmp), fp)
        (tmp / "scripts" / "x.py").write_text("real change")
        self.assertNotEqual(current.fingerprint(tmp), fp)


class ServiceCopyGuardTest(unittest.TestCase):
    def test_the_guard_run_from_the_service_copy_records_nothing(self):
        import current
        home = Path(tempfile.mkdtemp())
        env = dict(os.environ, PR_PULSE_HOME=str(home))
        svc = home / "app.versions" / "abc"
        make_plugin(svc, "1.0.0")
        plug = make_plugin(home / "cache" / "1.0.0", "1.0.0")
        import sqlite3 as _s
        sys.path.insert(0, str(ROOT / "scripts"))
        import db
        db.connect(home / "pulse.db").close()
        ev = json.dumps({"tool_name": "Bash", "tool_input": {"command": "ls"}, "session_id": "w1"})
        subprocess.run([sys.executable, str(svc / "scripts" / "post-guard.py")], input=ev, text=True, env=env)
        con = _s.connect(home / "pulse.db")
        self.assertEqual(con.execute("SELECT COUNT(*) FROM loaded").fetchone()[0], 0)
        subprocess.run([sys.executable, str(plug / "scripts" / "post-guard.py")], input=ev, text=True, env=env)
        self.assertEqual(con.execute("SELECT root FROM loaded").fetchone()[0], str(plug.resolve()))
