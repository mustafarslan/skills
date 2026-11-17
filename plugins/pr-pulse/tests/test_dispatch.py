"""Dispatch, pool, outbox and daemon-flow tests against a temp store. No gh, no Slack, no claude."""
import importlib.util
import io
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOME = tempfile.mkdtemp(prefix="pr-pulse-disp-")
os.environ["PR_PULSE_HOME"] = HOME
os.environ["PR_PULSE_NO_NOTIFY"] = "1"
sys.path.insert(0, str(ROOT / "scripts"))
import db        # noqa: E402
import dispatch  # noqa: E402
import rules     # noqa: E402


def load(name, path):
    spec = importlib.util.spec_from_loader(name, loader=None)
    mod = importlib.util.module_from_spec(spec)
    mod.__file__ = str(path)
    code = Path(path).read_text()
    exec(compile(code, str(path), "exec"), mod.__dict__)
    return mod


daemon = load("pr_pulsed", ROOT / "scripts" / "pr-pulsed.py")
cli = load("pr_pulse_cli", ROOT / "scripts" / "pr-pulse")

URL = "https://github.com/o/r/pull/{}"


class Base(unittest.TestCase):
    def setUp(self):
        self.path = Path(tempfile.mkdtemp(prefix="pp-")) / "pulse.db"
        self.con = db.connect(self.path)
        self.con.execute("INSERT INTO repos(path, slug, added_at) VALUES('/x/r', 'o/r', 0)")
        for n in range(1, 8):
            self.con.execute("INSERT INTO prs(url, slug, n, kind, state, head_sha) VALUES(?, 'o/r', ?, "
                             "'review', 'OPEN', 'h')", (URL.format(n), n))
        self.cfg = dict(db.DEFAULT_CONFIG, spawn_workers=False)
        # Dispatch logic only: every skill is available (test_skills.py covers the real lookup,
        # which on CI finds no personal skills).
        self._orig_skill = dispatch.core.skill_source
        dispatch.core.skill_source = lambda skill, repo_root=None: "personal"
        self.spawned = []
        self._orig_spawn = dispatch.spawn_worker
        dispatch.spawn_worker = lambda con, job, cfg, dry=False: (
            self.spawned.append(job["id"]) or db.claim(con, job["id"], "name:w") and
            db.set_job(con, job["id"], "delivered"))

    def tearDown(self):
        dispatch.spawn_worker = self._orig_spawn
        dispatch.core.skill_source = self._orig_skill

    def session(self, sid, status="idle", registered=1, live=True, slug="o/r"):
        self.con.execute("INSERT OR REPLACE INTO sessions(sid, name, slug, status, registered, seen_at) "
                         "VALUES(?,?,?,?,?,?)", (sid, sid, slug, status, registered, time.time()))
        dispatch.INBOX.mkdir(parents=True, exist_ok=True)
        live_f = dispatch.INBOX / f"{sid}.live"
        if live:
            live_f.touch()
        elif live_f.exists():
            live_f.unlink()


class PickTest(Base):
    def test_only_registered_ready_live_same_repo(self):
        self.session("stuck", status="waiting")
        self.session("unreg", registered=0)
        self.session("deaf", live=False)
        self.session("other", slug="o/other")
        self.assertIsNone(dispatch.pick_session(self.con, "o/r"))
        self.session("good")
        self.assertEqual(dispatch.pick_session(self.con, "o/r"), "good")

    def test_session_with_a_job_is_not_picked_again(self):
        self.session("good")
        j = db.enqueue(self.con, URL.format(1), "review", 3)
        db.claim(self.con, j, "good")
        self.assertIsNone(dispatch.pick_session(self.con, "o/r"))

    def test_sticky_session_wins_even_unregistered(self):
        self.session("a")
        self.session("drafter", registered=0)
        self.assertEqual(dispatch.pick_session(self.con, "o/r", sticky="drafter"), "drafter")
        self.session("drafter", status="waiting", registered=0)
        self.assertEqual(dispatch.pick_session(self.con, "o/r", sticky="drafter"), "a")

    def test_busy_with_a_live_watcher_still_gets_work(self):
        """Scratch-test finding: a running Monitor keeps a session 'busy' while it does nothing."""
        self.session("watching", status="busy")
        self.assertEqual(dispatch.pick_session(self.con, "o/r"), "watching")


