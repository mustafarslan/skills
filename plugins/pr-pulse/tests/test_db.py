"""Store and core tests. Run: python3 -m unittest discover -s tests (from pr-pulse/)."""
import os
import sqlite3
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TMP = tempfile.mkdtemp(prefix="pr-pulse-test-")
os.environ["PR_PULSE_HOME"] = TMP
os.environ["PR_PULSE_CONFIG"] = str(Path(TMP) / "config.json")
sys.path.insert(0, str(ROOT / "scripts"))
import core  # noqa: E402
import db    # noqa: E402


def fresh():
    p = Path(tempfile.mkdtemp(prefix="pp-db-")) / "pulse.db"
    return db.connect(p), p


class StoreTest(unittest.TestCase):
    def test_schema_and_wal(self):
        con, _ = fresh()
        self.assertEqual(con.execute("PRAGMA journal_mode").fetchone()[0], "wal")
        self.assertEqual(con.execute("PRAGMA user_version").fetchone()[0], db.SCHEMA_VERSION)

    def test_one_active_job_per_pr_action(self):
        con, _ = fresh()
        a = db.enqueue(con, "https://github.com/o/r/pull/1", "review", 3)
        self.assertIsNotNone(a)
        self.assertIsNone(db.enqueue(con, "https://github.com/o/r/pull/1", "review", 3))
        # a different action on the same PR is fine
        self.assertIsNotNone(db.enqueue(con, "https://github.com/o/r/pull/1", "merge", 0))
        # once done, the same action may be queued again
        db.set_job(con, a, "done")
        self.assertIsNotNone(db.enqueue(con, "https://github.com/o/r/pull/1", "review", 3))

    def test_waiting_user_still_blocks_duplicate(self):
        con, _ = fresh()
        a = db.enqueue(con, "https://github.com/o/r/pull/2", "feedback", 0)
        db.set_job(con, a, "waiting_user")
        self.assertIsNone(db.enqueue(con, "https://github.com/o/r/pull/2", "feedback", 0))
        self.assertEqual(db.running_count(con), 0)  # parked on the owner: holds no slot

    def test_concurrent_claim_exactly_one_wins(self):
        con, path = fresh()
        jid = db.enqueue(con, "https://github.com/o/r/pull/3", "review", 3)
        wins, barrier = [], threading.Barrier(8)

        def worker(i):
            c = db.connect(path)
            barrier.wait()
            if db.claim(c, jid, f"s{i}"):
                wins.append(i)
        ts = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual(len(wins), 1)
        self.assertEqual(db.running_count(con), 1)

    def test_claim_rejects_non_queued(self):
        con, _ = fresh()
        jid = db.enqueue(con, "https://github.com/o/r/pull/4", "review", 3)
        db.set_job(con, jid, "cancelled")
        self.assertFalse(db.claim(con, jid, "s1"))

    def test_bad_status_rejected(self):
        con, _ = fresh()
        jid = db.enqueue(con, "https://github.com/o/r/pull/5", "review", 3)
        with self.assertRaises(ValueError):
            db.set_job(con, jid, "bogus")

    def test_posted_tsv_imported(self):
        home = Path(tempfile.mkdtemp(prefix="pp-home-"))
        (home / "posted.tsv").write_text("https://github.com/o/r/pull/9\t2026-11-01T00:00:00Z\n")
        old = db.HOME
        db.HOME = home
        try:
            con = db.connect(home / "pulse.db")
            self.assertEqual(con.execute("SELECT COUNT(*) FROM announced").fetchone()[0], 1)
        finally:
            db.HOME = old

    def test_config_clamps_pool_pull(self):
        p = Path(tempfile.mkdtemp()) / "c.json"
        p.write_text('{"pool_pull": 9}')
        self.assertEqual(db.load_config(p)["pool_pull"], 2)
        p.write_text('{"pool_pull": 0}')
        self.assertEqual(db.load_config(p)["pool_pull"], 1)


