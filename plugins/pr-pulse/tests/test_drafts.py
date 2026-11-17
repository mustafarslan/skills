"""Drafts as notifications: each parked draft becomes a notification question; Fill it for me goes
back to the session (which confirms before posting), typed lines go verbatim, Drop is final, merge
decisions merge or re-review, and the inbox path closes the notification. Both directions."""
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("PR_PULSE_HOME", tempfile.mkdtemp(prefix="pp-drafts-"))
os.environ["PR_PULSE_NO_NOTIFY"] = "1"
sys.path.insert(0, str(ROOT / "scripts"))
import db         # noqa: E402
import dispatch   # noqa: E402
import outbox     # noqa: E402
import questions  # noqa: E402

spec = importlib.util.spec_from_loader("pp_cli_drafts", loader=None)
cli = importlib.util.module_from_spec(spec)
cli.__file__ = str(ROOT / "scripts" / "pr-pulse")
exec(compile((ROOT / "scripts" / "pr-pulse").read_text(), cli.__file__, "exec"), cli.__dict__)

URL = "https://github.com/o/r/pull/{}".format
REVIEW = """**Verdict:** Request changes — the retry loop can spin forever.

### Critical
1. **src/a.py:9** — unbounded retry

### Improvement
- docs need an update
- add a test

### Nit
- typo
"""


