"""Session focus: a PR session handles only the PRs of the sessions it is joined --for; their PRs
wait for it; everything else goes to a general session or a worker. Each gate both ways."""
import contextlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOME = tempfile.mkdtemp(prefix="pp-focus-")
os.environ["PR_PULSE_HOME"] = HOME
os.environ["PR_PULSE_NO_NOTIFY"] = "1"
sys.path.insert(0, str(ROOT / "scripts"))
import db        # noqa: E402
import dispatch  # noqa: E402
import focus     # noqa: E402


def load(name, path):
    spec = importlib.util.spec_from_loader(name, loader=None)
    mod = importlib.util.module_from_spec(spec)
    mod.__file__ = str(path)
    exec(compile(Path(path).read_text(), str(path), "exec"), mod.__dict__)
    return mod


cli = load("pr_pulse_cli_focus", ROOT / "scripts" / "pr-pulse")
daemon = load("pr_pulsed_focus", ROOT / "scripts" / "pr-pulsed.py")
URL = "https://github.com/o/r/pull/{}"


class Base(unittest.TestCase):
    def setUp(self):
        self.con = db.connect(Path(tempfile.mkdtemp()) / "pulse.db")
        self.con.execute("INSERT INTO repos(path, slug, added_at) VALUES('/x/r', 'o/r', 0)")
        for n in range(1, 8):
            self.con.execute("INSERT INTO prs(url, slug, n, kind, state, head_sha) VALUES(?, 'o/r', ?, 'own', "
                             "'OPEN', 'h')", (URL.format(n), n))
        # development sessions and PR sessions
        self.sess("dev-c", "contracts", registered=0)
        self.sess("dev-o", "org-access-control", registered=0)
        self.told = []
        self._notify = dispatch.notify
        dispatch.notify = self.told.append
        self.spawned = []
        self._spawn = dispatch.spawn_worker
        dispatch.spawn_worker = lambda con, job, cfg, dry=False: self.spawned.append(job["id"]) or True
        self._skill = dispatch.core.skill_source
        dispatch.core.skill_source = lambda s, r=None: "personal"
        self.cfg = dict(db.DEFAULT_CONFIG)

    def tearDown(self):
        dispatch.notify = self._notify
        dispatch.spawn_worker = self._spawn
        dispatch.core.skill_source = self._skill

    def sess(self, sid, name, registered=1, status="idle", focus_=None, live=True):
        self.con.execute("INSERT OR REPLACE INTO sessions(sid, name, slug, status, registered, focus, seen_at) "
                         "VALUES(?,?,'o/r',?,?,?,?)", (sid, name, status, registered,
                                                       json.dumps(focus_) if focus_ else None, time.time()))
        dispatch.INBOX.mkdir(parents=True, exist_ok=True)
        f = dispatch.INBOX / f"{sid}.live"
        if live:
            f.touch()
        elif f.exists():
            f.unlink()

    def job(self, n, action="feedback", origin=None):
        if origin:
            focus.record_origin(self.con, URL.format(n), origin)
        return db.enqueue(self.con, URL.format(n), action, 1)

    def where(self, j):
        return self.con.execute("SELECT status, sid FROM jobs WHERE id=?", (j,)).fetchone()


