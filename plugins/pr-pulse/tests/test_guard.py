"""Posting guard: blocks outward posts in pr-pulse job sessions until Alex's lines are in."""
import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("PR_PULSE_HOME", tempfile.mkdtemp(prefix="pp-guard-"))
sys.path.insert(0, str(ROOT / "scripts"))
import db  # noqa: E402

spec = importlib.util.spec_from_file_location("post_guard", ROOT / "scripts" / "post-guard.py")
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)

URL = "https://github.com/o/r/pull/1"
POSTS = [
    'gh pr comment 1 --body "hi"',
    "gh pr review 1 --approve",
    'gh pr review 1 --comment -b "x"',
    'gh api repos/o/r/pulls/1/comments -f body="x"',
    "gh api -X POST repos/o/r/issues/1/comments --input c.json",
    "gh api --method PATCH repos/o/r/pulls/comments/5 -f body=y",
    "gh api graphql -f query='mutation { addPullRequestReviewThreadReply(input: {}) { clientMutationId } }'",
    "gh issue comment 1 -b x",
    'cd /tmp && gh pr comment 1 -b "x"',
]
NOT_POSTS = [
    "gh pr view 1 --json reviews",
    "gh api repos/o/r/pulls/1/comments",
    "gh api graphql -f query='query { viewer { login } }'",
    "gh api graphql -f query='mutation { resolveReviewThread(input: {threadId: \"T\"}) { thread { id } } }'",
    "gh pr checks 1",
    "git push origin HEAD",
]


class GuardTest(unittest.TestCase):
    def setUp(self):
        self.con = db.connect(Path(tempfile.mkdtemp()) / "pulse.db")
        self.job = db.enqueue(self.con, URL, "review", 3)
        db.claim(self.con, self.job, "worker")
        db.set_job(self.con, self.job, "delivered")

    def test_classifier_both_directions(self):
        for c in POSTS:
            self.assertTrue(guard.is_posting(c), c)
        for c in NOT_POSTS:
            self.assertFalse(guard.is_posting(c), c)

    def test_blocks_without_lines(self):
        for c in POSTS:
            self.assertIsNotNone(guard.decide(self.con, "worker", c), c)

    def test_allows_once_lines_are_ready(self):
        self.con.execute("INSERT INTO outbox(job_id, pr_url, kind, draft, status, lines, created_at) "
                         "VALUES(?, ?, 'review', 'd', 'ready', 'my lines', 0)", (self.job, URL))
        for c in POSTS:
            self.assertIsNone(guard.decide(self.con, "worker", c), c)

    def test_pending_draft_is_not_enough(self):
        self.con.execute("INSERT INTO outbox(job_id, pr_url, kind, draft, status, created_at) "
                         "VALUES(?, ?, 'review', 'd', 'pending', 0)", (self.job, URL))
        self.assertIsNotNone(guard.decide(self.con, "worker", POSTS[0]))

    def test_other_sessions_untouched(self):
        for c in POSTS:
            self.assertIsNone(guard.decide(self.con, "my-own-session", c), c)

    def test_finished_job_no_longer_guards(self):
        db.set_job(self.con, self.job, "done")
        self.assertIsNone(guard.decide(self.con, "worker", POSTS[0]))


if __name__ == "__main__":
    unittest.main()