class DispatchTest(Base):
    def test_pool_size_caps_dispatch_and_priority_order(self):
        self.cfg["spawn_workers"] = True
        ids = [db.enqueue(self.con, URL.format(n), "review", p) for n, p in ((1, 3), (2, 0), (3, 1), (4, 2))]
        self.assertEqual(dispatch.dispatch(self.con, self.cfg), 3)
        self.assertEqual(self.spawned, [ids[1], ids[2], ids[3]])       # priority 0,1,2 first
        self.assertEqual(dispatch.dispatch(self.con, self.cfg), 0)    # pool full
        db.set_job(self.con, ids[1], "done")
        self.assertEqual(dispatch.dispatch(self.con, self.cfg), 1)    # one slot freed

    def test_waiting_user_frees_its_slot(self):
        self.cfg["spawn_workers"] = True
        ids = [db.enqueue(self.con, URL.format(n), "review", 3) for n in range(1, 5)]
        dispatch.dispatch(self.con, self.cfg)
        db.set_job(self.con, ids[0], "waiting_user")
        self.assertEqual(dispatch.dispatch(self.con, self.cfg), 1)

    def test_delivery_writes_inbox_line(self):
        self.session("s1")
        j = db.enqueue(self.con, URL.format(1), "review", 3)
        self.assertEqual(dispatch.dispatch(self.con, self.cfg), 1)
        line = json.loads((dispatch.INBOX / "s1.jsonl").read_text().splitlines()[-1])
        self.assertEqual((line["job"], line["action"], line["ref"]), (j, "review", "o/r#1"))
        self.assertEqual(self.con.execute("SELECT status, sid FROM jobs WHERE id=?", (j,)).fetchone()[:],
                         ("delivered", "s1"))

    def test_no_session_and_no_workers_means_wait(self):
        db.enqueue(self.con, URL.format(1), "review", 3)
        self.assertEqual(dispatch.dispatch(self.con, self.cfg), 0)

    def test_dry_run_changes_nothing(self):
        self.session("s1")
        j = db.enqueue(self.con, URL.format(1), "review", 3)
        dispatch.dispatch(self.con, self.cfg, dry=True)
        self.assertEqual(self.con.execute("SELECT status FROM jobs WHERE id=?", (j,)).fetchone()[0], "queued")

    def test_once_per_head(self):
        j = db.enqueue(self.con, URL.format(1), "merge", 0, head_sha="h1", once_per_head=True)
        db.set_job(self.con, j, "failed")
        self.assertIsNone(db.enqueue(self.con, URL.format(1), "merge", 0, head_sha="h1", once_per_head=True))
        self.assertIsNotNone(db.enqueue(self.con, URL.format(1), "merge", 0, head_sha="h2", once_per_head=True))

    def test_stale_requeue_once_then_fail_but_not_while_busy(self):
        self.session("s1")
        j = db.enqueue(self.con, URL.format(1), "review", 3)
        dispatch.dispatch(self.con, self.cfg)
        old = time.time() - 3600    # stale (45 min), not yet stalled (120 min)
        self.con.execute("UPDATE jobs SET heartbeat_at=?, updated_at=? WHERE id=?", (old, old, j))
        self.session("s1", status="busy")
        dispatch.recover_stale(self.con, self.cfg)
        self.assertEqual(self.con.execute("SELECT status FROM jobs WHERE id=?", (j,)).fetchone()[0], "delivered")
        self.session("s1", status="idle")
        dispatch.recover_stale(self.con, self.cfg)
        self.assertEqual(self.con.execute("SELECT status FROM jobs WHERE id=?", (j,)).fetchone()[0], "queued")
        dispatch.dispatch(self.con, self.cfg)
        self.con.execute("UPDATE jobs SET heartbeat_at=?, updated_at=? WHERE id=?", (old, old, j))
        dispatch.recover_stale(self.con, self.cfg)
        self.assertEqual(self.con.execute("SELECT status FROM jobs WHERE id=?", (j,)).fetchone()[0], "failed")

    def test_prompt_carries_intent_and_outbox_rule(self):
        j = db.enqueue(self.con, URL.format(1), "feedback", 0, note="1 new review(s)")
        job = dict(self.con.execute("SELECT * FROM jobs WHERE id=?", (j,)).fetchone())
        pr = dict(self.con.execute("SELECT * FROM prs WHERE url=?", (URL.format(1),)).fetchone())
        text = dispatch.render_prompt(job, pr)
        self.assertNotIn("never wait for an answer", text)
        for must in ("/pr-feedback 1", "ARCHITECTURE_INTENT.md", "every tenant", "outbox add --job",
                     "job done", "pr-pulse ask --job", "never skip", "{{"):
            if must == "{{":
                self.assertNotIn(must, text, "unfilled placeholder")
            else:
                self.assertIn(must, text)
        job["action"] = "merge-check"
        self.assertIn("Do NOT merge", dispatch.render_prompt(job, pr))

    def test_prompt_uses_the_users_own_name(self):
        j = db.enqueue(self.con, URL.format(2), "review", 3)
        job = dict(self.con.execute("SELECT * FROM jobs WHERE id=?", (j,)).fetchone())
        pr = dict(self.con.execute("SELECT * FROM prs WHERE url=?", (URL.format(2),)).fetchone())
        orig = dispatch.core.my_name
        dispatch.core.my_name = lambda cfg: "Ada"
        try:
            text = dispatch.render_prompt(job, pr)
        finally:
            dispatch.core.my_name = orig
        self.assertIn("Decisions are Ada's", text)
        self.assertNotIn("Alex", text)
        self.assertNotIn("{{me}}", text)


