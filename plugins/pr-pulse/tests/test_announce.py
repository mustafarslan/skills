"""Announcements: sessions save the text, the daemon posts it, and a PR left unannounced is
never silent. Each gate is checked in both directions."""
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("PR_PULSE_HOME", tempfile.mkdtemp(prefix="pp-announce-"))
os.environ["PR_PULSE_NO_NOTIFY"] = "1"
sys.path.insert(0, str(ROOT / "scripts"))
import announce  # noqa: E402
import db  # noqa: E402

URL = "https://github.com/o/r/pull/7"


class FakeSlack:
    def __init__(self, fail=None):
        self.posts, self.calls, self.fail = [], [], fail

    def post(self, channel, text, thread_ts=None, as_="bot"):
        if self.fail:
            raise RuntimeError(self.fail)
        self.posts.append((channel, text))
        self.post_as = as_
        return "111.222"

    def update(self, channel, ts, text, as_="bot"):
        self.call("chat.update", {"channel": channel, "ts": ts, "text": text})
        self.update_as = as_

    def call(self, method, params=None, post=False):
        if self.fail:
            raise RuntimeError(self.fail)
        self.calls.append((method, params))
        return {"ok": True}


class AnnounceTest(unittest.TestCase):
    def setUp(self):
        self.con = db.connect(Path(tempfile.mkdtemp()) / "pulse.db")
        self.notes = []

    def run_daemon(self, slack, now=None, **kw):
        args = dict(channel="C1", token_ok=True, webhook="", who="Ada", notify=self.notes.append,
                    slack=slack, now=now)
        args.update(kw)
        return announce.run(self.con, {"announce_nudge_minutes": 10}, **args)

    def state(self, url=URL):
        r = self.con.execute("SELECT state FROM announcements WHERE url=?", (url,)).fetchone()
        return r["state"] if r else None

    def test_saved_text_is_posted_once_by_the_daemon(self):
        announce.record_open(self.con, URL, "sid1", "Add thing")
        self.assertEqual(announce.save(self.con, URL, "A clear & small change.\n"), "queued")
        s = FakeSlack()
        self.assertEqual(self.run_daemon(s)["posted"], 1)
        self.assertEqual(len(s.posts), 1)
        ch, text = s.posts[0]
        self.assertEqual(ch, "C1")
        self.assertIn("A clear &amp; small change.", text)
        self.assertIn("<https://github.com/o/r/pull/7|r#7: Add thing> · Ada", text)
        self.assertEqual(self.state(), "posted")
        self.assertTrue(announce.already_announced(self.con, URL))
        self.assertEqual(self.run_daemon(s)["posted"], 0)   # never twice
        self.assertEqual(len(s.posts), 1)

    def test_nothing_is_posted_without_saved_text(self):
        announce.record_open(self.con, URL, "sid1", "Add thing")
        s = FakeSlack()
        self.run_daemon(s)
        self.assertEqual(s.posts, [])
        self.assertEqual(self.state(), "open")

    def test_unannounced_pr_is_nudged_once_after_the_grace(self):
        announce.record_open(self.con, URL, "sid1", "Add thing")
        s = FakeSlack()
        self.assertEqual(self.run_daemon(s, now=time.time() + 60)["nudged"], 0)    # too early
        self.assertEqual(self.run_daemon(s, now=time.time() + 700)["nudged"], 1)
        self.assertIn("r#7 was opened but not announced", self.notes[-1])
        self.assertEqual(self.run_daemon(s, now=time.time() + 1400)["nudged"], 0)  # only once
        self.assertEqual([r["url"] for r in announce.waiting(self.con)], [URL])

    def test_announced_pr_is_not_nudged(self):
        announce.record_open(self.con, URL, "sid1", "")
        announce.save(self.con, URL, "Text")
        self.run_daemon(FakeSlack())
        self.assertEqual(self.run_daemon(FakeSlack(), now=time.time() + 3600)["nudged"], 0)
        self.assertEqual(announce.waiting(self.con), [])

    def test_pr_posted_by_post_sh_is_not_nudged(self):
        announce.record_open(self.con, URL, "sid1", "")
        self.con.execute("INSERT INTO announced(url, at) VALUES(?, 'x')", (URL,))
        self.assertEqual(self.run_daemon(FakeSlack(), now=time.time() + 3600)["nudged"], 0)
        self.assertEqual(self.state(), "posted")

    def test_open_is_never_recorded_for_an_announced_pr(self):
        self.con.execute("INSERT INTO announced(url, at) VALUES(?, 'x')", (URL,))
        self.assertFalse(announce.record_open(self.con, URL, "sid1", ""))
        self.assertIsNone(self.state())

    def test_failed_post_notifies_and_waits_for_the_user(self):
        announce.save(self.con, URL, "Text")
        out = self.run_daemon(FakeSlack(fail="channel_not_found"))
        self.assertEqual(out["failed"], 1)
        self.assertEqual(self.state(), "failed")
        self.assertIn("channel_not_found", self.notes[-1])
        self.assertFalse(announce.already_announced(self.con, URL))
        s = FakeSlack()
        self.run_daemon(s)
        self.assertEqual(s.posts, [])          # not retried blind
        announce.save(self.con, URL, "Text")   # the inbox re-saves it
        self.run_daemon(s)
        self.assertEqual(len(s.posts), 1)

    def test_no_slack_setup_fails_instead_of_dropping(self):
        announce.save(self.con, URL, "Text")
        self.run_daemon(FakeSlack(), token_ok=False, webhook="")
        self.assertEqual(self.state(), "failed")

    def test_saving_again_edits_the_posted_message(self):
        announce.save(self.con, URL, "First")
        s = FakeSlack()
        self.run_daemon(s)
        self.assertEqual(announce.save(self.con, URL, "Second"), "edit-queued")
        self.assertEqual(self.run_daemon(s)["edited"], 1)
        method, params = s.calls[-1]
        self.assertEqual((method, params["channel"], params["ts"]), ("chat.update", "C1", "111.222"))
        self.assertTrue(params["text"].startswith("Second\n"))
        self.assertEqual(len(s.posts), 1)            # an edit is never a new post
        self.assertEqual(self.run_daemon(s)["edited"], 0)

    def test_message_without_a_slack_id_cannot_be_edited(self):
        self.con.execute("INSERT INTO announced(url, at) VALUES(?, 'x')", (URL,))
        self.assertEqual(announce.save(self.con, URL, "New"), "cannot-edit")

    def test_dropped_pr_is_neither_posted_nor_nudged(self):
        announce.record_open(self.con, URL, "sid1", "")
        self.assertTrue(announce.drop(self.con, URL))
        s = FakeSlack()
        out = self.run_daemon(s, now=time.time() + 3600)
        self.assertEqual((out["posted"], out["nudged"], s.posts), (0, 0, []))

    def test_retry_reuses_the_saved_text(self):
        announce.save(self.con, URL, "Kept text")
        self.run_daemon(FakeSlack(fail="boom"))
        self.assertTrue(announce.retry(self.con, URL))
        s = FakeSlack()
        self.run_daemon(s)
        self.assertTrue(s.posts[0][1].startswith("Kept text\n"))
        self.assertFalse(announce.retry(self.con, URL))   # posted: nothing to retry

    def test_retry_needs_saved_text(self):
        announce.record_open(self.con, URL, "sid1", "")
        self.assertFalse(announce.retry(self.con, URL))

    def test_daemon_freshness(self):
        self.assertFalse(announce.daemon_fresh(self.con))          # never ran (or an old daemon)
        self.run_daemon(FakeSlack())
        self.assertTrue(announce.daemon_fresh(self.con))
        self.assertFalse(announce.daemon_fresh(self.con, now=time.time() + 600))
        db.set_setting(self.con, "stopped", "1")
        self.assertFalse(announce.daemon_fresh(self.con))

    def test_posting_removes_the_hooks_cached_metadata(self):
        pend = db.HOME / "pending"
        pend.mkdir(parents=True, exist_ok=True)
        f = pend / "https___github_com_o_r_pull_7.json"
        f.write_text("{}")
        other = pend / "https___github_com_o_r_pull_8.json"
        other.write_text("{}")
        announce.save(self.con, URL, "Text")
        self.run_daemon(FakeSlack())
        self.assertFalse(f.exists())
        self.assertTrue(other.exists())

    def test_stale_queued_text_is_listed(self):
        announce.save(self.con, URL, "Text")
        self.assertEqual(announce.waiting(self.con), [])           # just saved: the daemon has it
        self.con.execute("UPDATE announcements SET updated_at=? WHERE url=?", (time.time() - 900, URL))
        self.assertEqual([r["url"] for r in announce.waiting(self.con)], [URL])

    def test_bad_url_is_refused(self):
        self.assertEqual(announce.save(self.con, "https://example.com/x", "Text"), "bad-url")


