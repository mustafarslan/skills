"""Verdicts are only ever a thread reply under the PR's share message; never a new top-level post."""
import importlib.util
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("PR_PULSE_HOME", tempfile.mkdtemp(prefix="pp-verdict-"))
os.environ["PR_PULSE_NO_NOTIFY"] = "1"
sys.path.insert(0, str(ROOT / "scripts"))
import db  # noqa: E402

spec = importlib.util.spec_from_loader("pr_pulsed_v", loader=None)
daemon = importlib.util.module_from_spec(spec)
daemon.__file__ = str(ROOT / "scripts" / "pr-pulsed.py")
exec(compile((ROOT / "scripts" / "pr-pulsed.py").read_text(), daemon.__file__, "exec"), daemon.__dict__)

URL = "https://github.com/o/r/pull/7"


class VerdictBase(unittest.TestCase):
    def setUp(self):
        self.con = db.connect(Path(tempfile.mkdtemp()) / "pulse.db")
        self.con.execute("INSERT INTO prs(url, slug, n, kind, state, author) VALUES(?, 'o/r', 7, 'review', 'OPEN', 'ada')", (URL,))
        j = db.enqueue(self.con, URL, "review", 2)
        self.con.execute("UPDATE jobs SET created_at=? WHERE id=?", (time.time() - 60, j))
        self.con.execute("INSERT INTO outbox(job_id, pr_url, kind, draft, status, lines, created_at, posted_at) "
                         "VALUES(?, ?, 'review', 'd', 'posted', 'Solid change.', 0, ?)", (j, URL, time.time()))
        db.set_job(self.con, j, "done")
        self.posts = []
        self.orig = (daemon.slack.token, daemon.slack.post, daemon.slack.find_share, daemon.core.run,
                     daemon.resolve_slack_author, daemon.slack.message_exists)
        self.gone = set()                                       # share ts values Slack says were deleted
        daemon.slack.message_exists = lambda ch, ts: ts not in self.gone
        os.environ["PR_PULSE_SLACK_BOT_TOKEN"] = "x"
        daemon.slack.post = lambda ch, text, thread=None, as_="bot": self.posts.append((ch, thread, text)) or "1"
        daemon.resolve_slack_author = lambda con, cfg, login, sharer: "UADA"

        def fake_run(args, cwd=None, timeout=30):
            if args[:2] == ["gh", "api"] and args[2].endswith("/reviews"):
                return '[{"id": 99, "state": "COMMENTED"}]'
            if args[:2] == ["gh", "api"] and "/reviews/99/comments" in args[2]:
                return "2"
            return None
        daemon.core.run = fake_run
        self.cfg = dict(db.DEFAULT_CONFIG, watch_channels=["C1"], verdict_channel="C1", my_name="Ada")

    def tearDown(self):
        (daemon.slack.token, daemon.slack.post, daemon.slack.find_share, daemon.core.run,
         daemon.resolve_slack_author, daemon.slack.message_exists) = self.orig
        os.environ.pop("PR_PULSE_SLACK_BOT_TOKEN", None)


class VerdictTest(VerdictBase):
    def test_no_share_message_means_no_post_at_all(self):
        daemon.slack.find_share = lambda chans, url, skip_users=(), days=30: None
        daemon.post_verdicts(self.con, self.cfg, "me")
        self.assertEqual(self.posts, [])                       # never a top-level message
        self.assertTrue(self.con.execute("SELECT 1 FROM events WHERE kind='verdict.no_thread'").fetchone())

    def test_found_share_gets_a_thread_reply_with_the_lines(self):
        daemon.slack.find_share = lambda chans, url, skip_users=(), days=30: ("C1", "1700.01", "USHARER")
        daemon.post_verdicts(self.con, self.cfg, "me")
        self.assertEqual(len(self.posts), 1)
        ch, thread, text = self.posts[0]
        self.assertEqual((ch, thread), ("C1", "1700.01"))       # a reply in that thread
        self.assertIn("Ada's review: comments added <@UADA>", text)
        self.assertIn("> Solid change.", text)
        daemon.post_verdicts(self.con, self.cfg, "me")          # same review: posted once
        self.assertEqual(len(self.posts), 1)

    def test_pool_share_is_used_without_searching(self):
        self.con.execute("INSERT INTO review_pool(pr_url, channel, ts, sharer, shared_at, status) "
                         "VALUES(?, 'C1', '1600.5', 'USH', 1600.5, 'pulled')", (URL,))
        daemon.slack.find_share = lambda *a, **k: self.fail("should not search")
        daemon.post_verdicts(self.con, self.cfg, "me")
        self.assertEqual(self.posts[0][1], "1600.5")


