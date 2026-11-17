"""Any session waiting for the user gets one notification; not the tab they're looking at;
cleared when it stops waiting; repeated after REMIND. Both directions."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("PR_PULSE_HOME", tempfile.mkdtemp(prefix="pp-wait-"))
sys.path.insert(0, str(ROOT / "scripts"))
import db       # noqa: E402
import waiting  # noqa: E402


def s(sid, status, kind="interactive", pid=1):
    return {"sessionId": sid, "name": f"n-{sid}", "status": status, "kind": kind, "pid": pid, "cwd": "/x"}


class WaitingTest(unittest.TestCase):
    def setUp(self):
        self.con = db.connect(Path(tempfile.mkdtemp()) / "pulse.db")
        self.cfg = dict(db.DEFAULT_CONFIG)
        self.launched, self.cleared = [], []
        self._clear, self._tty = waiting.clear, waiting.session_tty
        waiting.clear = lambda sid, con=None: self.cleared.append(sid)
        waiting.session_tty = lambda sess: (f"/dev/tty-{sess['sessionId']}" if sess['kind'] == 'interactive' else '')

    def tearDown(self):
        waiting.clear, waiting.session_tty = self._clear, self._tty

    def watch(self, sessions, now, front=""):
        return waiting.watch(self.con, sessions, self.cfg, now=now,
                             launch=lambda x: self.launched.append(x["sessionId"]), front=lambda: front)

    def test_notifies_once_then_reminds(self):
        t = 1_800_000_000.0
        self.assertEqual(self.watch([s("a", "waiting"), s("b", "busy")], t), ["a"])
        self.assertEqual(self.watch([s("a", "waiting")], t + 60), [])            # same episode
        self.assertEqual(self.watch([s("a", "waiting")], t + waiting.REMIND + 1), ["a"])

    def test_not_for_the_tab_in_front(self):
        self.assertEqual(self.watch([s("a", "waiting")], 1e9, front="/dev/tty-a"), [])
        self.assertEqual(self.watch([s("a", "waiting")], 1e9 + 5, front="/dev/tty-other"), ["a"])

    def test_background_sessions_are_never_the_front_tab(self):
        self.assertEqual(self.watch([s("w", "waiting", kind="background")], 1e9, front="/dev/tty-w"), ["w"])

    def test_cleared_when_it_stops_waiting_and_new_episode_notifies_again(self):
        t = 1_800_000_000.0
        self.watch([s("a", "waiting")], t)
        self.watch([s("a", "busy")], t + 30)
        self.assertEqual(self.cleared, ["a"])
        self.assertEqual(self.watch([s("a", "waiting")], t + 60), ["a"])      # a new question

    def test_off_switch_and_unknown_sessions(self):
        self.cfg["notify_waiting_sessions"] = False
        self.assertEqual(self.watch([s("a", "waiting")], 1e9), [])
        self.cfg["notify_waiting_sessions"] = True
        self.assertEqual(waiting.watch(self.con, None, self.cfg), [])        # claude agents failed


if __name__ == "__main__":
    unittest.main()


class BannerRemovalTest(unittest.TestCase):
    """`alerter --remove` on another group froze the question banner on screen (reproduced
    2026-11-13): while a question shows, removals wait; after, they run."""

    def setUp(self):
        import tempfile
        from pathlib import Path
        self.con = db.connect(Path(tempfile.mkdtemp()) / "pulse.db")
        self.ran = []
        self.orig = waiting.core.run
        waiting.core.run = lambda args, cwd=None, timeout=30: (self.ran.append(args) or "/x/alerter")

    def tearDown(self):
        waiting.core.run = self.orig

    def removes(self):
        return [a for a in self.ran if a[:2] == ["alerter", "--remove"]]

    def test_no_remove_while_a_question_shows_then_it_runs(self):
        self.con.execute("INSERT INTO questions(job_id, sid, question, created_at, status) "
                         "VALUES(1, 's', 'q', 0, 'showing')")
        waiting.clear("abcdef123456", self.con)
        self.assertEqual(self.removes(), [])
        self.assertEqual(waiting.flush_removals(self.con), 0)       # still showing: waits
        self.assertEqual(self.removes(), [])
        self.con.execute("UPDATE questions SET status='answered'")
        self.assertEqual(waiting.flush_removals(self.con), 1)
        self.assertEqual(self.removes(), [["alerter", "--remove", "pr-pulse-wait-abcdef12"]])
        self.assertEqual(waiting.flush_removals(self.con), 0)       # once

    def test_with_no_question_on_screen_it_removes_at_once(self):
        waiting.clear("abcdef123456", self.con)
        self.assertEqual(self.removes(), [["alerter", "--remove", "pr-pulse-wait-abcdef12"]])