class CliTest(unittest.TestCase):
    def test_cli_saves_and_lists(self):
        home = tempfile.mkdtemp()
        env = dict(os.environ, PR_PULSE_HOME=home, PATH="/usr/bin:/bin")   # no gh: title stays empty
        cli = [sys.executable, str(ROOT / "scripts" / "pr-pulse")]
        subprocess.run(cli + ["announce", "open", URL, "sid1", "Add thing"], env=env, check=True)
        out = subprocess.run(cli + ["announce", "list"], env=env, capture_output=True, text=True).stdout
        self.assertIn(URL, out)
        r = subprocess.run(cli + ["announce", URL], input="Small change.", env=env, capture_output=True,
                           text=True)
        self.assertEqual(r.returncode, 3, r.stderr)                 # no daemon has run here
        self.assertTrue(r.stdout.startswith("NOT POSTED YET"))
        con = db.connect(Path(home) / "pulse.db")
        db.set_setting(con, announce.PASS_KEY, time.time())       # a current daemon checked in
        r = subprocess.run(cli + ["announce", URL], input="Small change.", env=env, capture_output=True,
                           text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(r.stdout.startswith("saved"))
        out = subprocess.run(cli + ["announce", "list"], env=env, capture_output=True, text=True).stdout
        self.assertIn("No PR is waiting", out)
        r = subprocess.run(cli + ["announce", URL], input="  ", env=env, capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)


if __name__ == "__main__":
    unittest.main()