class OutboxFlowTest(Base):
    def run_cli(self, argv, stdin=""):
        out = io.StringIO()
        old_in, old_out = sys.stdin, sys.stdout
        sys.stdin, sys.stdout = io.StringIO(stdin), out
        try:
            fn = {"outbox": cli.cmd_outbox, "job": cli.cmd_job}[argv[0]]
            fn(self.con, argv[1:])
        except SystemExit as e:
            out.write(f"[exit {e.code}]")
        finally:
            sys.stdin, sys.stdout = old_in, old_out
        return out.getvalue()

    def test_lines_send_job_back_to_its_session(self):
        self.session("drafter")
        j = db.enqueue(self.con, URL.format(1), "review", 3)
        dispatch.dispatch(self.con, self.cfg)
        self.assertIn("[exit 1]", self.run_cli(["job", "wait-user", str(j)]))  # nothing parked yet
        self.run_cli(["outbox", "add", "--job", str(j), "--kind", "review"], "LGTM, two nits")
        self.run_cli(["outbox", "add", "--job", str(j), "--kind", "reply"], "Thanks!")
        self.run_cli(["job", "wait-user", str(j)])
        self.assertEqual(self.con.execute("SELECT status FROM jobs WHERE id=?", (j,)).fetchone()[0], "waiting_user")
        d1, d2 = [r[0] for r in self.con.execute("SELECT id FROM outbox ORDER BY id")]
        self.assertIn("[exit 1]", self.run_cli(["outbox", "posted", str(d1)]))  # no lines yet
        self.run_cli(["outbox", "lines", str(d1)], "Looks good to me.")
        self.assertEqual(self.con.execute("SELECT status FROM jobs WHERE id=?", (j,)).fetchone()[0], "waiting_user")
        self.run_cli(["outbox", "drop", str(d2)])
        row = self.con.execute("SELECT status, sid, note FROM jobs WHERE id=?", (j,)).fetchone()
        self.assertEqual((row[0], row[1]), ("queued", "drafter"))
        self.assertTrue(row[2].startswith("lines-ready"))
        dispatch.dispatch(self.con, self.cfg)
        self.assertEqual(self.con.execute("SELECT sid FROM jobs WHERE id=?", (j,)).fetchone()[0], "drafter")
        shown = self.run_cli(["outbox", "show", "--job", str(j)])
        self.assertIn("Your lines (post these first):\nLooks good to me.", shown)
        self.assertIn("posted", self.run_cli(["outbox", "posted", str(d1)]))

    def test_fill_it_for_me_is_saved_and_logged_as_claude(self):
        self.session("drafter")
        j = db.enqueue(self.con, URL.format(5), "review", 3)
        dispatch.dispatch(self.con, self.cfg)
        self.run_cli(["outbox", "add", "--job", str(j), "--kind", "review"], "Two nits below.")
        self.run_cli(["job", "wait-user", str(j)])
        d = self.con.execute("SELECT id FROM outbox").fetchone()[0]
        out = self.run_cli(["outbox", "lines", str(d), "--filled"], "Looks good, two small nits below.")
        self.assertIn("lines filled in for you saved", out)
        self.assertEqual(self.con.execute("SELECT lines, status FROM outbox WHERE id=?", (d,)).fetchone()[:],
                         ("Looks good, two small nits below.", "ready"))
        ev = self.con.execute("SELECT detail FROM events WHERE kind='outbox.lines'").fetchone()[0]
        self.assertIn("fill it for me", ev)
        self.assertEqual(self.con.execute("SELECT status FROM jobs WHERE id=?", (j,)).fetchone()[0], "queued")
        # typed lines are logged as the user's
        j2 = db.enqueue(self.con, URL.format(6), "review", 3)
        self.run_cli(["outbox", "add", "--job", str(j2), "--kind", "reply"], "Fixed.")
        d2 = self.con.execute("SELECT MAX(id) FROM outbox").fetchone()[0]
        self.run_cli(["outbox", "lines", str(d2)], "Good catch.")
        last = self.con.execute("SELECT detail FROM events WHERE kind='outbox.lines' ORDER BY id DESC").fetchone()[0]
        self.assertIn('"user"', last)

    def test_merge_check_decision(self):
        self.con.execute("UPDATE prs SET kind='own' WHERE n=2")
        j = db.enqueue(self.con, URL.format(2), "merge-check", 0, head_sha="n" * 40)
        self.run_cli(["outbox", "add", "--job", str(j), "--kind", "decision"], "Only a test rename.")
        d = self.con.execute("SELECT id FROM outbox").fetchone()[0]
        self.assertIn("[exit 2]", self.run_cli(["outbox", "lines", str(d)], "merge"))
        self.run_cli(["outbox", "decide", str(d), "merge"])
        self.assertEqual(self.con.execute("SELECT merge_ok_sha FROM prs WHERE n=2").fetchone()[0], "n" * 40)
        self.assertEqual(self.con.execute("SELECT status FROM jobs WHERE id=?", (j,)).fetchone()[0], "done")

    def test_merge_check_re_review_does_not_merge(self):
        j = db.enqueue(self.con, URL.format(3), "merge-check", 0, head_sha="n" * 40)
        self.run_cli(["outbox", "add", "--job", str(j), "--kind", "decision"], "Changes the parser.")
        d = self.con.execute("SELECT id FROM outbox").fetchone()[0]
        self.run_cli(["outbox", "decide", str(d), "re-review"])
        self.assertIsNone(self.con.execute("SELECT merge_ok_sha FROM prs WHERE n=3").fetchone()[0])
        self.assertEqual(self.con.execute("SELECT status FROM jobs WHERE id=?", (j,)).fetchone()[0], "queued")


class PoolPullTest(Base):
    def test_pulls_at_most_pool_pull_and_rechecks_skips(self):
        for n in range(1, 5):
            self.con.execute("INSERT INTO review_pool(pr_url, channel, ts, shared_at) VALUES(?, 'C', ?, ?)",
                             (URL.format(n), f"{n}.0", n))
        verdicts = {URL.format(1): "draft", URL.format(2): "", URL.format(3): "", URL.format(4): ""}
        calls = []

        def fake(con, me, mapped, url, action, note, prio):
            calls.append(url)
            why = verdicts[url]
            if not why:
                db.enqueue(con, url, action, prio, note)
            return why
        orig = daemon.queue_review
        daemon.queue_review = fake
        try:
            self.cfg["pool_pull"] = 2
            daemon.pool_pull(self.con, self.cfg, "me", {"o/r"})
            st = dict(self.con.execute("SELECT pr_url, status FROM review_pool").fetchall())
            self.assertEqual(st[URL.format(1)], "pool")      # draft: stays, re-checked later
            self.assertEqual(st[URL.format(2)], "pulled")
            self.assertEqual(st[URL.format(3)], "pulled")
            self.assertEqual(st[URL.format(4)], "pool")      # cap of 2 reached
            # the skipped draft is not re-checked within 30 minutes
            calls.clear()
            daemon.pool_pull(self.con, self.cfg, "me", {"o/r"})
            self.assertNotIn(URL.format(1), calls)
            # later it became ready
            self.con.execute("UPDATE review_pool SET last_check=0 WHERE pr_url=?", (URL.format(1),))
            verdicts[URL.format(1)] = ""
            self.con.execute("UPDATE jobs SET status='done'")
            daemon.pool_pull(self.con, self.cfg, "me", {"o/r"})
            st = dict(self.con.execute("SELECT pr_url, status FROM review_pool").fetchall())
            self.assertEqual(st[URL.format(1)], "pulled")
        finally:
            daemon.queue_review = orig

    def test_no_pull_when_pool_full(self):
        self.con.execute("INSERT INTO review_pool(pr_url, channel, ts, shared_at) VALUES(?, 'C', '1.0', 1)",
                         (URL.format(5),))
        for n in (1, 2, 3):
            db.enqueue(self.con, URL.format(n), "review", 3)
        orig = daemon.queue_review
        daemon.queue_review = lambda *a: self.fail("should not pull")
        try:
            daemon.pool_pull(self.con, self.cfg, "me", {"o/r"})
        finally:
            daemon.queue_review = orig


