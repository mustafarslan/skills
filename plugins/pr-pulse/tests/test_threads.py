"""Slack thread replies reach the daemon: an author's tag in a review thread queues a re-review.
A fake Slack client stands in for the API; no network, no gh."""
import importlib.util
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("PR_PULSE_HOME", tempfile.mkdtemp(prefix="pr-pulse-thr-"))
os.environ["PR_PULSE_NO_NOTIFY"] = "1"
sys.path.insert(0, str(ROOT / "scripts"))
import db     # noqa: E402
import slack  # noqa: E402


def load(name, path):
    spec = importlib.util.spec_from_loader(name, loader=None)
    mod = importlib.util.module_from_spec(spec)
    mod.__file__ = str(path)
    exec(compile(Path(path).read_text(), str(path), "exec"), mod.__dict__)
    return mod


daemon = load("pr_pulsed_threads", ROOT / "scripts" / "pr-pulsed.py")
URL = "https://github.com/o/r/pull/12"
CH = "CREV"


class FakeSlack:
    """Parents with replies, and every replies() call made."""
    def __init__(self):
        self.threads, self.calls, self.fail = {}, [], None

    def recent_threads(self, ch, since):
        if self.fail:
            raise slack.SlackError(f"conversations.history: {self.fail}")
        return [dict(p, reply_count=len(rs), latest_reply=rs[-1]["ts"])
                for p, rs in self.threads.values() if rs and float(p["ts"]) >= float(since)]

    def replies(self, ch, ts, oldest):
        self.calls.append((ts, oldest))
        return [r for r in self.threads[ts][1] if float(r["ts"]) > float(oldest)]

    def history(self, ch, oldest):
        if self.fail:
            raise slack.SlackError(f"conversations.history: {self.fail}")
        return []


class ThreadIngestTest(unittest.TestCase):
    def setUp(self):
        self.con = db.connect(Path(tempfile.mkdtemp(prefix="pp-")) / "pulse.db")
        self.fake = FakeSlack()
        self.saved = {k: getattr(daemon.slack, k) for k in ("recent_threads", "replies", "history", "token")}
        for k in ("recent_threads", "replies", "history"):
            setattr(daemon.slack, k, getattr(self.fake, k))
        daemon.slack.token = lambda: "x"
        self.queued = []
        self.saved_q = daemon.queue_review
        daemon.queue_review = lambda con, me, mapped, url, action, note, prio: self.queued.append((url, note)) or ""
        self.notes = []
        self.saved_n = daemon.dispatch.notify
        daemon.dispatch.notify = self.notes.append
        db.set_setting(self.con, "slack_bot_user", "UBOT")
        self.cfg = dict(db.DEFAULT_CONFIG, watch_channels=[CH], slack_user_id="UME")
        self.t0 = time.time() - 3600
        db.set_setting(self.con, f"slack_oldest:{CH}", f"{self.t0:.6f}")
        db.set_setting(self.con, f"slack_threads_from:{CH}", f"{self.t0:.6f}")

    def tearDown(self):
        for k, v in self.saved.items():
            setattr(daemon.slack, k, v)
        daemon.queue_review = self.saved_q
        daemon.dispatch.notify = self.saved_n

    def thread(self, *replies):
        pts = f"{self.t0 + 10:.6f}"
        parent = {"ts": pts, "user": "UALICE", "text": f"please review <{URL}|o/r#12>"}
        rs = [{"ts": f"{self.t0 + 20 + i:.6f}", "user": u, "text": t} for i, (u, t) in enumerate(replies)]
        self.fake.threads[pts] = (parent, rs)
        return pts

    def tick(self):
        daemon.slack_ingest(self.con, self.cfg, "me", {"o/r"})

    def test_author_tag_in_thread_queues_one_rereview(self):
        pts = self.thread(("UBOT", "Alex's review: changes requested <@UALICE>"),
                          ("UALICE", "<@UME> fixed both, please re-review"))
        self.tick()
        self.assertEqual([u for u, _ in self.queued], [URL])
        self.assertIn("thread", self.queued[0][1])
        row = self.con.execute("SELECT channel, ts, status FROM review_pool WHERE pr_url=?", (URL,)).fetchone()
        self.assertEqual((row["channel"], row["ts"], row["status"]), (CH, pts, "pulled"))  # verdict goes to this thread
        self.tick()   # nothing new: no second job, and the thread isn't read again
        self.assertEqual(len(self.queued), 1)
        self.assertEqual(len(self.fake.calls), 1)

    def test_untagged_or_mine_does_nothing(self):
        self.thread(("UALICE", "fixed both"), ("UME", "<@UME> thanks"))
        self.tick()
        self.assertEqual(self.queued, [])

    def test_later_reply_is_read_from_where_we_stopped(self):
        pts = self.thread(("UALICE", "fixed one"))
        self.tick()
        self.assertEqual(self.queued, [])
        parent, rs = self.fake.threads[pts]
        rs.append({"ts": f"{self.t0 + 40:.6f}", "user": "UALICE", "text": "<@UME> now both"})
        self.tick()
        self.assertEqual([u for u, _ in self.queued], [URL])
        self.assertEqual(self.fake.calls[-1], (pts, rs[0]["ts"]))

    def test_replies_before_first_run_are_ignored(self):
        self.thread(("UALICE", "<@UME> old tag"))
        db.set_setting(self.con, f"slack_threads_from:{CH}", f"{time.time():.6f}")
        self.tick()
        self.assertEqual(self.queued, [])

    def test_tag_on_my_own_pr_is_ignored(self):
        self.con.execute("INSERT INTO prs(url, slug, n, kind, state, head_sha) VALUES(?, 'o/r', 12, 'own', 'OPEN', 'h')", (URL,))
        self.thread(("UALICE", "<@UME> question about your PR"))
        self.tick()
        self.assertEqual(self.queued, [])

    def test_lost_channel_access_notifies_once_then_clears(self):
        self.fake.fail = "channel_not_found"
        self.tick()
        self.tick()
        self.assertEqual(len(self.notes), 1)
        self.assertIn("/invite @prpulse", self.notes[0])
        self.fake.fail = None
        self.tick()
        self.assertIsNone(db.get_setting(self.con, f"slack_err:{CH}"))
        self.fake.fail = "channel_not_found"
        self.tick()
        self.assertEqual(len(self.notes), 2)   # a new outage is reported again

    def test_network_blip_does_not_notify(self):
        self.fake.fail = "URLError"
        self.tick()
        self.assertEqual(self.notes, [])


if __name__ == "__main__":
    unittest.main()
