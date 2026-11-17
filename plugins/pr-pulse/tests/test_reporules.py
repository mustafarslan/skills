"""Per-repo PR rules: validated before use, applied to one repo only, and every gate proven both ways."""
import contextlib
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
os.environ.setdefault("PR_PULSE_HOME", tempfile.mkdtemp(prefix="pp-rules-"))
os.environ["PR_PULSE_NO_NOTIFY"] = "1"
sys.path.insert(0, str(ROOT / "scripts"))
import db         # noqa: E402
import dispatch   # noqa: E402
import reporules  # noqa: E402


def load(name, path):
    spec = importlib.util.spec_from_loader(name, loader=None)
    mod = importlib.util.module_from_spec(spec)
    mod.__file__ = str(path)
    exec(compile(Path(path).read_text(), str(path), "exec"), mod.__dict__)
    return mod


daemon = load("pr_pulsed_rules", ROOT / "scripts" / "pr-pulsed.py")
cli = load("pr_pulse_cli_rules", ROOT / "scripts" / "pr-pulse")

GOOD = {"Acme/App": {"settings": {"auto_review": "off", "merge": "ask", "feedback_rounds": 1,
                                  "review_bots": ["CodeRabbitAI"]},
                     "rules": ["Run the bank-rule tests before approving."]}}


class ValidateTest(unittest.TestCase):
    def test_a_good_entry_is_cleaned(self):
        clean, errors = reporules.validate(GOOD)
        self.assertEqual(errors, [])
        e = clean["acme/app"]
        self.assertEqual(e["settings"], {"auto_review": "off", "merge": "ask", "feedback_rounds": 1,
                                         "review_bots": ["coderabbitai"]})
        self.assertEqual(e["rules"], ["Run the bank-rule tests before approving."])

    def test_each_bad_entry_is_refused_with_a_reason(self):
        bad = {
            "noslash": {"rules": ["x"]},
            "a/b": {"settings": {"merge": "sometimes"}},
            "c/d": {"settings": {"feedback_rounds": 11}},
            "e/f": {"settings": {"feedback_rounds": True}},
            "g/h": {"settings": {"colour": "red"}},
            "i/j": {"rules": "not a list"},
            "k/l": {"rules": [""]},
            "m/n": {"other": 1},
            "o/p": {"rules": ["x" * 301]},
        }
        clean, errors = reporules.validate(bad)
        self.assertEqual(clean, {})
        self.assertEqual(len(errors), len(bad))
        self.assertTrue(all("uses the global settings" in e for e in errors))

    def test_two_names_differing_only_in_case_are_refused(self):
        clean, errors = reporules.validate({"A/B": {"rules": ["x"]}, "a/b": {"rules": ["y"]}})
        self.assertEqual(len(clean), 1)
        self.assertIn("listed twice", errors[0])

    def test_for_repo_applies_to_that_repo_only(self):
        cfg = dict(db.DEFAULT_CONFIG, repo_rules=GOOD)
        mine = reporules.for_repo(cfg, "acme/APP")
        other = reporules.for_repo(cfg, "acme/other")
        self.assertEqual((mine["auto_review"], mine["merge"], mine["feedback_rounds"]), ("off", "ask", 1))
        self.assertEqual(mine["repo_rules_text"], ["Run the bank-rule tests before approving."])
        self.assertEqual((other["auto_review"], other["merge"], other["feedback_rounds"]),
                         ("on", "auto", db.DEFAULT_CONFIG["feedback_rounds"]))
        self.assertEqual(other["repo_rules_text"], [])

    def test_a_bad_entry_never_half_applies(self):
        cfg = dict(db.DEFAULT_CONFIG, repo_rules={"acme/app": {"settings": {"merge": "never",
                                                                             "auto_review": "maybe"}}})
        self.assertEqual(reporules.for_repo(cfg, "acme/app")["merge"], "auto")