class SlackIngestTest(Base):
    def test_first_run_starts_from_now_then_classifies(self):
        cfg = dict(self.cfg, watch_channels=["C1"], slack_user_id="UME")
        os.environ["PR_PULSE_SLACK_BOT_TOKEN"] = "x"
        db.set_setting(self.con, "slack_bot_user", "UBOT")
        msgs = [{"ts": "10.0", "user": "UA", "text": f"please review {URL.format(6)}"},
                {"ts": "11.0", "user": "UBOT", "text": f"<@UME> {URL.format(7)}"},
                {"ts": "12.0", "user": "UB", "text": f"<@UME> fixed {URL.format(7)}"}]
        orig_hist, orig_q = daemon.slack.history, daemon.queue_review
        daemon.slack.history = lambda ch, oldest: msgs
        queued = []
        daemon.queue_review = lambda con, me, mapped, url, action, note, prio: queued.append((url, action, prio)) or ""
        try:
            daemon.slack_ingest(self.con, cfg, "me", {"o/r"})       # first run: only sets oldest
            self.assertEqual(self.con.execute("SELECT COUNT(*) FROM review_pool").fetchone()[0], 0)
            daemon.slack_ingest(self.con, cfg, "me", {"o/r"})
            pool = dict(self.con.execute("SELECT pr_url, status FROM review_pool").fetchall())
            self.assertEqual(pool[URL.format(6)], "pool")
            self.assertEqual(queued, [(URL.format(7), "re-review", rules.PRIO["re-review"])])
            daemon.slack_ingest(self.con, cfg, "me", {"o/r"})       # same messages: seen, no repeat
            self.assertEqual(len(queued), 1)
        finally:
            daemon.slack.history, daemon.queue_review = orig_hist, orig_q
            del os.environ["PR_PULSE_SLACK_BOT_TOKEN"]


class WaitingForApprovalTest(Base):
    """Side-agent finding: an unattended worker stuck on a permission prompt must be surfaced,
    and must not be re-queued into a second worker."""

    def setUp(self):
        super().setUp()
        self.told = []
        self._orig_notify = dispatch.notify
        dispatch.notify = lambda msg: self.told.append(msg)

    def tearDown(self):
        dispatch.notify = self._orig_notify
        super().tearDown()

    def stuck_job(self):
        self.con.execute("INSERT INTO sessions(sid, name, slug, status, spawned) "
                         "VALUES('w1', 'pr-o-r-1-feedback', 'o/r', 'waiting', 1)")
        j = db.enqueue(self.con, URL.format(1), "feedback", 0)
        db.claim(self.con, j, "w1")
        db.set_job(self.con, j, "delivered")
        return j

    def test_notifies_at_once_then_every_two_hours(self):
        j = self.stuck_job()
        t0 = 1_800_000_000.0
        self.assertEqual(dispatch.watch_waiting(self.con, t0), [j])
        self.assertIn("claude attach w1", self.told[0])   # by id: names can repeat
        self.assertEqual(dispatch.watch_waiting(self.con, t0 + 600), [])
        self.assertEqual(dispatch.watch_waiting(self.con, t0 + 2 * 3600 + 1), [j])

    def test_busy_or_idle_is_not_reported(self):
        j = self.stuck_job()
        self.con.execute("UPDATE sessions SET status='busy' WHERE sid='w1'")
        self.assertEqual(dispatch.watch_waiting(self.con), [])

    def test_busy_but_silent_past_stall_minutes_frees_the_slot_once(self):
        # Live 2026-11-11: three workers stopped after a denied command; `claude agents` kept
        # saying busy (their inbox watchers ran), so the jobs held all three slots for hours.
        told = []
        orig, dispatch.notify = dispatch.notify, told.append
        try:
            self.session("s1", status="busy")
            j = db.enqueue(self.con, URL.format(1), "review", 3)
            db.claim(self.con, j, "s1")
            db.set_job(self.con, j, "delivered")
            old = time.time() - 3 * 3600
            self.con.execute("UPDATE jobs SET heartbeat_at=?, updated_at=? WHERE id=?", (old, old, j))
            dispatch.recover_stale(self.con, self.cfg)
            row = self.con.execute("SELECT status, note, attempts FROM jobs WHERE id=?", (j,)).fetchone()
            self.assertEqual(row["status"], "waiting_user")        # no slot, not requeued, not failed
            self.assertTrue(row["note"].startswith("stalled"))
            self.assertEqual(len(told), 1)
            self.assertIn("switch to session s1", told[0])   # your own session: attach is for workers
            dispatch.recover_stale(self.con, self.cfg)
            self.assertEqual(len(told), 1)                          # told once
            spec = importlib.util.spec_from_file_location("pg_stall", Path(dispatch.__file__).parent / "post-guard.py")
            pg = importlib.util.module_from_spec(spec); spec.loader.exec_module(pg)
            self.assertIsNotNone(pg.decide(self.con, "s1", "gh pr review 1 --approve -b x"))   # still guarded
            # the session comes back: a beat picks the job up again
            env = os.environ.get("CLAUDE_CODE_SESSION_ID")
            os.environ["CLAUDE_CODE_SESSION_ID"] = "s1"
            try:
                import importlib.util as iu
                spec = iu.spec_from_loader("pp_cli_stall", loader=None)
                cli = iu.module_from_spec(spec)
                cli.__file__ = str(Path(dispatch.__file__).parent / "pr-pulse")
                exec(compile(Path(cli.__file__).read_text(), cli.__file__, "exec"), cli.__dict__)
                import contextlib, io
                with contextlib.redirect_stdout(io.StringIO()):
                    cli.cmd_job(self.con, ["beat", str(j)])
            finally:
                if env is None:
                    os.environ.pop("CLAUDE_CODE_SESSION_ID", None)
                else:
                    os.environ["CLAUDE_CODE_SESSION_ID"] = env
            self.assertEqual(self.con.execute("SELECT status FROM jobs WHERE id=?", (j,)).fetchone()[0], "delivered")
        finally:
            dispatch.notify = orig

    def test_beat_does_not_revive_a_job_waiting_for_drafts(self):
        import importlib.util as iu
        spec = iu.spec_from_loader("pp_cli_stall2", loader=None)
        cli = iu.module_from_spec(spec)
        cli.__file__ = str(Path(dispatch.__file__).parent / "pr-pulse")
        exec(compile(Path(cli.__file__).read_text(), cli.__file__, "exec"), cli.__dict__)
        j = db.enqueue(self.con, URL.format(1), "review", 3)
        db.set_job(self.con, j, "waiting_user", "1 draft(s) waiting for the user's lines")
        import contextlib, io
        with self.assertRaises(SystemExit), contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            cli.cmd_job(self.con, ["beat", str(j)])
        self.assertEqual(self.con.execute("SELECT status FROM jobs WHERE id=?", (j,)).fetchone()[0], "waiting_user")

    def test_waiting_job_is_never_requeued(self):
        j = self.stuck_job()
        old = time.time() - 5 * 3600
        self.con.execute("UPDATE jobs SET heartbeat_at=?, updated_at=? WHERE id=?", (old, old, j))
        dispatch.recover_stale(self.con, self.cfg)
        self.assertEqual(self.con.execute("SELECT status FROM jobs WHERE id=?", (j,)).fetchone()[0], "delivered")
        self.con.execute("UPDATE sessions SET status='idle' WHERE sid='w1'")   # it gave up silently
        dispatch.recover_stale(self.con, self.cfg)
        self.assertEqual(self.con.execute("SELECT status FROM jobs WHERE id=?", (j,)).fetchone()[0], "queued")


