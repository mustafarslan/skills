"""post_as "user": posts and reactions come from the person's own Slack user token; reading stays
on the bot; a missing user token holds posts instead of falling back to the bot."""
import os
import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
os.environ.setdefault("PR_PULSE_HOME", tempfile.mkdtemp())

import importlib.util  # noqa: E402

spec = importlib.util.spec_from_file_location(
    "pr_pulsed", Path(__file__).resolve().parent.parent / "scripts" / "pr-pulsed.py")
daemon = importlib.util.module_from_spec(spec)
spec.loader.exec_module(daemon)

import announce  # noqa: E402
import db  # noqa: E402
import rules  # noqa: E402
import slack  # noqa: E402

URL = "https://github.com/o/r/pull/7"


class PosterTest(unittest.TestCase):
    def test_bot_unless_post_as_is_user(self):
        self.assertEqual(slack.poster({}), "bot")
        self.assertEqual(slack.poster({"post_as": "bot"}), "bot")
        self.assertEqual(slack.poster({"post_as": "user"}), "user")
        self.assertEqual(slack.poster({"post_as": "nonsense"}), "bot")

    def test_missing_user_token_names_its_variable(self):
        os.environ.pop("PR_PULSE_SLACK_USER_TOKEN", None)
        with self.assertRaisesRegex(slack.SlackError, "PR_PULSE_SLACK_USER_TOKEN"):
            slack.post("C1", "hi", as_="user")

    def test_user_token_is_sent_for_user_calls(self):
        sent = []

        class Resp:
            headers = {"x-oauth-scopes": ""}
            def read(self): return b'{"ok": true, "ts": "1.1"}'
            def __enter__(self): return self
            def __exit__(self, *a): return False
        orig = slack.urllib.request.urlopen
        slack.urllib.request.urlopen = lambda req, timeout=20: sent.append(req.get_header("Authorization")) or Resp()
        os.environ["PR_PULSE_SLACK_BOT_TOKEN"], os.environ["PR_PULSE_SLACK_USER_TOKEN"] = "xoxb-b", "xoxp-u"
        try:
            slack.post("C1", "hi", as_="user")
            slack.post("C1", "hi")
        finally:
            slack.urllib.request.urlopen = orig
            os.environ.pop("PR_PULSE_SLACK_BOT_TOKEN"), os.environ.pop("PR_PULSE_SLACK_USER_TOKEN")
        self.assertEqual(sent, ["Bearer xoxp-u", "Bearer xoxb-b"])