class Base(unittest.TestCase):
    URL = "https://github.com/acme/app/pull/{}"

    def setUp(self):
        self.con = db.connect(Path(tempfile.mkdtemp()) / "pulse.db")
        self.con.execute("INSERT INTO repos(path, slug, added_at) VALUES('/x/app', 'acme/app', 0)")
        for n in (1, 2):
            self.con.execute("INSERT INTO prs(url, slug, n, kind, state, head_sha, title) VALUES(?, 'acme/app', ?, "
                             "'review', 'OPEN', 'h', 'T')", (self.URL.format(n), n))
        self.con.execute("INSERT INTO prs(url, slug, n, kind, state, head_sha) VALUES("
                         "'https://github.com/acme/other/pull/3', 'acme/other', 3, 'review', 'OPEN', 'h')")


class HoldTest(Base):
    def job(self, url, action="review"):
        j = db.enqueue(self.con, url, action, 2)
        return dict(self.con.execute("SELECT j.*, p.slug FROM jobs j LEFT JOIN prs p ON p.url=j.pr_url "
                                     "WHERE j.id=?", (j,)).fetchone())

    def test_auto_review_off_holds_reviews_in_that_repo_only(self):
        import autoreview
        cfg = dict(db.DEFAULT_CONFIG, repo_rules=GOOD)
        j1 = self.job(self.URL.format(1))
        self.assertTrue(autoreview.held(self.con, j1, cfg))
        self.assertFalse(autoreview.held(self.con, j1, dict(db.DEFAULT_CONFIG)))    # no rule: not held
        self.assertFalse(autoreview.held(self.con, self.job("https://github.com/acme/other/pull/3"), cfg))
        self.assertFalse(autoreview.held(self.con, self.job(self.URL.format(2), "feedback"), cfg))


class PoolTest(Base):
    def test_pool_skips_a_repo_with_auto_review_off_and_pulls_others(self):
        for i, url in enumerate((self.URL.format(1), "https://github.com/acme/other/pull/3")):
            self.con.execute("INSERT INTO review_pool(pr_url, channel, ts, sharer, shared_at, status) "
                             "VALUES(?, 'C', ?, 'U', ?, 'pool')", (url, f"{i}.0", i))
        pulled = []
        orig = daemon.queue_review
        daemon.queue_review = lambda con, me, mapped, url, action, note, prio: pulled.append(url) or ""
        try:
            daemon.pool_pull(self.con, dict(db.DEFAULT_CONFIG, pool_pull=2, repo_rules=GOOD), "me",
                             {"acme/app", "acme/other"})
        finally:
            daemon.queue_review = orig
        self.assertEqual(pulled, ["https://github.com/acme/other/pull/3"])


class MergeSettingTest(Base):
    def run_own(self, merge):
        cfg = dict(db.DEFAULT_CONFIG, repo_rules={"acme/app": {"settings": {"merge": merge}}})
        pr = {"url": self.URL.format(9), "number": 9, "state": "OPEN", "isDraft": False, "title": "T",
              "author": {"login": "me"}, "headRefOid": "h" * 40, "reviewDecision": "APPROVED",
              "reviews": [{"author": {"login": "alice"}, "state": "APPROVED", "commit": {"oid": "h" * 40},
                           "submittedAt": "2026-11-09T10:00:00Z"}],
              "comments": [], "statusCheckRollup": [{"conclusion": "SUCCESS"}]}
        orig = daemon.core.own_open_prs
        daemon.core.own_open_prs = lambda slug: [pr] if slug == "acme/app" else []
        try:
            daemon.own_prs(self.con, cfg, "me")   # first sight: remembered, no action
            daemon.own_prs(self.con, cfg, "me")
        finally:
            daemon.core.own_open_prs = orig
        return self.con.execute("SELECT action, note FROM jobs WHERE pr_url=?", (self.URL.format(9),)).fetchall()

    def test_auto_merges_as_before(self):
        rows = self.run_own("auto")
        self.assertEqual([r["action"] for r in rows], ["merge"])
        self.assertNotIn("merge=ask", rows[0]["note"])

    def test_ask_queues_a_merge_that_asks_first(self):
        rows = self.run_own("ask")
        self.assertEqual([r["action"] for r in rows], ["merge"])
        self.assertIn("merge=ask", rows[0]["note"])
        job = dict(self.con.execute("SELECT * FROM jobs WHERE pr_url=?", (self.URL.format(9),)).fetchone())
        pr = dict(self.con.execute("SELECT * FROM prs WHERE url=?", (self.URL.format(9),)).fetchone())
        out = dispatch.render_prompt(job, pr, "", self.con)
        self.assertIn("before merging, ask", out)
        self.assertNotIn("{{", out)
        self.assertNotIn("{me}", out)

    def test_never_starts_no_merge(self):
        self.assertEqual(self.run_own("never"), [])