class StaleShareTest(VerdictBase):
    """A reply to a deleted share message lands at the channel root, so a deleted one is never used."""

    def setUp(self):
        super().setUp()
        self.con.execute("INSERT INTO review_pool(pr_url, channel, ts, sharer, shared_at, status) "
                         "VALUES(?, 'C1', '1600.5', 'USH', 1600.5, 'pulled')", (URL,))

    def test_live_share_is_used(self):
        daemon.slack.find_share = lambda *a, **k: self.fail("should not search")
        daemon.post_verdicts(self.con, self.cfg, "me")
        self.assertEqual(self.posts[0][1], "1600.5")

    def test_deleted_share_moves_to_the_repost(self):
        self.gone.add("1600.5")
        daemon.slack.find_share = lambda chans, url, skip_users=(), days=30: ("C1", "1670.9", "USH")
        daemon.post_verdicts(self.con, self.cfg, "me")
        self.assertEqual([(p[0], p[1]) for p in self.posts], [("C1", "1670.9")])
        row = self.con.execute("SELECT ts, status FROM review_pool WHERE pr_url=?", (URL,)).fetchone()
        self.assertEqual((row["ts"], row["status"]), ("1670.9", "pulled"))
        self.assertTrue(self.con.execute("SELECT 1 FROM events WHERE kind='verdict.share_moved'").fetchone())

    def test_deleted_share_with_no_repost_posts_nothing(self):
        self.gone.add("1600.5")
        daemon.slack.find_share = lambda chans, url, skip_users=(), days=30: None
        daemon.post_verdicts(self.con, self.cfg, "me")
        self.assertEqual(self.posts, [])                       # never a top-level message
        self.assertTrue(self.con.execute("SELECT 1 FROM events WHERE kind='verdict.share_deleted'").fetchone())
        self.assertTrue(self.con.execute("SELECT 1 FROM events WHERE kind='verdict.no_thread'").fetchone())

    def test_search_returning_the_same_deleted_message_posts_nothing(self):
        self.gone.add("1600.5")
        daemon.slack.find_share = lambda chans, url, skip_users=(), days=30: ("C1", "1600.5", "USH")
        daemon.post_verdicts(self.con, self.cfg, "me")
        self.assertEqual(self.posts, [])

    def test_check_failure_keeps_the_stored_share(self):
        def boom(ch, ts):
            raise daemon.slack.SlackError("conversations.replies: ratelimited")
        daemon.slack.message_exists = boom
        daemon.slack.find_share = lambda *a, **k: self.fail("should not search")
        daemon.post_verdicts(self.con, self.cfg, "me")
        self.assertEqual(self.posts[0][1], "1600.5")
        self.assertTrue(self.con.execute("SELECT 1 FROM events WHERE kind='verdict.share_unchecked'").fetchone())


class MessageExistsTest(unittest.TestCase):
    def setUp(self):
        self.orig = daemon.slack.call

    def tearDown(self):
        daemon.slack.call = self.orig

    def test_not_found_errors_mean_gone(self):
        for err in ("thread_not_found", "message_not_found"):
            def gone(method, params=None, post=False, err=err):
                raise daemon.slack.SlackError(f"{method}: {err}")
            daemon.slack.call = gone
            self.assertFalse(daemon.slack.message_exists("C1", "1.2"))

    def test_present_message(self):
        daemon.slack.call = lambda method, params=None, post=False: {"ok": True, "messages": [{"ts": "1.2"}]}
        self.assertTrue(daemon.slack.message_exists("C1", "1.2"))

    def test_other_errors_raise(self):
        def fail(method, params=None, post=False):
            raise daemon.slack.SlackError(f"{method}: ratelimited")
        daemon.slack.call = fail
        with self.assertRaises(daemon.slack.SlackError):
            daemon.slack.message_exists("C1", "1.2")