class PruneTest(unittest.TestCase):
    """30-day cleanup: deletes old finished history, never anything still in play."""

    def test_old_finished_goes_recent_and_active_stay(self):
        con, _ = fresh()
        now = 1_800_000_000.0
        old, recent = now - 31 * 86400, now - 5 * 86400
        u = "https://github.com/o/r/pull/{}".format
        con.execute("INSERT INTO events(ts, kind) VALUES(?, 'old'), (?, 'recent')", (old, recent))
        for n, status, ts in ((1, "done", old), (2, "failed", old), (3, "done", recent),
                              (4, "waiting_user", old), (5, "queued", old)):
            con.execute("INSERT INTO jobs(pr_url, action, priority, status, created_at, updated_at) "
                        "VALUES(?, 'review', 3, ?, ?, ?)", (u(n), status, ts, ts))
        con.execute("INSERT INTO outbox(pr_url, kind, draft, status, created_at, posted_at) VALUES "
                    "(?, 'reply', 'x', 'posted', ?, ?), (?, 'reply', 'y', 'pending', ?, NULL)",
                    (u(1), old, old, u(4), old))
        con.execute("INSERT INTO prs(url, slug, n, kind, state, updated_at) VALUES "
                    "(?, 'o/r', 8, 'own', 'CLOSED_OR_MERGED', ?), (?, 'o/r', 9, 'own', 'OPEN', ?), "
                    "(?, 'o/r', 4, 'own', 'CLOSED_OR_MERGED', ?)", (u(8), old, u(9), old, u(4), old))
        con.execute("INSERT INTO sessions(sid, status, seen_at) VALUES ('g', 'gone', ?), ('l', 'idle', ?)",
                    (old, old))
        con.execute("INSERT INTO slack_seen(channel, ts) VALUES ('C', ?), ('C', ?)", (f"{old:.6f}", f"{recent:.6f}"))
        con.execute("INSERT INTO repos(path, slug, added_at) VALUES ('/x', 'o/r', ?)", (old,))
        con.execute("INSERT INTO announced(url, at) VALUES (?, 'long ago')", (u(1),))

        out = db.prune(con, 30, now)

        self.assertEqual(out["events"], 1)
        self.assertEqual(sorted(r[0] for r in con.execute("SELECT pr_url FROM jobs")),
                         [u(3), u(4), u(5)])                      # recent + active jobs kept
        self.assertEqual([r[0] for r in con.execute("SELECT status FROM outbox")], ["pending"])
        self.assertEqual(sorted(r[0] for r in con.execute("SELECT n FROM prs")), [4, 9])  # open + has a job
        self.assertEqual([r[0] for r in con.execute("SELECT sid FROM sessions")], ["l"])
        self.assertEqual(con.execute("SELECT COUNT(*) FROM slack_seen").fetchone()[0], 1)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM repos").fetchone()[0], 1)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM announced").fetchone()[0], 1)

    def test_runs_at_most_daily(self):
        con, _ = fresh()
        now = 1_800_000_000.0
        self.assertIsNotNone(db.prune_if_due(con, {"retention_days": 30}, now))
        self.assertIsNone(db.prune_if_due(con, {"retention_days": 30}, now + 3600))
        self.assertIsNotNone(db.prune_if_due(con, {"retention_days": 30}, now + 86401))


class CoreTest(unittest.TestCase):
    def test_ci_state(self):
        self.assertEqual(core.ci_state([]), "none")
        self.assertEqual(core.ci_state([{"conclusion": "SUCCESS"}, {"state": "SKIPPED"}]), "green")
        self.assertEqual(core.ci_state([{"conclusion": "SUCCESS"}, {"state": "PENDING"}]), "pending")
        self.assertEqual(core.ci_state([{"conclusion": "SUCCESS"}, {"conclusion": "FAILURE"}]), "red")

    def _session(self, sid, name, status, slug="o/r"):
        return {"sessionId": sid, "name": name, "status": status, "cwd": f"/x/{slug}", "kind": "interactive"}

    def test_sync_marks_gone_but_not_on_unknown(self):
        con, _ = fresh()
        orig = core.repo_of
        core.repo_of = lambda cwd: ("/x/o/r", "o/r", "main")
        try:
            core.sync_sessions(con, [self._session("a", "one", "idle"), self._session("b", "two", "busy")])
            core.sync_sessions(con, [self._session("a", "one", "busy")])
            st = dict(con.execute("SELECT sid, status FROM sessions").fetchall())
            self.assertEqual(st, {"a": "busy", "b": "gone"})
        finally:
            core.repo_of = orig

    def test_suggest_prefers_registered_then_pr_name_then_idle(self):
        con, _ = fresh()
        orig = core.repo_of
        core.repo_of = lambda cwd: ("/x/o/r", "o/r", "main")
        try:
            core.sync_sessions(con, [self._session("a", "feature-x", "idle"),
                                     self._session("b", "recos-pr-review", "busy"),
                                     self._session("c", "other", "idle")])
            self.assertEqual(core.suggest_mapping(con)[0]["suggested"], "b")
            con.execute("UPDATE sessions SET registered=1 WHERE sid='c'")
            self.assertEqual(core.suggest_mapping(con)[0]["suggested"], "c")
        finally:
            core.repo_of = orig

    def test_describe_change(self):
        con, _ = fresh()
        pr = {"url": "https://github.com/o/r/pull/7", "number": 7, "title": "t", "author": {"login": "me"},
              "state": "OPEN", "isDraft": False, "headRefOid": "aaa", "reviewDecision": "",
              "reviews": [], "comments": [], "statusCheckRollup": [{"state": "PENDING"}]}
        old, new = core.upsert_pr(con, "o/r", pr, "own")
        self.assertEqual(core.describe_change(old, new), ["tracked"])
        old, new = core.upsert_pr(con, "o/r", pr, "own")
        self.assertEqual(core.describe_change(old, new), [])
        pr2 = dict(pr, headRefOid="bbb", reviewDecision="APPROVED", reviews=[{}],
                   statusCheckRollup=[{"conclusion": "SUCCESS"}])
        old, new = core.upsert_pr(con, "o/r", pr2, "own")
        self.assertEqual(core.describe_change(old, new),
                         ["new push", "decision - -> APPROVED", "CI pending -> green", "new review"])


if __name__ == "__main__":
    unittest.main()