class RoutingTest(Base):
    def test_a_pair_takes_its_sessions_pr_and_the_general_session_does_not(self):
        self.sess("pr-c", "pr-contracts", focus_=["contracts"])
        self.sess("gen", "general")
        j = self.job(1, origin="dev-c")
        self.assertEqual(dispatch.pick_session(self.con, "o/r", None, URL.format(1)), "pr-c")
        dispatch.dispatch(self.con, self.cfg)
        self.assertEqual(self.where(j)["sid"], "pr-c")

    def test_a_focused_session_never_takes_other_sessions_or_unknown_prs(self):
        self.sess("pr-c", "pr-contracts", focus_=["contracts"])
        other = self.job(2, origin="dev-o")      # org-access-control's PR, no pair for it
        loose = self.job(3)                       # no known origin
        dispatch.dispatch(self.con, self.cfg)
        self.assertEqual(sorted(self.spawned), sorted([other, loose]))   # workers, never pr-c
        self.assertEqual(self.where(other)["sid"], None)

    def test_with_a_general_session_unpaired_prs_go_there(self):
        self.sess("pr-c", "pr-contracts", focus_=["contracts"])
        self.sess("gen", "general")
        j = self.job(2, origin="dev-o")
        self.assertEqual(dispatch.pick_session(self.con, "o/r", None, URL.format(2)), "gen")

    def test_a_busy_pair_means_wait_not_a_worker(self):
        self.sess("pr-c", "pr-contracts", focus_=["contracts"])
        first = self.job(1, origin="dev-c")
        second = self.job(4, origin="dev-c")
        dispatch.dispatch(self.con, self.cfg)
        self.assertEqual(self.where(first)["sid"], "pr-c")
        self.assertEqual(self.where(second)["status"], "queued")      # waits for pr-c
        self.assertEqual(self.spawned, [])
        self.assertEqual(self.told, [])                               # busy: no notice

    def test_a_deaf_or_gone_pair_holds_and_tells_once_until_it_listens_again(self):
        self.sess("pr-c", "pr-contracts", focus_=["contracts"], live=False)
        j = self.job(1, origin="dev-c")
        dispatch.dispatch(self.con, self.cfg)
        dispatch.dispatch(self.con, self.cfg)
        self.assertEqual(self.where(j)["status"], "queued")
        self.assertEqual(self.spawned, [])
        self.assertEqual(len(self.told), 1)
        self.assertIn("pr-contracts", self.told[0])
        self.assertIn("--for contracts", self.told[0])
        (dispatch.INBOX / "pr-c.live").touch()                       # it listens again
        dispatch.dispatch(self.con, self.cfg)
        self.assertEqual(self.where(j)["sid"], "pr-c")
        self.con.execute("UPDATE sessions SET status='gone' WHERE sid='pr-c'")
        (dispatch.INBOX / "pr-c.live").unlink()
        self.job(5, origin="dev-c")
        dispatch.dispatch(self.con, self.cfg)
        self.assertEqual(len(self.told), 2)                          # a new outage is told again

    def test_without_focus_everything_behaves_as_before(self):
        self.sess("gen", "general")
        j = self.job(1, origin="dev-c")
        self.assertEqual(dispatch.pick_session(self.con, "o/r", None, URL.format(1)), "gen")
        dispatch.dispatch(self.con, self.cfg)
        self.assertEqual(self.where(j)["sid"], "gen")

    def test_auto_review_off_still_holds_reviews_for_the_general_session(self):
        import autoreview
        self.sess("gen", "general")
        autoreview.turn_off(self.con, stopper=lambda sid, name: True)
        j = db.enqueue(self.con, URL.format(6), "review", 2)
        dispatch.dispatch(self.con, self.cfg)
        self.assertEqual(self.where(j)["status"], "queued")
        autoreview.turn_on(self.con, pr_state=lambda u: "OPEN")
        dispatch.dispatch(self.con, self.cfg)
        self.assertEqual(self.where(j)["sid"], "gen")


class OriginTest(Base):
    def test_first_writer_wins(self):
        self.assertTrue(focus.record_origin(self.con, URL.format(1), "dev-c"))
        self.assertFalse(focus.record_origin(self.con, URL.format(1), "dev-o"))
        self.assertEqual(focus.origin_name(self.con, URL.format(1)), "contracts")

    def test_manual_origin_overrides(self):
        focus.record_origin(self.con, URL.format(1), "dev-c")
        with contextlib.redirect_stdout(io.StringIO()):
            cli.cmd_focus(self.con, ["origin", "1", "org-access-control"])
        self.assertEqual(focus.origin_name(self.con, URL.format(1)), "org-access-control")