class VerdictAsUserTest(unittest.TestCase):
    def setUp(self):
        self.con = db.connect(Path(tempfile.mkdtemp()) / "pulse.db")
        self.con.execute("INSERT INTO prs(url, slug, n, kind, state, author) VALUES(?, 'o/r', 7, 'review', 'OPEN', 'ada')", (URL,))
        j = db.enqueue(self.con, URL, "review", 2)
        self.con.execute("UPDATE jobs SET created_at=? WHERE id=?", (time.time() - 60, j))
        db.set_job(self.con, j, "done")
        self.con.execute("INSERT INTO review_pool(pr_url, channel, ts, sharer, shared_at, status) "
                         "VALUES(?, 'C1', '1600.5', 'UADA', 1600.5, 'pulled')", (URL,))
        self.posts, self.reacted, self.unreacted, self.notes = [], [], [], []
        self.hand_added = set()      # (ts, emoji) the person already put there by hand
        self.orig = (daemon.slack.post, daemon.slack.react, daemon.slack.unreact, daemon.slack.message_exists,
                     daemon.core.run, daemon.resolve_slack_author, daemon.dispatch.notify)
        daemon.slack.post = lambda ch, text, thread=None, as_="bot": self.posts.append((thread, text, as_)) or "1"

        def react(ch, ts, name, as_="bot"):
            self.reacted.append((ts, name, as_))
            return (ts, name) not in self.hand_added
        daemon.slack.react = react
        daemon.slack.unreact = lambda ch, ts, name, as_="bot": self.unreacted.append((ts, name, as_))
        daemon.slack.message_exists = lambda ch, ts: True
        daemon.resolve_slack_author = lambda con, cfg, login, sharer: "UADA"
        daemon.dispatch.notify = self.notes.append
        self.review(99, "APPROVED")
        os.environ["PR_PULSE_SLACK_BOT_TOKEN"], os.environ["PR_PULSE_SLACK_USER_TOKEN"] = "xoxb-b", "xoxp-u"
        self.cfg = dict(db.DEFAULT_CONFIG, watch_channels=["C1"], verdict_channel="C1", my_name="Ada",
                        post_as="user", slack_user_id="UME")

    def tearDown(self):
        (daemon.slack.post, daemon.slack.react, daemon.slack.unreact, daemon.slack.message_exists,
         daemon.core.run, daemon.resolve_slack_author, daemon.dispatch.notify) = self.orig
        os.environ.pop("PR_PULSE_SLACK_BOT_TOKEN", None)
        os.environ.pop("PR_PULSE_SLACK_USER_TOKEN", None)

    def review(self, rid, state):
        def fake_run(args, cwd=None, timeout=30):
            if args[:2] == ["gh", "api"] and args[2].endswith("/reviews"):
                return f'[{{"id": {rid}, "state": "{state}"}}]'
            if args[:2] == ["gh", "api"] and "/comments" in args[2]:
                return "0"
            return None
        daemon.core.run = fake_run

    def test_reply_is_posted_as_the_user_without_a_name(self):
        daemon.post_verdicts(self.con, self.cfg, "me")
        self.assertEqual(len(self.posts), 1)
        thread, text, as_ = self.posts[0]
        self.assertEqual((thread, as_), ("1600.5", "user"))
        self.assertTrue(text.startswith("Review: approved <@UADA>"), text)
        self.assertNotIn("Ada", text)

    def test_missing_user_token_holds_the_verdict_and_never_uses_the_bot(self):
        os.environ.pop("PR_PULSE_SLACK_USER_TOKEN")
        daemon.post_verdicts(self.con, self.cfg, "me")
        daemon.post_verdicts(self.con, self.cfg, "me")
        self.assertEqual(self.posts, [])
        self.assertIsNone(self.con.execute("SELECT 1 FROM verdicts").fetchone())   # not lost: it waits
        self.assertEqual(len(self.notes), 1)                                       # told once, not every tick
        os.environ["PR_PULSE_SLACK_USER_TOKEN"] = "xoxp-u"
        daemon.post_verdicts(self.con, self.cfg, "me")
        self.assertEqual([p[2] for p in self.posts], ["user"])

    def test_refused_user_token_notifies(self):
        def refused(ch, text, thread=None, as_="bot"):
            raise daemon.slack.SlackError("chat.postMessage: token_revoked")
        daemon.slack.post = refused
        daemon.post_verdicts(self.con, self.cfg, "me")
        self.assertTrue(any("not posted" in n and "/pr-pulse:init slack" in n for n in self.notes), self.notes)

    def test_bot_mode_is_unchanged(self):
        self.cfg["post_as"] = "bot"
        daemon.post_verdicts(self.con, self.cfg, "me")
        self.assertEqual(self.posts[0][2], "bot")
        self.assertTrue(self.posts[0][1].startswith("Ada's review: approved"))

    def test_emoji_as_user_leaves_a_hand_added_reaction_alone(self):
        self.cfg["verdict_style"] = "emoji"
        self.hand_added.add(("1600.5", "white_check_mark"))
        daemon.post_verdicts(self.con, self.cfg, "me")
        self.assertEqual(self.reacted, [("1600.5", "white_check_mark", "user")])
        self.assertIsNone(self.con.execute("SELECT 1 FROM reactions").fetchone())   # not recorded as ours
        self.review(100, "CHANGES_REQUESTED")
        daemon.post_verdicts(self.con, self.cfg, "me")
        self.assertEqual(self.unreacted, [])                                       # so never taken off

    def test_bot_mode_still_owns_an_emoji_another_reviewers_bot_put_there(self):
        self.cfg.update(verdict_style="emoji", post_as="bot")
        self.hand_added.add(("1600.5", "white_check_mark"))      # the shared bot already reacted
        daemon.post_verdicts(self.con, self.cfg, "me")
        row = self.con.execute("SELECT emoji, posted_as FROM reactions").fetchone()
        self.assertEqual((row["emoji"], row["posted_as"]), ("white_check_mark", "bot"))

    def test_a_bot_reaction_is_removed_by_the_bot_after_switching_to_user(self):
        self.cfg["verdict_style"] = "emoji"
        self.con.execute("INSERT INTO reactions(pr_url, channel, ts, kind, emoji, at) "
                         "VALUES(?, 'C1', '1600.5', 'share', 'warning', 1)", (URL,))   # made by the bot earlier
        daemon.post_verdicts(self.con, self.cfg, "me")
        self.assertIn(("1600.5", "white_check_mark", "user"), self.reacted)
        self.assertIn(("1600.5", "warning", "bot"), self.unreacted)
        row = self.con.execute("SELECT emoji, posted_as FROM reactions").fetchone()
        self.assertEqual((row["emoji"], row["posted_as"]), ("white_check_mark", "user"))

    def test_same_emoji_changes_hands_from_bot_to_user(self):
        self.cfg["verdict_style"] = "emoji"
        self.con.execute("INSERT INTO reactions(pr_url, channel, ts, kind, emoji, at) "
                         "VALUES(?, 'C1', '1600.5', 'share', 'white_check_mark', 1)", (URL,))
        daemon.post_verdicts(self.con, self.cfg, "me")
        self.assertIn(("1600.5", "white_check_mark", "bot"), self.unreacted)

    def test_rereview_recycle_as_user_and_cleanup_as_user(self):
        self.cfg["verdict_style"] = "emoji"
        daemon.mark_rereview(self.con, self.cfg, URL, "C1", "1700.9", "UADA")
        self.assertEqual(self.reacted, [("1700.9", "recycle", "user")])
        self.con.execute("UPDATE prs SET state='MERGED'")
        self.con.execute("DELETE FROM jobs")
        daemon.post_verdicts(self.con, self.cfg, "me")
        self.assertIn(("1700.9", "recycle", "user"), self.unreacted)