class PromptRulesTest(Base):
    def test_the_repos_rules_reach_its_jobs_only(self):
        cfg_path = Path(tempfile.mkdtemp()) / "config.json"
        cfg_path.write_text(json.dumps({"repo_rules": GOOD}))
        orig = db.CONFIG_PATH
        db.CONFIG_PATH = cfg_path
        try:
            j = db.enqueue(self.con, self.URL.format(1), "review", 2)
            out = dispatch.render_prompt(dict(self.con.execute("SELECT * FROM jobs WHERE id=?", (j,)).fetchone()),
                                         dict(self.con.execute("SELECT * FROM prs WHERE url=?",
                                                               (self.URL.format(1),)).fetchone()), "", self.con)
            self.assertIn("rules for acme/app", out)
            self.assertIn("- Run the bank-rule tests before approving.", out)
            j3 = db.enqueue(self.con, "https://github.com/acme/other/pull/3", "review", 2)
            out3 = dispatch.render_prompt(dict(self.con.execute("SELECT * FROM jobs WHERE id=?", (j3,)).fetchone()),
                                          dict(self.con.execute("SELECT * FROM prs WHERE n=3").fetchone()), "", self.con)
            self.assertNotIn("bank-rule", out3)
            self.assertNotIn("{{", out3)
        finally:
            db.CONFIG_PATH = orig


class CliTest(Base):
    def setUp(self):
        super().setUp()
        self.cfg_path = Path(tempfile.mkdtemp()) / "config.json"
        self.cfg_path.write_text(json.dumps({"my_name": "Ada"}))
        self.orig = db.CONFIG_PATH
        db.CONFIG_PATH = self.cfg_path

    def tearDown(self):
        db.CONFIG_PATH = self.orig

    def rules(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cli.cmd_rules(self.con, list(args))
        return out.getvalue()

    def test_set_add_remove_and_clear(self):
        self.rules("set", "acme/app", "merge", "ask")
        self.rules("add", "acme/app", "Never", "merge", "on", "Fridays.")
        out = self.rules("acme/app")
        self.assertIn("merge            ask", out)
        self.assertIn("1. Never merge on Fridays.", out)
        saved = json.loads(self.cfg_path.read_text())
        self.assertEqual(saved["my_name"], "Ada")                      # the rest of the config is kept
        self.assertEqual(saved["repo_rules"]["acme/app"]["rules"], ["Never merge on Fridays."])
        self.rules("rm", "acme/app", "1")
        self.rules("unset", "acme/app", "merge")
        self.assertNotIn("repo_rules", json.loads(self.cfg_path.read_text()))   # empty entries removed

    def test_a_bad_value_is_refused_and_nothing_is_saved(self):
        with self.assertRaises(SystemExit):
            with contextlib.redirect_stderr(io.StringIO()):
                self.rules("set", "acme/app", "merge", "sometimes")
        self.assertNotIn("repo_rules", json.loads(self.cfg_path.read_text()))


class ProblemsTest(unittest.TestCase):
    def test_a_bad_entry_is_notified_once(self):
        con = db.connect(Path(tempfile.mkdtemp()) / "pulse.db")
        told = []
        orig = daemon.dispatch.notify
        daemon.dispatch.notify = told.append
        try:
            cfg = {"repo_rules": {"a/b": {"settings": {"merge": "sometimes"}}}}
            daemon.repo_rules_problems(con, cfg)
            daemon.repo_rules_problems(con, cfg)
        finally:
            daemon.dispatch.notify = orig
        self.assertEqual(len(told), 1)
        self.assertIn("/pr-pulse:rules", told[0])


if __name__ == "__main__":
    unittest.main()