class DraftsTest(unittest.TestCase):
    def setUp(self):
        self.con = db.connect(Path(tempfile.mkdtemp()) / "pulse.db")
        self.inbox = Path(tempfile.mkdtemp())
        self.con.execute("INSERT INTO prs(url, slug, n, kind, state, head_sha) VALUES(?, 'o/r', 1, 'review', 'OPEN', 'h1')", (URL(1),))
        self.job = db.enqueue(self.con, URL(1), "review", 2)
        db.claim(self.con, self.job, "s1")
        db.set_job(self.con, self.job, "delivered")
        self.cleared = []
        self._clear = questions.clear_screen
        questions.clear_screen = lambda qid=None: self.cleared.append(qid)

    def tearDown(self):
        questions.clear_screen = self._clear

    def cli(self, argv, stdin=""):
        out, old = io.StringIO(), (sys.stdin, sys.stdout, sys.stderr)
        sys.stdin, sys.stdout, sys.stderr = io.StringIO(stdin), out, out
        try:
            {"outbox": cli.cmd_outbox, "job": cli.cmd_job, "questions": cli.cmd_questions}[argv[0]](self.con, argv[1:])
        except SystemExit as e:
            out.write(f"[exit {e.code}]")
        finally:
            sys.stdin, sys.stdout, sys.stderr = old
        return out.getvalue()

    def park(self, kind="review", text=REVIEW):
        self.cli(["outbox", "add", "--job", str(self.job), "--kind", kind], text)
        d = self.con.execute("SELECT MAX(id) FROM outbox").fetchone()[0]
        self.cli(["job", "wait-user", str(self.job)])
        q = self.con.execute("SELECT * FROM questions WHERE draft_id=?", (d,)).fetchone()
        return d, q

    def status(self, table, id_):
        return self.con.execute(f"SELECT status FROM {table} WHERE id=?", (id_,)).fetchone()[0]

    def test_parking_a_draft_creates_its_notification_with_a_summary(self):
        d, q = self.park()
        self.assertEqual((q["kind"], json.loads(q["options"])), ("draft", ["Fill it for me", "Drop it"]))
        self.assertTrue(q["allow_text"])
        self.assertTrue(q["summary"].startswith("Verdict: Request changes"))
        import rules
        msg = rules.notification_message(q["question"], q["summary"], json.loads(q["findings"]))
        self.assertTrue(msg.startswith("1 critical · 2 improvements · 1 nit"), msg)
        self.assertIn("Verdict:", q["details"])
        self.assertIn("no questions waiting", self.cli(["questions"]))   # drafts aren't listed as questions

    def test_typed_lines_go_verbatim_and_send_the_job_back(self):
        d, q = self.park()
        self.assertEqual(questions.answer(self.con, q["id"], "Close, but one blocker.", "notification", self.inbox), "ok")
        row = self.con.execute("SELECT status, lines FROM outbox WHERE id=?", (d,)).fetchone()
        self.assertEqual(tuple(row), ("ready", "Close, but one blocker."))
        self.assertEqual(self.status("jobs", self.job), "queued")
        self.assertFalse((self.inbox / "s1.jsonl").exists())      # applied to the outbox, not the session

    def test_fill_goes_back_to_the_session_with_a_confirm_step(self):
        d, q = self.park()
        questions.answer(self.con, q["id"], "Fill it for me", "notification", self.inbox)
        self.assertEqual(self.status("outbox", d), "fill")
        job = dict(self.con.execute("SELECT * FROM jobs WHERE id=?", (self.job,)).fetchone())
        self.assertIn("fill: 1", job["note"])
        pr = dict(self.con.execute("SELECT * FROM prs WHERE url=?", (URL(1),)).fetchone())
        prompt = dispatch.render_prompt(job, pr)
        self.assertIn("outbox propose", prompt)                  # nothing posts unseen
        self.assertNotIn("outbox lines <draft id> --filled", prompt)   # the session never self-approves
        self.assertNotIn("{{", prompt)

    def filled(self):
        """A draft the user marked Fill it for me, back with its session (delivered)."""
        d, q = self.park()
        questions.answer(self.con, q["id"], "Fill it for me", "notification", self.inbox)
        db.claim(self.con, self.job, "s1")
        db.set_job(self.con, self.job, "delivered")
        return d

    def propose(self, d, lines="Nice work, one note below."):
        out = self.cli(["outbox", "propose", str(d)], lines)
        q = self.con.execute("SELECT * FROM questions WHERE draft_id=? ORDER BY id DESC", (d,)).fetchone()
        return out, q

    def test_propose_asks_the_user_and_frees_the_slot(self):
        d = self.filled()
        out, q = self.propose(d)
        self.assertIn("Stop here and wait", out)
        self.assertEqual(json.loads(q["options"]), ["Post", "Drop it"])
        self.assertEqual(q["summary"], "Nice work, one note below.")
        self.assertIn("Nice work", q["details"])
        self.assertEqual(self.status("outbox", d), "fill")        # not the user's lines yet
        self.assertEqual(self.status("jobs", self.job), "waiting_user")   # holds no slot
        spec = importlib.util.spec_from_file_location("pg", ROOT / "scripts" / "post-guard.py")
        pg = importlib.util.module_from_spec(spec); spec.loader.exec_module(pg)
        # the state propose really leaves: the session must still not post
        self.assertIsNotNone(pg.decide(self.con, "s1", "gh pr review 1 --approve -b x"))
        q2 = self.con.execute("SELECT id FROM questions WHERE draft_id=? AND status='pending'", (d,)).fetchone()
        questions.answer(self.con, q2["id"], "Post", "notification", self.inbox)
        db.claim(self.con, self.job, "s1")
        db.set_job(self.con, self.job, "delivered")
        self.assertIsNone(pg.decide(self.con, "s1", "gh pr review 1 --approve -b x"))      # after Post: allowed

    def test_post_saves_the_proposal_as_the_users_and_sends_the_job_back(self):
        d = self.filled()
        _, q = self.propose(d)
        self.assertEqual(questions.answer(self.con, q["id"], "Post", "notification", self.inbox), "ok")
        row = self.con.execute("SELECT status, lines FROM outbox WHERE id=?", (d,)).fetchone()
        self.assertEqual(tuple(row), ("ready", "Nice work, one note below."))
        job = self.con.execute("SELECT status, note FROM jobs WHERE id=?", (self.job,)).fetchone()
        self.assertEqual(job["status"], "queued")
        self.assertTrue(job["note"].startswith("lines-ready: 1"))
        self.assertNotIn("fill:", job["note"])

    def test_a_missed_proposal_shows_in_the_inbox_and_post_there_works(self):
        d = self.filled()
        self.assertNotIn(f"draft {d}", self.cli(["outbox", "list"]))   # a fill without lines: not yet
        _, q = self.propose(d)
        out = self.cli(["outbox", "list"])
        self.assertIn(f"draft {d}", out)
        self.assertIn("not yours until then", out)
        self.cli(["outbox", "lines", str(d), "--filled"], "Nice work, one note below.")
        self.assertEqual(self.status("outbox", d), "ready")
        self.assertEqual(self.status("questions", q["id"]), "answered")     # banner closed
        self.assertEqual(self.status("jobs", self.job), "queued")

    def test_typed_answer_to_a_proposal_goes_verbatim(self):
        d = self.filled()
        _, q = self.propose(d)
        questions.answer(self.con, q["id"], "My own words.", "inbox", self.inbox)
        self.assertEqual(self.con.execute("SELECT lines FROM outbox WHERE id=?", (d,)).fetchone()[0], "My own words.")
        self.assertEqual(self.status("outbox", d), "ready")

    def test_drop_on_a_proposal_drops_the_draft(self):
        d = self.filled()
        _, q = self.propose(d)
        questions.answer(self.con, q["id"], "Drop it", "notification", self.inbox)
        self.assertEqual(self.status("outbox", d), "dropped")
        self.assertEqual(self.status("jobs", self.job), "done")

    def test_propose_only_for_a_fill_draft(self):
        d, q = self.park()                                        # pending: the user hasn't asked for a fill
        self.con.execute("UPDATE jobs SET status='delivered' WHERE id=?", (self.job,))
        out, _ = self.propose(d)
        self.assertIn("[exit", out)
        self.assertEqual(self.status("outbox", d), "pending")
        self.assertIsNone(self.con.execute("SELECT lines FROM outbox WHERE id=?", (d,)).fetchone()[0])

    def test_one_open_proposal_holds_the_job_until_every_one_is_answered(self):
        d1 = self.filled()
        self.con.execute("INSERT INTO outbox(job_id, pr_url, kind, draft, status, created_at) "
                         "VALUES(?, ?, 'reply', 'x', 'fill', 0)", (self.job, URL(1)))
        d2 = self.con.execute("SELECT MAX(id) FROM outbox").fetchone()[0]
        _, q1 = self.propose(d1)
        self.con.execute("UPDATE jobs SET status='delivered' WHERE id=?", (self.job,))
        _, q2 = self.propose(d2, "Thanks!")
        questions.answer(self.con, q1["id"], "Post", "notification", self.inbox)
        self.assertEqual(self.status("jobs", self.job), "waiting_user")   # q2 is still open
        questions.answer(self.con, q2["id"], "Post", "notification", self.inbox)
        self.assertEqual(self.status("jobs", self.job), "queued")

    def test_answer_on_the_banner_itself_never_clears_the_screen(self):
        d, q = self.park()
        questions.claim_for_showing(self.con, q["id"])
        questions.answer(self.con, q["id"], "Fill it for me", "notification", self.inbox)
        self.assertEqual(self.cleared, [])                        # live bug: it cleared (and hung)
        self.assertEqual(self.status("outbox", d), "fill")
        self.assertEqual(self.status("questions", q["id"]), "answered")

    def test_drop_ends_the_job_when_nothing_is_left(self):
        d, q = self.park()
        questions.answer(self.con, q["id"], "Drop it", "notification", self.inbox)
        self.assertEqual(self.status("outbox", d), "dropped")
        self.assertEqual(self.status("jobs", self.job), "done")

    def test_merge_decision(self):
        self.con.execute("UPDATE jobs SET head_sha='h1' WHERE id=?", (self.job,))
        d, q = self.park("decision", "Head moved: refactor only.")
        self.assertEqual(json.loads(q["options"]), ["Merge", "Re-review"])
        questions.answer(self.con, q["id"], "Merge", "notification", self.inbox)
        self.assertEqual(self.con.execute("SELECT merge_ok_sha FROM prs WHERE url=?", (URL(1),)).fetchone()[0], "h1")
        self.assertEqual(self.status("jobs", self.job), "done")

    def test_inbox_answer_closes_the_notification(self):
        d, q = self.park()
        questions.claim_for_showing(self.con, q["id"])           # on screen now
        self.cli(["outbox", "lines", str(d)], "Typed in the inbox.")
        self.assertEqual(self.status("questions", q["id"]), "answered")
        self.assertIn(q["id"], self.cleared)                      # banner removed
        self.assertEqual(questions.answer(self.con, q["id"], "Drop it", "notification", self.inbox), "already")
        self.assertEqual(self.status("outbox", d), "ready")       # a late banner click changes nothing

    def test_one_question_per_draft(self):
        d, q = self.park()
        self.assertIsNone(outbox.ask_for(self.con, d))


if __name__ == "__main__":
    unittest.main()