class WorkerCmdTest(unittest.TestCase):
    def test_prompt_is_last_and_lists_cannot_swallow_it(self):
        cfg = dict(db.DEFAULT_CONFIG)
        cmd = dispatch.worker_cmd(cfg, "pr-o-r-1-review", "THE PROMPT")
        self.assertEqual(cmd[:2], ["claude", "--bg"])
        self.assertEqual(cmd[-1], "THE PROMPT")
        self.assertEqual(cmd[-3:-1], ["-n", "pr-o-r-1-review"])   # a non-list flag right before it
        self.assertIn("--allowedTools", cmd)
        self.assertIn("Bash(git push*--force*)", cmd[cmd.index("--disallowedTools"):])
        self.assertFalse(any("merge" in a for a in cmd[cmd.index("--allowedTools"):cmd.index("--disallowedTools")]))
        s = json.loads(cmd[cmd.index("--settings") + 1])
        hook = s["hooks"]["PreToolUse"][0]
        self.assertEqual(hook["matcher"], "Bash")
        self.assertIn("post-guard.py", hook["hooks"][0]["command"])
        self.assertTrue(Path(hook["hooks"][0]["command"].strip('"')).exists())
        r = dispatch.worker_cmd(cfg, None, "P", resume_sid="abc")
        # resume: no flags, or Claude starts a copy that keeps the old session's options anyway
        self.assertEqual(r, ["claude", "--bg", "--resume", "abc", "P"])
        self.assertEqual(r[-3:], ["--resume", "abc", "P"])

    def test_routine_allowed_dangerous_denied(self):
        allowed, denied = db.DEFAULT_CONFIG["worker_allowed_tools"], db.DEFAULT_CONFIG["worker_denied_tools"]
        for must in ("Bash(git push origin HEAD*)", "Bash(pr-pulse *)", "Edit(./**)"):
            self.assertIn(must, allowed)
        for must in ("Bash(git push*--force*)", "Bash(git reset --hard*)"):
            self.assertIn(must, denied)
        # merging asks (not allowed, not denied): the owner approves it via attach
        self.assertFalse(any("merge" in a for a in allowed))
        self.assertFalse(any("merge" in a for a in denied))


class AgyFindingsTest(Base):
    def test_merge_ok_cleared_by_any_new_push(self):
        import core
        pr = {"url": URL.format(1), "number": 1, "title": "t", "author": {"login": "me"}, "state": "OPEN",
              "isDraft": False, "headRefOid": "B", "reviewDecision": "APPROVED", "reviews": [],
              "comments": [], "statusCheckRollup": []}
        core.upsert_pr(self.con, "o/r", pr, "own")
        self.con.execute("UPDATE prs SET merge_ok_sha='B' WHERE url=?", (URL.format(1),))
        core.upsert_pr(self.con, "o/r", pr, "own")       # same head: OK kept
        self.assertEqual(self.con.execute("SELECT merge_ok_sha FROM prs WHERE n=1").fetchone()[0], "B")
        core.upsert_pr(self.con, "o/r", dict(pr, headRefOid="C"), "own")
        core.upsert_pr(self.con, "o/r", dict(pr, headRefOid="B"), "own")   # back to B: must ask again
        self.assertIsNone(self.con.execute("SELECT merge_ok_sha FROM prs WHERE n=1").fetchone()[0])

    def test_no_re_review_while_a_review_runs(self):
        db.enqueue(self.con, URL.format(1), "review", 3)
        orig = daemon.view_pr
        daemon.view_pr = lambda url: self.fail("must not even look it up")
        try:
            why = daemon.queue_review(self.con, "me", {"o/r"}, URL.format(1), "re-review", "tag", 1)
        finally:
            daemon.view_pr = orig
        self.assertEqual(why, "a review of it is already running")

    def test_lines_ready_never_goes_to_another_session(self):
        self.session("interactive")                       # registered, idle, live
        self.con.execute("INSERT INTO sessions(sid, name, slug, status, registered, spawned) "
                         "VALUES('worker', 'w', 'o/r', 'gone', 0, 1)")
        j = db.enqueue(self.con, URL.format(1), "review", 3)
        self.con.execute("UPDATE jobs SET sid='worker', note='lines-ready: 1 draft(s) to post' WHERE id=?", (j,))
        resumed = []
        orig = dispatch.resume_worker
        dispatch.resume_worker = lambda con, job, sid, cfg, dry=False: resumed.append(sid) or False
        try:
            dispatch.dispatch(self.con, self.cfg)
        finally:
            dispatch.resume_worker = orig
        self.assertEqual(resumed, ["worker"])
        self.assertFalse((dispatch.INBOX / "interactive.jsonl").exists()
                         and str(j) in (dispatch.INBOX / "interactive.jsonl").read_text())

    def test_names_include_the_owner(self):
        self.assertNotEqual(dispatch.worker_name("a/backend", 5, "review"),
                            dispatch.worker_name("b/backend", 5, "review"))


if __name__ == "__main__":
    unittest.main()