class FromABotTest(unittest.TestCase):
    """Shapes read back from Slack on 2026-11-16: a post made with a person's user token through
    their app carries bot_id, app_id and bot_profile exactly like the shared bot's own posts."""
    BOT = {"user": "UBOTUSER", "bot_id": "B1", "app_id": "A1", "bot_profile": {"name": "pr-pulse"}}
    PERSON_VIA_APP = {"user": "UME", "bot_id": "B2", "app_id": "A2", "bot_profile": {"name": "pr-pulse (me)"}}

    def setUp(self):
        self.orig = slack.call
        slack._IS_BOT.clear()
        self.lookups = []

        def call(method, params=None, post=False, as_="bot"):
            self.lookups.append(params["user"])
            return {"user": {"id": params["user"], "is_bot": params["user"].startswith("UBOT")}}
        slack.call = call

    def tearDown(self):
        slack.call = self.orig
        slack._IS_BOT.clear()

    def test_the_bots_post_is_a_bots(self):
        self.assertTrue(slack.from_a_bot(self.BOT))

    def test_a_person_posting_through_their_app_is_a_person(self):
        self.assertFalse(slack.from_a_bot(self.PERSON_VIA_APP))

    def test_plain_messages_and_webhooks(self):
        self.assertFalse(slack.from_a_bot({"user": "UBOB"}))
        self.assertTrue(slack.from_a_bot({"bot_id": "B9", "subtype": "bot_message"}))   # no user at all

    def test_lookups_are_cached_and_a_failed_one_counts_as_a_bot(self):
        slack.from_a_bot(self.PERSON_VIA_APP), slack.from_a_bot(self.PERSON_VIA_APP)
        self.assertEqual(self.lookups, ["UME"])

        def down(*a, **k):
            raise slack.SlackError("users.info: ratelimited")
        slack.call = down
        self.assertTrue(slack.from_a_bot({"user": "UNEW", "bot_id": "B3"}))

    def test_find_share_takes_a_person_posting_through_their_app(self):
        hist = {"messages": [dict(self.BOT, ts="3.0", text=URL), dict(self.PERSON_VIA_APP, user="UBOB", ts="2.0", text=URL)]}
        orig = slack.call

        def call(method, params=None, post=False, as_="bot"):
            return hist if method == "conversations.history" else orig(method, params, post, as_)
        slack.call = call
        self.assertEqual(slack.find_share(["C1"], URL), ("C1", "2.0", "UBOB"))


class EnvFileTest(unittest.TestCase):
    def test_the_daemon_finds_the_user_token_in_the_env_file(self):
        import envfile
        orig = envfile.ENV
        envfile.ENV = Path(tempfile.mkdtemp()) / "env"
        os.environ.pop("PR_PULSE_SLACK_USER_TOKEN", None)
        try:
            envfile.set_value("PR_PULSE_SLACK_USER_TOKEN", "xoxp-from-file")
            envfile.load_into_environ()
            self.assertEqual(slack.token("user"), "xoxp-from-file")
        finally:
            envfile.ENV = orig
            os.environ.pop("PR_PULSE_SLACK_USER_TOKEN", None)


class AnnounceWithoutUserTokenTest(unittest.TestCase):
    def test_fails_loudly_and_keeps_the_daemon_fresh(self):
        con = db.connect(Path(tempfile.mkdtemp()) / "pulse.db")
        announce.record_open(con, URL, "s1", "Title")
        announce.save(con, URL, "Ready")
        os.environ.pop("PR_PULSE_SLACK_USER_TOKEN", None)
        notes = []
        out = announce.run(con, {}, channel="C1", token_ok=True, webhook="https://hooks.slack.com/x",
                           who="Ada", notify=notes.append, as_="user")
        self.assertEqual(out["failed"], 1)
        self.assertIn("PR_PULSE_SLACK_USER_TOKEN", notes[0])
        self.assertTrue(announce.daemon_fresh(con))


