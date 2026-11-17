"""GitHub-side re-reviews: a "Re-request review" click and a push after the user's requested
changes each queue one re-review, with no Slack tag. gh is stubbed; no network."""
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("PR_PULSE_HOME", tempfile.mkdtemp(prefix="pr-pulse-gh-"))
os.environ["PR_PULSE_NO_NOTIFY"] = "1"
sys.path.insert(0, str(ROOT / "scripts"))
import db     # noqa: E402
import rules  # noqa: E402


def load(name, path):
    spec = importlib.util.spec_from_loader(name, loader=None)
    mod = importlib.util.module_from_spec(spec)
    mod.__file__ = str(path)
    exec(compile(Path(path).read_text(), str(path), "exec"), mod.__dict__)
    return mod


daemon = load("pr_pulsed_gh_rereview", ROOT / "scripts" / "pr-pulsed.py")
ME = "me"
URL = "https://github.com/o/r/pull/7"
OLD, NEW = "a" * 40, "b" * 40


def review(who, state, sha, t):
    return {"author": {"login": who}, "state": state, "commit": {"oid": sha}, "submittedAt": t}


def pr(head=NEW, reviews=(), decision="CHANGES_REQUESTED", comments=()):
    return {"url": URL, "number": 7, "title": "t", "state": "OPEN", "isDraft": False,
            "author": {"login": "alice"}, "headRefOid": head, "reviewDecision": decision,
            "reviews": list(reviews), "comments": list(comments), "statusCheckRollup": []}


MINE = review(ME, "CHANGES_REQUESTED", OLD, "2026-11-13T10:00:00Z")
REPLY = review("alice", "COMMENTED", NEW, "2026-11-14T09:00:00Z")   # a thread reply


class PushedAfterChangesRequestedRuleTest(unittest.TestCase):
    def test_push_and_a_thread_reply_after_my_changes_requested(self):
        p = pr(reviews=[MINE, REPLY])
        self.assertEqual(rules.pushed_after_changes_requested(p, ME), OLD)

    def test_push_and_a_pr_comment_from_the_author(self):
        p = pr(reviews=[MINE], comments=[{"author": {"login": "alice"},
                                          "createdAt": "2026-11-14T09:00:00Z"}])
        self.assertEqual(rules.pushed_after_changes_requested(p, ME), OLD)

    def test_a_push_alone_such_as_a_rebase_is_not_due(self):
        p = pr(reviews=[MINE])
        self.assertEqual(rules.pushed_after_changes_requested(p, ME), "")

    def test_an_author_reply_before_my_review_does_not_count(self):
        early = review("alice", "COMMENTED", OLD, "2026-11-12T09:00:00Z")
        other = {"author": {"login": "bob"}, "createdAt": "2026-11-14T09:00:00Z"}
        p = pr(reviews=[early, MINE], comments=[other])
        self.assertEqual(rules.pushed_after_changes_requested(p, ME), "")

    def test_a_later_comment_review_keeps_changes_requested_standing(self):
        p = pr(reviews=[MINE, REPLY, review(ME, "COMMENTED", NEW, "2026-11-14T10:00:00Z")])
        self.assertEqual(rules.pushed_after_changes_requested(p, ME), OLD)

    def test_head_unchanged_is_not_due(self):
        p = pr(head=OLD, reviews=[MINE, REPLY])
        self.assertEqual(rules.pushed_after_changes_requested(p, ME), "")

    def test_a_later_approval_or_dismissal_clears_it(self):
        for state in ("APPROVED", "DISMISSED"):
            p = pr(reviews=[MINE, REPLY, review(ME, state, OLD, "2026-11-14T10:00:00Z")])
            self.assertEqual(rules.pushed_after_changes_requested(p, ME), "", state)

    def test_someone_elses_changes_requested_is_not_mine(self):
        p = pr(reviews=[review("bob", "CHANGES_REQUESTED", OLD, "2026-11-13T10:00:00Z"), REPLY])
        self.assertEqual(rules.pushed_after_changes_requested(p, ME), "")