class AutoReviewTest(Base):
    """/pr-pulse:auto-review off holds reviews of others' PRs; own-PR work carries on."""

    def setUp(self):
        super().setUp()
        import autoreview
        self.ar = autoreview
        self.cfg = dict(self.cfg, spawn_workers=True)

    def started(self, jid):
        return self.con.execute("SELECT status FROM jobs WHERE id=?", (jid,)).fetchone()["status"] != "queued"

    def test_off_holds_reviews_and_lets_own_pr_work_through(self):
        rv = db.enqueue(self.con, URL.format(1), "review", 2)
        rr = db.enqueue(self.con, URL.format(2), "re-review", 1)
        fb = db.enqueue(self.con, URL.format(3), "feedback", 3)
        mg = db.enqueue(self.con, URL.format(4), "merge", 3)
        self.ar.turn_off(self.con, stopper=lambda sid, name: True)
        self.assertEqual(dispatch.dispatch(self.con, self.cfg), 2)
        self.assertFalse(self.started(rv))
        self.assertFalse(self.started(rr))
        self.assertTrue(self.started(fb))
        self.assertTrue(self.started(mg))

    def test_on_hands_out_reviews(self):
        rv = db.enqueue(self.con, URL.format(1), "review", 2)
        self.ar.turn_off(self.con, stopper=lambda sid, name: True)
        dispatch.dispatch(self.con, self.cfg)
        self.assertFalse(self.started(rv))
        self.ar.turn_on(self.con, pr_state=lambda url: "OPEN")
        self.assertEqual(dispatch.dispatch(self.con, self.cfg), 1)
        self.assertTrue(self.started(rv))

    def test_review_with_your_lines_still_posts_while_off(self):
        rv = db.enqueue(self.con, URL.format(1), "review", 2)
        self.con.execute("UPDATE jobs SET note='lines-ready: post' WHERE id=?", (rv,))
        self.ar.turn_off(self.con, stopper=lambda sid, name: True)
        self.assertEqual(dispatch.dispatch(self.con, self.cfg), 1)
        self.assertTrue(self.started(rv))

    def test_held_review_of_a_merged_pr_is_dropped_on_resume(self):
        gone = db.enqueue(self.con, URL.format(1), "review", 2)
        kept = db.enqueue(self.con, URL.format(2), "review", 2)
        self.ar.turn_off(self.con, stopper=lambda sid, name: True)
        self.ar.turn_on(self.con, pr_state=lambda url: "MERGED" if url == URL.format(1) else "OPEN")
        st = dict(self.con.execute("SELECT id, status FROM jobs").fetchall())
        self.assertEqual((st[gone], st[kept]), ("cancelled", "queued"))

    def test_off_stops_pr_pulse_review_workers_only(self):
        self.con.execute("INSERT INTO sessions(sid, name, slug, status, spawned) VALUES"
                         "('w1','pr-o-r-1-review','o/r','busy',1), ('me','my-session','o/r','busy',0)")
        a = db.enqueue(self.con, URL.format(1), "review", 2)
        b = db.enqueue(self.con, URL.format(2), "review", 2)
        db.claim(self.con, a, "w1")
        db.set_job(self.con, a, "delivered")
        db.claim(self.con, b, "me")
        db.set_job(self.con, b, "delivered")
        stopped = []
        out = self.ar.turn_off(self.con, stopper=lambda sid, name: stopped.append(name) or True)
        self.assertEqual(stopped, ["pr-o-r-1-review"])
        st = dict(self.con.execute("SELECT id, status FROM jobs").fetchall())
        self.assertEqual((st[a], st[b]), ("queued", "delivered"))   # requeued (held) / left alone
        self.assertTrue(any("my-session" in line for line in out))
        dispatch.dispatch(self.con, self.cfg)
        self.assertFalse(self.started(a))                           # held, not restarted

    def test_keep_running_stops_nothing(self):
        self.con.execute("INSERT INTO sessions(sid, name, slug, status, spawned) VALUES"
                         "('w1','pr-o-r-1-review','o/r','busy',1)")
        a = db.enqueue(self.con, URL.format(1), "review", 2)
        db.claim(self.con, a, "w1")
        db.set_job(self.con, a, "delivered")
        stopped = []
        self.ar.turn_off(self.con, stop_workers=False, stopper=lambda sid, name: stopped.append(name) or True)
        self.assertEqual(stopped, [])

    def test_pool_is_not_pulled_while_off_and_is_when_on(self):
        self.con.execute("INSERT INTO review_pool(pr_url, channel, ts, sharer, shared_at, status) "
                         "VALUES(?, 'C', '1.0', 'U', 0, 'pool')", (URL.format(5),))
        orig = daemon.queue_review
        pulled = []
        daemon.queue_review = lambda con, me, mapped, url, action, note, prio: pulled.append(url) or ""
        try:
            self.ar.turn_off(self.con, stopper=lambda sid, name: True)
            daemon.pool_pull(self.con, self.cfg, "me", {"o/r"})
            self.assertEqual(pulled, [])
            self.ar.turn_on(self.con, pr_state=lambda url: "OPEN")
            daemon.pool_pull(self.con, self.cfg, "me", {"o/r"})
            self.assertEqual(pulled, [URL.format(5)])
        finally:
            daemon.queue_review = orig

    def test_off_survives_stop_and_start(self):
        self.ar.turn_off(self.con, stopper=lambda sid, name: True)
        db.set_setting(self.con, "stopped", "1")
        db.set_setting(self.con, "paused", "1")
        db.set_setting(self.con, "stopped", "0")   # what start does to the store
        db.set_setting(self.con, "paused", "0")
        self.assertFalse(self.ar.is_on(self.con))
        self.assertIn("OFF", self.ar.status_line(self.con))