class OwnPostsTest(unittest.TestCase):
    def test_my_verdict_reply_and_announcement_are_never_picked_up(self):
        reply = {"user": "UME", "ts": "2.0", "text": f"Review: approved <@UADA> · <{URL}|o/r#7>"}
        self.assertEqual(rules.classify_reply(reply, {"text": URL}, "UME", "UBOT", "B1")[0], "ignore")
        ann = {"user": "UME", "ts": "3.0", "text": f"New PR\n<{URL}|o/r#7: Title>"}
        self.assertEqual(rules.classify_slack(ann, "UME", "UBOT", "B1"), ("ignore", "my own share"))

    def test_a_teammates_announcement_as_themselves_is_a_share(self):
        ann = {"user": "UBOB", "ts": "3.0", "text": f"New PR\n<{URL}|o/r#7: Title>"}
        self.assertEqual(rules.classify_slack(ann, "UME", "UBOT", "B1"), ("pool", [URL]))


class FakeSlack:
    def __init__(self):
        self.posts, self.updates = [], []

    def post(self, channel, text, thread_ts=None, as_="bot"):
        self.posts.append((text, as_))
        return "111.222"

    def update(self, channel, ts, text, as_="bot"):
        self.updates.append((text, as_))


class AnnounceAsUserTest(unittest.TestCase):
    def setUp(self):
        self.con = db.connect(Path(tempfile.mkdtemp()) / "pulse.db")
        self.notes = []

    def run_once(self, s, **kw):
        args = dict(channel="C1", token_ok=False, webhook="https://hooks.slack.com/services/x", who="Ada",
                    notify=self.notes.append, slack=s, as_="user")
        args.update(kw)
        return announce.run(self.con, {}, **args)

    def test_posts_as_the_user_without_the_name_and_never_via_the_webhook(self):
        announce.record_open(self.con, URL, "s1", "Title")
        announce.save(self.con, URL, "Ready for review")
        s = FakeSlack()
        self.assertEqual(self.run_once(s)["posted"], 1)
        text, as_ = s.posts[0]
        self.assertEqual(as_, "user")
        self.assertNotIn("· Ada", text)
        self.assertEqual(self.con.execute("SELECT posted_as FROM announcements").fetchone()[0], "user")

    def test_a_bot_announcement_is_edited_by_the_bot_with_its_name(self):
        announce.record_open(self.con, URL, "s1", "Title")
        announce.save(self.con, URL, "First")
        s = FakeSlack()
        self.run_once(s, as_="bot", token_ok=True)
        announce.save(self.con, URL, "Second")
        self.run_once(s)                                          # post_as is user now
        text, as_ = s.updates[0]
        self.assertEqual(as_, "bot")
        self.assertIn("· Ada", text)


class MigrationTest(unittest.TestCase):
    def test_v10_store_gets_posted_as_defaulting_to_bot(self):
        path = Path(tempfile.mkdtemp()) / "pulse.db"
        con = db.connect(path)                        # a current store, then turned back into v10
        con.execute("DROP TABLE reactions")
        con.execute("CREATE TABLE reactions(pr_url TEXT NOT NULL, channel TEXT NOT NULL, ts TEXT NOT NULL, "
                    "kind TEXT NOT NULL, emoji TEXT NOT NULL, at REAL NOT NULL, PRIMARY KEY(channel, ts))")
        con.execute("INSERT INTO reactions VALUES('u', 'C1', '1.0', 'share', 'warning', 1)")
        con.execute("DROP TABLE announcements")
        con.execute("CREATE TABLE announcements(url TEXT PRIMARY KEY, opened_at REAL, sid TEXT, title TEXT, "
                    "text TEXT, state TEXT NOT NULL DEFAULT 'open', ts TEXT, channel TEXT, edit_text TEXT, "
                    "error TEXT, nudged_at REAL, updated_at REAL)")
        con.execute("INSERT INTO announcements(url, state, ts) VALUES('u', 'posted', '2.0')")
        con.execute("PRAGMA user_version=10")
        con.close()
        con = db.connect(path)
        self.assertEqual(con.execute("SELECT posted_as FROM reactions").fetchone()[0], "bot")
        self.assertEqual(con.execute("SELECT posted_as FROM announcements").fetchone()[0], "bot")
        self.assertEqual(con.execute("PRAGMA user_version").fetchone()[0], db.SCHEMA_VERSION)


if __name__ == "__main__":
    unittest.main()