class JoinTest(Base):
    def join(self, sid, *args):
        os.environ["CLAUDE_CODE_SESSION_ID"] = sid
        orig = cli.core.repo_of
        cli.core.repo_of = lambda cwd: ("/x/r", "o/r", "main")
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out):
                cli.cmd_join(self.con, list(args))
        finally:
            cli.core.repo_of = orig
            del os.environ["CLAUDE_CODE_SESSION_ID"]
        return out.getvalue()

    def focus_of(self, sid):
        return focus.focus_of(self.con.execute("SELECT focus FROM sessions WHERE sid=?", (sid,)).fetchone())

    def test_join_for_a_session_then_plain_rejoin_keeps_it_and_general_clears_it(self):
        self.sess("pr-c", "pr-contracts", registered=0)
        out = self.join("pr-c", "--for", "contracts")
        self.assertIn("only the PRs of contracts", out)
        self.assertEqual(self.focus_of("pr-c"), ["contracts"])
        self.assertIsNone(self.con.execute("SELECT pr_session FROM repos").fetchone()[0])   # never catch-all
        self.join("pr-c")                                            # what start/park re-run
        self.assertEqual(self.focus_of("pr-c"), ["contracts"])
        self.join("pr-c", "--general")
        self.assertEqual(self.focus_of("pr-c"), [])

    def test_leave_clears_focus(self):
        self.sess("pr-c", "pr-contracts", focus_=["contracts"])
        os.environ["CLAUDE_CODE_SESSION_ID"] = "pr-c"
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                cli.cmd_leave(self.con, [])
        finally:
            del os.environ["CLAUDE_CODE_SESSION_ID"]
        self.assertEqual(self.focus_of("pr-c"), [])

    def test_unknown_ambiguous_and_self_are_refused(self):
        self.sess("pr-c", "pr-contracts", registered=0)
        self.sess("dup1", "twin", registered=0)
        self.sess("dup2", "twin", registered=0)
        for bad in ("nobody", "twin", "pr-contracts"):
            with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
                self.join("pr-c", "--for", bad)
        self.assertEqual(self.focus_of("pr-c"), [])


class PoolTest(Base):
    def test_jobs_waiting_for_a_pair_do_not_starve_the_pool(self):
        self.sess("pr-c", "pr-contracts", focus_=["contracts"], live=False)
        for n in (1, 2, 3):
            self.job(n, origin="dev-c")                              # 3 queued, all waiting for pr-c
        self.con.execute("INSERT INTO review_pool(pr_url, channel, ts, sharer, shared_at, status) "
                         "VALUES('https://github.com/o/r/pull/9', 'C', '1.0', 'U', 0, 'pool')")
        pulled = []
        orig = daemon.queue_review
        daemon.queue_review = lambda con, me, mapped, url, action, note, prio: pulled.append(url) or ""
        try:
            daemon.pool_pull(self.con, dict(self.cfg, pool_size=3), "me", {"o/r"})
        finally:
            daemon.queue_review = orig
        self.assertEqual(pulled, ["https://github.com/o/r/pull/9"])


class MigrationTest(unittest.TestCase):
    def test_announced_prs_get_their_origin_on_upgrade(self):
        p = Path(tempfile.mkdtemp()) / "pulse.db"
        con = db.connect(p)
        con.execute("DELETE FROM pr_origin")
        con.execute("INSERT INTO announcements(url, opened_at, sid, state) VALUES('https://github.com/o/r/pull/1', 1, "
                    "'dev-c', 'posted')")
        con.execute("INSERT INTO announcements(url, opened_at, sid, state) VALUES('https://github.com/o/r/pull/2', 1, "
                    "'', 'posted')")
        con.execute("PRAGMA user_version=8")
        con.close()
        con = db.connect(p)
        self.assertEqual([tuple(r) for r in con.execute("SELECT url, sid FROM pr_origin")],
                         [("https://github.com/o/r/pull/1", "dev-c")])


if __name__ == "__main__":
    unittest.main()