class WorkersTest(Base):
    """pr-pulse's own workers: marked as its own, opened by id, stopped when finished."""

    def setUp(self):
        super().setUp()
        import workers
        self.w = workers
        self.stopped = []
        self.stopper = lambda sid: self.stopped.append(sid) or True

    def worker(self, sid, name, status="idle", cwd="/x/r/.claude/worktrees/pr-pulse-o--r-1", spawned=0):
        self.con.execute("INSERT INTO sessions(sid, name, cwd, kind, status, spawned, seen_at) "
                         "VALUES(?,?,?,'background',?,?,?)", (sid, name, cwd, status, spawned, time.time()))

    def test_workers_are_marked_from_events_or_worktree_and_yours_never(self):
        db.event(self.con, "worker.spawned", {"job": 1, "name": "pr-o-r-1-review", "wt": "/w"})
        self.worker("a", "pr-o-r-1-review", cwd="/elsewhere")
        self.worker("b", "pr-o-r-2-feedback")                      # worktree path only
        self.worker("c", "my-own-bg", cwd="/Users/me/Projects/r")   # yours
        self.con.execute("INSERT INTO sessions(sid, name, cwd, kind, status) VALUES('d','pr-o-r-1-review',"
                         "'/x','interactive','idle')")              # interactive with a worker-like name
        self.assertEqual(self.w.mark_spawned(self.con), 2)
        got = dict(self.con.execute("SELECT sid, spawned FROM sessions").fetchall())
        self.assertEqual(got, {"a": 1, "b": 1, "c": 0, "d": 0})

    def test_job_start_marks_the_worker_at_once(self):
        j = db.enqueue(self.con, URL.format(1), "review", 2)
        db.claim(self.con, j, "name:pr-o-r-1-review")
        os.environ["CLAUDE_CODE_SESSION_ID"] = "real-sid"
        try:
            with contextlib_redirect():
                cli.cmd_job(self.con, ["start", str(j)])
        finally:
            del os.environ["CLAUDE_CODE_SESSION_ID"]
        self.assertEqual(self.con.execute("SELECT spawned FROM sessions WHERE sid='real-sid'").fetchone()[0], 1)

    def test_job_start_in_your_session_does_not_mark_it(self):
        self.session("mine")
        j = db.enqueue(self.con, URL.format(1), "review", 2)
        db.claim(self.con, j, "mine")
        os.environ["CLAUDE_CODE_SESSION_ID"] = "mine"
        try:
            with contextlib_redirect():
                cli.cmd_job(self.con, ["start", str(j)])
        finally:
            del os.environ["CLAUDE_CODE_SESSION_ID"]
        self.assertEqual(self.con.execute("SELECT spawned FROM sessions WHERE sid='mine'").fetchone()[0], 0)

    def test_finished_idle_worker_is_stopped_after_the_quiet_time(self):
        self.worker("done1", "pr-o-r-1-review", spawned=1)
        j = db.enqueue(self.con, URL.format(1), "review", 2)
        db.claim(self.con, j, "done1")
        db.set_job(self.con, j, "done")
        self.assertEqual(self.w.reap_idle(self.con, {"worker_idle_minutes": 10}, stopper=self.stopper), [])
        later = time.time() + 11 * 60
        self.assertEqual(self.w.reap_idle(self.con, {"worker_idle_minutes": 10}, now=later,
                                          stopper=self.stopper), ["pr-o-r-1-review"])
        self.assertEqual(self.stopped, ["done1"])

    def test_busy_waiting_unbound_and_your_sessions_are_never_stopped(self):
        later = time.time() + 3600
        self.worker("busy1", "pr-o-r-1-review", status="busy", spawned=1)
        self.worker("wait1", "pr-o-r-2-review", spawned=1)
        j = db.enqueue(self.con, URL.format(2), "review", 2)
        db.claim(self.con, j, "wait1")
        db.set_job(self.con, j, "waiting_user")
        self.worker("new1", "pr-o-r-3-feedback", spawned=1)        # job still claimed by name
        j3 = db.enqueue(self.con, URL.format(3), "feedback", 2)
        db.claim(self.con, j3, "name:pr-o-r-3-feedback")
        self.worker("mine", "my-bg", spawned=0)
        self.assertEqual(self.w.reap_idle(self.con, {}, now=later, stopper=self.stopper), [])
        self.assertEqual(self.stopped, [])

    def test_a_new_worker_clears_a_jobless_leftover_with_its_name_only(self):
        live = [{"sessionId": "old1", "name": "pr-o-r-1-feedback"}, {"sessionId": "busy2", "name": "pr-o-r-1-feedback"},
                {"sessionId": "x", "name": "other"}]
        j = db.enqueue(self.con, URL.format(1), "feedback", 2)
        db.claim(self.con, j, "busy2")
        stopped, kept = self.w.clear_name(self.con, "pr-o-r-1-feedback", live, stopper=self.stopper)
        self.assertEqual((stopped, kept), (["old1"], ["busy2"]))

    def test_open_session_attaches_by_id_even_when_names_repeat(self):
        import sessionui
        live = [{"sessionId": "2ac567f1-aaaa", "name": "pr-x", "kind": "background"},
                {"sessionId": "daa07302-bbbb", "name": "pr-x", "kind": "background"}]
        orig = (sessionui.core.list_sessions, sessionui._osa)
        ran = []
        sessionui.core.list_sessions = lambda: live
        sessionui._osa = lambda script: ran.append(script)
        try:
            self.assertEqual(sessionui.open_session("daa07302-bbbb", "pr-x"), "opened claude attach daa07302")
            self.assertIn('"claude attach daa07302"', ran[0])
            self.assertEqual(sessionui.open_session("gone", "pr-x"), "session is not running")  # ambiguous name
        finally:
            sessionui.core.list_sessions, sessionui._osa = orig


def contextlib_redirect():
    import contextlib
    return contextlib.redirect_stdout(io.StringIO())


class GuardMergeTest(Base):
    def setUp(self):
        super().setUp()
        self.guard = load("post_guard_m", ROOT / "scripts" / "post-guard.py")
        self.enq = ("gh api graphql -f id=X -f oid=Y -f query='mutation($id: ID!) { enqueuePullRequest("
                    "input: {pullRequestId: $id}) { mergeQueueEntry { position } } }'")

    def job(self, action, sid="w1"):
        j = db.enqueue(self.con, URL.format(1), action, 2)
        db.claim(self.con, j, sid)
        db.set_job(self.con, j, "delivered")
        return j

    def test_a_merge_job_may_enqueue(self):
        self.job("merge")
        self.assertIsNone(self.guard.decide(self.con, "w1", self.enq))

    def test_a_review_job_may_not_enqueue(self):
        self.job("review")
        self.assertIn("blocked", self.guard.decide(self.con, "w1", self.enq))

    def test_a_merge_job_still_may_not_comment(self):
        self.job("merge")
        self.assertIn("blocked", self.guard.decide(self.con, "w1", "gh pr comment 1 --body hi"))
        mixed = self.enq.replace("enqueuePullRequest(", "addComment(input: {}) { x } enqueuePullRequest(")
        self.assertIn("blocked", self.guard.decide(self.con, "w1", mixed))


