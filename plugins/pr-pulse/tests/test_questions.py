"""Questions answered from a notification: one on screen at a time, answers tied to their
question, late answers for finished jobs dropped, waiting jobs never treated as stale."""
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("PR_PULSE_HOME", tempfile.mkdtemp(prefix="pp-q-"))
os.environ["PR_PULSE_NO_NOTIFY"] = "1"
sys.path.insert(0, str(ROOT / "scripts"))
import db         # noqa: E402
import dispatch   # noqa: E402
import questions  # noqa: E402

URL = "https://github.com/o/r/pull/{}".format


class QuestionsTest(unittest.TestCase):
    def setUp(self):
        self.con = db.connect(Path(tempfile.mkdtemp()) / "pulse.db")
        self.inbox = Path(tempfile.mkdtemp())
        self.job = db.enqueue(self.con, URL(1), "feedback", 0)
        db.claim(self.con, self.job, "s1")
        db.set_job(self.con, self.job, "delivered")

    def ask(self, text="Implement or defer?", opts=("Implement", "Defer"), allow=True, job=None):
        return questions.add(self.con, job or self.job, "s1", text, opts, allow)

    def test_answer_wakes_the_session(self):
        q = self.ask()
        self.assertEqual(questions.answer(self.con, q, "Defer", "notification", self.inbox), "ok")
        line = json.loads((self.inbox / "s1.jsonl").read_text().splitlines()[-1])
        self.assertEqual((line["answer"], line["job"], line["text"]), (q, self.job, "Defer"))
        self.assertEqual(questions.answer(self.con, q, "Implement", "inbox", self.inbox), "already")
        self.assertEqual(len((self.inbox / "s1.jsonl").read_text().splitlines()), 1)   # no second line

    def test_answer_elsewhere_clears_the_screen_once(self):
        cleared = []
        orig = questions.clear_screen
        questions.clear_screen = lambda qid=None: cleared.append(qid)
        try:
            q = self.ask()
            questions.claim_for_showing(self.con, q)              # on screen now
            self.assertEqual(questions.answer(self.con, q, "Defer", "inbox", self.inbox), "ok")
            self.assertEqual(cleared, [q])                       # banner removed
            q2 = self.ask("second")
            questions.claim_for_showing(self.con, q2)
            questions.answer(self.con, q2, "Defer", "notification", self.inbox)
            self.assertEqual(cleared, [q])                       # answered on the banner itself: nothing to clear
        finally:
            questions.clear_screen = orig

    def test_late_answer_for_finished_job_is_dropped(self):
        q = self.ask()
        db.set_job(self.con, self.job, "done")
        self.assertEqual(questions.answer(self.con, q, "Defer", "notification", self.inbox), "expired")
        self.assertFalse((self.inbox / "s1.jsonl").exists())

    def test_one_on_screen_at_a_time_and_reshow_after_later(self):
        q1, q2 = self.ask("first"), self.ask("second")
        now = time.time()
        first = questions.next_to_show(self.con, now)
        self.assertEqual(first["id"], q1)
        self.assertTrue(questions.claim_for_showing(self.con, q1))
        self.assertFalse(questions.claim_for_showing(self.con, q1))      # no double claim
        self.assertIsNone(questions.next_to_show(self.con, now))         # q2 waits its turn
        questions.release(self.con, q1)                                  # Later
        nxt = questions.next_to_show(self.con, now + 5)
        self.assertEqual(nxt["id"], q2)                                  # q1 is not shown again yet
        self.assertEqual(questions.next_to_show(self.con, now + questions.RESHOW_SECONDS + 5)["id"], q1)

    def test_expire_finished(self):
        q = self.ask()
        db.set_job(self.con, self.job, "failed")
        questions.expire_finished(self.con)
        self.assertEqual(self.con.execute("SELECT status FROM questions WHERE id=?", (q,)).fetchone()[0], "expired")
        self.assertIsNone(questions.next_to_show(self.con))

    def test_job_waiting_on_an_answer_is_not_stale(self):
        self.con.execute("INSERT INTO sessions(sid, status) VALUES('s1', 'idle')")
        old = time.time() - 5 * 3600
        self.con.execute("UPDATE jobs SET heartbeat_at=?, updated_at=? WHERE id=?", (old, old, self.job))
        q = self.ask()
        dispatch.recover_stale(self.con, dict(db.DEFAULT_CONFIG))
        self.assertEqual(self.con.execute("SELECT status FROM jobs WHERE id=?", (self.job,)).fetchone()[0], "delivered")
        questions.answer(self.con, q, "Defer", "inbox", self.inbox)
        self.con.execute("UPDATE jobs SET heartbeat_at=?, updated_at=? WHERE id=?", (old, old, self.job))
        dispatch.recover_stale(self.con, dict(db.DEFAULT_CONFIG))
        self.assertEqual(self.con.execute("SELECT status FROM jobs WHERE id=?", (self.job,)).fetchone()[0], "queued")


if __name__ == "__main__":
    unittest.main()