class DaemonTest(unittest.TestCase):
    def setUp(self):
        self.con = db.connect(Path(tempfile.mkdtemp(prefix="pp-")) / "pulse.db")
        self.cfg = dict(db.DEFAULT_CONFIG)
        self.searches, self.pr = [], None
        self.saved = (daemon.core.run, daemon.view_pr)

        def run(cmd, timeout=None):
            self.searches.append(" ".join(cmd))
            return json.dumps([{"url": URL}])
        daemon.core.run = run
        daemon.view_pr = lambda url: self.pr

    def tearDown(self):
        daemon.core.run, daemon.view_pr = self.saved

    def jobs(self):
        return [(r["action"], r["note"]) for r in self.con.execute(
            "SELECT action, note FROM jobs WHERE pr_url=? ORDER BY id", (URL,)).fetchall()]

    # -- "Re-request review" ------------------------------------------------------------
    def test_first_request_is_a_plain_review(self):
        self.pr = pr(reviews=[], decision="REVIEW_REQUIRED")
        daemon.review_requested(self.con, ME, {"o/r"})
        self.assertEqual([a for a, _ in self.jobs()], ["review"])

    def test_rerequest_after_my_review_is_a_rereview_even_when_approved_and_same_head(self):
        self.pr = pr(head=OLD, decision="APPROVED",
                     reviews=[review(ME, "CHANGES_REQUESTED", OLD, "2026-11-13T10:00:00Z"),
                              review("bob", "APPROVED", OLD, "2026-11-13T11:00:00Z")])
        daemon.review_requested(self.con, ME, {"o/r"})
        (action, note), = self.jobs()
        self.assertEqual(action, "re-review")
        self.assertIn("GitHub re-requested your review", note)

    def test_rerequest_queues_once_per_head(self):
        self.pr = pr(head=OLD, reviews=[review(ME, "CHANGES_REQUESTED", OLD, "2026-11-13T10:00:00Z")])
        daemon.review_requested(self.con, ME, {"o/r"})
        self.con.execute("UPDATE jobs SET status='done'")
        daemon.review_requested(self.con, ME, {"o/r"})
        self.assertEqual(len(self.jobs()), 1)

    def test_rerequest_in_an_unmapped_repo_is_ignored(self):
        self.pr = pr(reviews=[review(ME, "CHANGES_REQUESTED", OLD, "2026-11-13T10:00:00Z")])
        daemon.review_requested(self.con, ME, {"other/repo"})
        self.assertEqual(self.jobs(), [])

    # -- push after my requested changes --------------------------------------------------
    def test_push_after_changes_requested_queues_a_rereview(self):
        self.pr = pr(reviews=[MINE, REPLY])
        daemon.pushed_since_changes(self.con, self.cfg, ME, {"o/r"}, now=1000.0)
        (action, note), = self.jobs()
        self.assertEqual(action, "re-review")
        self.assertIn(f"new commits and a reply after your requested changes at {OLD[:9]}", note)
        self.assertIn("review:changes_requested", self.searches[0])

    def test_no_push_since_changes_requested_queues_nothing(self):
        self.pr = pr(head=OLD, reviews=[review(ME, "CHANGES_REQUESTED", OLD, "2026-11-13T10:00:00Z")])
        daemon.pushed_since_changes(self.con, self.cfg, ME, {"o/r"}, now=1000.0)
        self.assertEqual(self.jobs(), [])

    def test_rebase_only_push_queues_nothing(self):
        self.pr = pr(reviews=[MINE])
        daemon.pushed_since_changes(self.con, self.cfg, ME, {"o/r"}, now=1000.0)
        self.assertEqual(self.jobs(), [])

    def test_push_rereview_queues_once_per_head(self):
        self.pr = pr(reviews=[MINE, REPLY])
        daemon.pushed_since_changes(self.con, self.cfg, ME, {"o/r"}, now=1000.0)
        self.con.execute("UPDATE jobs SET status='done'")
        daemon.pushed_since_changes(self.con, self.cfg, ME, {"o/r"}, now=2000.0)
        self.assertEqual(len(self.jobs()), 1)

    def test_search_runs_at_most_once_per_poll_interval(self):
        self.pr = pr(head=OLD, reviews=[review(ME, "CHANGES_REQUESTED", OLD, "2026-11-13T10:00:00Z")])
        daemon.pushed_since_changes(self.con, self.cfg, ME, {"o/r"}, now=1000.0)
        daemon.pushed_since_changes(self.con, self.cfg, ME, {"o/r"}, now=1100.0)
        self.assertEqual(len(self.searches), 1)
        daemon.pushed_since_changes(self.con, self.cfg, ME, {"o/r"}, now=1000.0 + 301)
        self.assertEqual(len(self.searches), 2)


if __name__ == "__main__":
    unittest.main()