class AskNamesThePrTest(Base):
    def test_question_without_the_pr_gets_it_and_one_with_it_is_kept(self):
        self.con.execute("UPDATE prs SET title='Merge rows safely' WHERE url=?", (URL.format(1),))
        j = db.enqueue(self.con, URL.format(1), "merge", 2)
        db.claim(self.con, j, "w1")
        db.set_job(self.con, j, "delivered")
        with contextlib_redirect():
            cli.cmd_ask(self.con, ["--job", str(j), "--question", "Merge now, or keep holding?",
                                   "--summary", "x", "--option", "Merge"])
            cli.cmd_ask(self.con, ["--job", str(j), "--question", "Merge #1 now?", "--summary", "x",
                                   "--option", "Merge"])
        qs = [r[0] for r in self.con.execute("SELECT question FROM questions ORDER BY id")]
        self.assertEqual(qs, ["r#1 (Merge rows safely): Merge now, or keep holding?", "Merge #1 now?"])


class EarlierDecisionsTest(Base):
    """A new job on a PR knows the user's earlier answers on it, so a standing hold isn't re-asked."""

    def answered(self, job, q, a, kind="question", age=60):
        qid = self.con.execute("INSERT INTO questions(job_id, sid, question, options, allow_text, created_at, "
                               "status, answer, answered_at, kind) VALUES(?, 's', ?, '[]', 1, ?, 'answered', ?, ?, ?)",
                               (job, q, time.time() - age, a, time.time() - age, kind)).lastrowid
        return qid

    def test_earlier_answers_on_the_pr_reach_the_next_job(self):
        old = db.enqueue(self.con, URL.format(1), "feedback", 2)
        self.answered(old, "Merge #1 now, or keep holding?", "Keep holding: sizing query not run")
        db.set_job(self.con, old, "done")
        new = db.enqueue(self.con, URL.format(1), "feedback", 2)
        pr = dict(self.con.execute("SELECT * FROM prs WHERE url=?", (URL.format(1),)).fetchone())
        job = dict(self.con.execute("SELECT * FROM jobs WHERE id=?", (new,)).fetchone())
        out = dispatch.render_prompt(job, pr, "", self.con)
        self.assertIn("earlier decisions on this PR", out)
        self.assertIn('answered "Keep holding: sizing query not run"', out)
        self.assertNotIn("{{", out)

    def test_nothing_is_added_without_earlier_decisions_and_noise_is_left_out(self):
        other = db.enqueue(self.con, URL.format(2), "feedback", 2)
        self.answered(other, "Other PR?", "yes")                          # another PR
        cur = db.enqueue(self.con, URL.format(1), "review", 2)
        self.answered(cur, "This job-only Q?", "zz-own-answer")                   # this job's own question
        old = db.enqueue(self.con, URL.format(1), "merge", 2)
        self.answered(old, "Post this comment?", "Post", kind="draft")   # a draft confirmation
        self.answered(old, "Too old?", "old", age=20 * 86400)            # older than 14 days
        self.con.execute("INSERT INTO questions(job_id, sid, question, options, allow_text, created_at) "
                         "VALUES(?, 's', 'Unanswered?', '[]', 1, ?)", (old, time.time()))
        pr = dict(self.con.execute("SELECT * FROM prs WHERE url=?", (URL.format(1),)).fetchone())
        job = dict(self.con.execute("SELECT * FROM jobs WHERE id=?", (cur,)).fetchone())
        out = dispatch.render_prompt(job, pr, "", self.con)
        self.assertNotIn("earlier decisions", out)
        for s in ("Other PR?", "zz-own-answer", "This job-only Q", "Post this comment", "Too old", "Unanswered"):
            self.assertNotIn(s, out)
        self.assertNotIn("{{", out)


class StrayClickTest(Base):
    """A carried answer given seconds after the banner is flagged; a withdrawn one is not carried."""

    def q(self, job, answer, shown_ago, answered_ago, via="notification"):
        now = time.time()
        return self.con.execute(
            "INSERT INTO questions(job_id, sid, question, options, allow_text, created_at, status, answer, "
            "answered_at, shown_at, answered_via, kind) VALUES(?, 's', 'Merge #1 now?', '[]', 1, ?, 'answered', "
            "?, ?, ?, ?, 'question')", (job, now - shown_ago, answer, now - answered_ago, now - shown_ago, via)).lastrowid

    def prompt_for_new_job(self):
        new = db.enqueue(self.con, URL.format(1), "feedback", 2)
        pr = dict(self.con.execute("SELECT * FROM prs WHERE url=?", (URL.format(1),)).fetchone())
        return dispatch.render_prompt(dict(self.con.execute("SELECT * FROM jobs WHERE id=?", (new,)).fetchone()),
                                      pr, "", self.con)

    def test_quick_notification_answer_is_flagged(self):
        old = db.enqueue(self.con, URL.format(1), "merge", 2)
        self.q(old, "Merge", shown_ago=100, answered_ago=96)          # 4 s after it showed
        db.set_job(self.con, old, "done")
        out = self.prompt_for_new_job()
        self.assertIn("4s after the notification showed", out)
        self.assertIn("confirm it with ", out)   # the name comes from config or git: none on CI

    def test_considered_or_in_session_answers_are_not_flagged(self):
        old = db.enqueue(self.con, URL.format(1), "merge", 2)
        self.q(old, "Keep holding", shown_ago=200, answered_ago=100)  # 100 s: read and decided
        self.q(old, "Merge", shown_ago=100, answered_ago=99, via="session")
        db.set_job(self.con, old, "done")
        out = self.prompt_for_new_job()
        self.assertIn('answered "Keep holding"', out)
        self.assertNotIn("stray click", out)

    def test_forget_stops_carrying_an_answer(self):
        old = db.enqueue(self.con, URL.format(1), "merge", 2)
        qid = self.q(old, "Merge", shown_ago=100, answered_ago=96)
        db.set_job(self.con, old, "done")
        with contextlib_redirect():
            cli.cmd_forget(self.con, [str(qid)])
        self.assertNotIn("earlier decisions", self.prompt_for_new_job())
        out = io.StringIO()
        import contextlib
        with contextlib.redirect_stdout(out):
            cli.cmd_forget(self.con, ["99999"])
        self.assertIn("no answer to withdraw", out.getvalue())


def contextlib_redirect():
    import contextlib
    return contextlib.redirect_stdout(io.StringIO())