class EmojiVerdictTest(VerdictBase):
    """verdict_style "emoji": reactions instead of replies, only on the author's share message and
    the author's own re-review request; each round swaps only pr-pulse's own reaction."""

    def setUp(self):
        super().setUp()
        self.reacted, self.unreacted = [], []
        self.orig_r = (daemon.slack.react, daemon.slack.unreact)
        daemon.slack.react = lambda ch, ts, name, as_="bot": self.reacted.append((ch, ts, name)) or True
        daemon.slack.unreact = lambda ch, ts, name, as_="bot": self.unreacted.append((ch, ts, name))
        self.cfg["verdict_style"] = "emoji"
        self.con.execute("INSERT INTO review_pool(pr_url, channel, ts, sharer, shared_at, status) "
                         "VALUES(?, 'C1', '1600.5', 'UADA', 1600.5, 'pulled')", (URL,))

    def tearDown(self):
        daemon.slack.react, daemon.slack.unreact = self.orig_r
        super().tearDown()

    def review(self, rid, state):
        def fake_run(args, cwd=None, timeout=30):
            if args[:2] == ["gh", "api"] and args[2].endswith("/reviews"):
                return f'[{{"id": {rid}, "state": "{state}"}}]'
            if args[:2] == ["gh", "api"] and "/comments" in args[2]:
                return "0"
            return None
        daemon.core.run = fake_run

    def test_emoji_mode_reacts_and_never_replies(self):
        self.review(99, "APPROVED")
        daemon.post_verdicts(self.con, self.cfg, "me")
        self.assertEqual(self.posts, [])
        self.assertEqual(self.reacted, [("C1", "1600.5", "white_check_mark")])

    def test_reply_mode_never_reacts(self):
        self.cfg["verdict_style"] = "reply"
        self.review(99, "APPROVED")
        daemon.post_verdicts(self.con, self.cfg, "me")
        self.assertEqual(self.reacted, [])
        self.assertEqual(len(self.posts), 1)

    def test_next_round_swaps_only_our_own_emoji(self):
        self.review(98, "CHANGES_REQUESTED")
        daemon.post_verdicts(self.con, self.cfg, "me")
        self.assertEqual(self.reacted, [("C1", "1600.5", "warning")])
        self.review(99, "APPROVED")
        daemon.post_verdicts(self.con, self.cfg, "me")
        self.assertEqual(self.reacted[-1], ("C1", "1600.5", "white_check_mark"))
        self.assertEqual(self.unreacted, [("C1", "1600.5", "warning")])      # only the one we added
        self.review(100, "APPROVED")                                          # same verdict again
        daemon.post_verdicts(self.con, self.cfg, "me")
        self.assertEqual(len(self.reacted), 2)                                # nothing changes

    def test_rereview_request_from_the_author_gets_recycle_then_the_verdict(self):
        daemon.mark_rereview(self.con, self.cfg, URL, "C1", "1700.9", "UADA")
        self.assertEqual(self.reacted, [("C1", "1700.9", "recycle")])
        self.review(99, "APPROVED")
        daemon.post_verdicts(self.con, self.cfg, "me")
        self.assertIn(("C1", "1700.9", "white_check_mark"), self.reacted)
        self.assertIn(("C1", "1700.9", "recycle"), self.unreacted)
        self.assertIn(("C1", "1600.5", "white_check_mark"), self.reacted)

    def test_someone_elses_tag_gets_no_emoji(self):
        daemon.mark_rereview(self.con, self.cfg, URL, "C1", "1700.9", "UBOB")
        self.assertEqual(self.reacted, [])

    def test_reply_mode_puts_nothing_on_a_rereview_request(self):
        self.cfg["verdict_style"] = "reply"
        daemon.mark_rereview(self.con, self.cfg, URL, "C1", "1700.9", "UADA")
        self.assertEqual(self.reacted, [])

    def test_missing_scope_falls_back_to_the_reply(self):
        def no_scope(ch, ts, name, as_="bot"):
            raise daemon.slack.SlackError("reactions.add: missing_scope")
        daemon.slack.react = no_scope
        self.review(99, "APPROVED")
        daemon.post_verdicts(self.con, self.cfg, "me")
        self.assertEqual(len(self.posts), 1)                                  # the verdict isn't lost
        self.assertTrue(self.con.execute("SELECT 1 FROM events WHERE kind='reaction.failed'").fetchone())

    def test_recycle_never_sticks(self):
        daemon.mark_rereview(self.con, self.cfg, URL, "C1", "1700.9", "UADA")
        self.con.execute("UPDATE prs SET state='MERGED'")
        self.review(99, "APPROVED")
        self.con.execute("DELETE FROM jobs")                                  # no new verdict this tick
        daemon.post_verdicts(self.con, self.cfg, "me")
        self.assertIn(("C1", "1700.9", "recycle"), self.unreacted)
        self.assertIsNone(self.con.execute("SELECT 1 FROM reactions WHERE ts='1700.9'").fetchone())


class EmojiMapTest(unittest.TestCase):
    def test_every_announced_verdict_has_an_emoji(self):
        import rules
        for state, inline in (("APPROVED", 0), ("APPROVED", 2), ("CHANGES_REQUESTED", 0), ("COMMENTED", 1)):
            self.assertIsNotNone(rules.verdict_emoji(rules.verdict_for(state, inline)))
        self.assertEqual(rules.verdict_emoji("request changes"), "warning")
        self.assertIsNone(rules.verdict_emoji(None))

    def test_manifest_asks_for_reactions(self):
        import json
        m = json.loads((ROOT / "slack" / "manifest-full.json").read_text())
        self.assertIn("reactions:write", m["oauth_config"]["scopes"]["bot"])


if __name__ == "__main__":
    unittest.main()
