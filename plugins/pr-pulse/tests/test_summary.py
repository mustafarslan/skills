"""Notification summaries: scope by impact, severity kept, three short lines, both directions."""
import io
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("PR_PULSE_HOME", tempfile.mkdtemp(prefix="pp-sum-"))
sys.path.insert(0, str(ROOT / "scripts"))
import db         # noqa: E402
import rules      # noqa: E402


class ScopeTest(unittest.TestCase):
    def test_infer(self):
        cases = {
            "src/auth/refresh.ts:88": "runtime", "app/models/user.py": "runtime",
            "tests/auth/test_refresh.py:40": "tests", "src/auth/refresh.test.ts": "tests",
            "pkg/auth/refresh_test.go": "tests", "src/__tests__/a.js": "tests",
            "docs/auth.md": "docs", "README.md": "docs",
            "db/migrations/0042_tokens.sql": "migration", "alembic/versions/a1.py": "migration",
            "prisma/migrations/2026/migration.sql": "migration",
            "infra/main.tf": "infra", "k8s/deploy.yaml": "infra", "Dockerfile": "infra",
            ".github/workflows/deploy-prod.yml": "infra", ".github/workflows/lint.yml": "ci",
            ".eslintrc.json": "tooling", "tsconfig.json": "tooling",
        }
        for path, scope in cases.items():
            self.assertEqual(rules.infer_scope(path), scope, path)

    def test_session_cannot_move_migration_or_infra_out_of_production(self):
        self.assertEqual(rules.effective_scope("docs", "db/migrations/1.sql"), "migration")
        self.assertEqual(rules.effective_scope("tests", "infra/main.tf"), "infra")
        # it may raise risk (a fixture that defines a prod contract) ...
        self.assertEqual(rules.effective_scope("runtime", "tests/fixtures/contract.json"), "runtime")
        self.assertEqual(rules.effective_scope("migration", "src/db/setup.py"), "migration")
        # ... but never lower a production-looking path (side-agent finding)
        self.assertEqual(rules.effective_scope("tests", "src/testing/helpers.ts"), "runtime")
        self.assertEqual(rules.effective_scope("docs", "src/auth/refresh.ts"), "runtime")
        self.assertEqual(rules.effective_scope("bogus", "docs/a.md"), "docs")
        self.assertEqual(rules.effective_scope("tests", ""), "tests")
        self.assertEqual(rules.effective_scope("", ""), "runtime")


class MessageTest(unittest.TestCase):
    def fs(self, *items):
        return rules.normalize_findings([dict(zip(("severity", "path", "what"), i)) for i in items])

    def test_test_only_critical_is_labelled_not_downgraded(self):
        fs = self.fs(("critical", "tests/a_test.py:3", "Asserts the wrong token, so the race is never caught"),
                     ("nit", "src/a.py:1", "Unused import"))
        msg = rules.notification_message("Approve, request changes or comment?", "s", fs).splitlines()
        self.assertEqual(msg[0], "1 critical (test) · 1 nit")
        self.assertTrue(msg[1].startswith("Asserts the wrong token"))
        self.assertEqual(msg[2], "Approve, request changes or comment?")

    def test_production_finding_leads_even_at_equal_severity(self):
        fs = self.fs(("critical", "tests/a_test.py", "test thing"), ("critical", "src/a.py:9", "prod thing"))
        msg = rules.notification_message("Q?", "s", fs).splitlines()
        self.assertEqual(msg[0], "2 critical (1 test)")
        self.assertTrue(msg[1].startswith("prod thing"))

    def test_aliases_and_plurals(self):
        fs = self.fs(("blocker", "src/a.py", "x"), ("major", "src/b.py", "y"), ("major", "docs/c.md", "z"),
                     ("style", "src/d.py", "w"), ("low", "src/e.py", "v"))
        self.assertEqual(rules.counts_line(fs), "1 critical · 2 improvements (1 docs) · 2 nits")

    def test_no_findings_uses_summary(self):
        msg = rules.notification_message("Implement, defer or reply?",
                                         "CodeRabbit asks to rename a helper; style only", [])
        self.assertEqual(msg.splitlines(), ["CodeRabbit asks to rename a helper; style only",
                                            "Implement, defer or reply?"])

    def test_details_lists_every_finding_worst_production_first(self):
        fs = self.fs(("nit", "src/a.py:1", "Unused import"),
                     ("critical", "tests/a_test.py:3", "Asserts the wrong token"),
                     ("improvement", "docs/a.md", "Old flow described"))
        lines = rules.details_text("Auth refactor", fs).splitlines()
        self.assertEqual(lines[0], "Auth refactor")
        self.assertEqual(lines[1], "critical · test tests/a_test.py:3 — Asserts the wrong token")
        self.assertEqual(lines[2], "improvement · docs docs/a.md — Old flow described")
        self.assertEqual(lines[3], "nit · runtime src/a.py:1 — Unused import")
        many = self.fs(*[("nit", f"src/{i}.py", "x") for i in range(11)])
        self.assertEqual(rules.details_text("", many).splitlines()[-1], "+3 more in the session")

    def test_long_top_line_is_trimmed(self):
        fs = self.fs(("critical", "src/a.py", "x" * 300))
        self.assertLessEqual(len(rules.notification_message("Q?", "", fs).splitlines()[1]), 110)


def load_cli():
    spec = importlib.util.spec_from_loader("pp_cli_sum", loader=None)
    mod = importlib.util.module_from_spec(spec)
    mod.__file__ = str(ROOT / "scripts" / "pr-pulse")
    exec(compile((ROOT / "scripts" / "pr-pulse").read_text(), mod.__file__, "exec"), mod.__dict__)
    return mod


class AskTest(unittest.TestCase):
    def setUp(self):
        self.cli = load_cli()
        self.con = db.connect(Path(tempfile.mkdtemp()) / "pulse.db")
        self.job = db.enqueue(self.con, "https://github.com/o/r/pull/1", "review", 3)
        db.claim(self.con, self.job, "s1")
        db.set_job(self.con, self.job, "delivered")

    def ask(self, args, stdin=""):
        out, old_in, old_out = io.StringIO(), sys.stdin, sys.stdout
        sys.stdin, sys.stdout, sys.stderr = io.StringIO(stdin), out, out
        code = 0
        try:
            self.cli.cmd_ask(self.con, args)
        except SystemExit as e:
            code = e.code
        finally:
            sys.stdin, sys.stdout, sys.stderr = old_in, old_out, sys.__stderr__
        return code, out.getvalue()

    def test_question_without_context_is_refused(self):
        code, out = self.ask(["--job", str(self.job), "--question", "Approve?", "--option", "Yes"])
        self.assertEqual(code, 2)
        self.assertIn("needs context", out)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM questions").fetchone()[0], 0)

    def test_json_payload_with_pipes_and_findings(self):
        payload = {"question": "Approve, request changes or comment?", "summary": "a | b: c",
                   "options": ["Approve", "Request changes", "Comment"],
                   "findings": [{"severity": "critical", "path": "db/migrations/1.sql",
                                 "what": "drops col | breaks v1", "scope": "docs"}]}
        code, out = self.ask(["--job", str(self.job), "--json"], json.dumps(payload))
        self.assertEqual(code, 0, out)
        q = self.con.execute("SELECT * FROM questions").fetchone()
        self.assertEqual(q["summary"], "a | b: c")
        fs = json.loads(q["findings"])
        self.assertEqual((fs[0]["scope"], fs[0]["what"]), ("migration", "drops col | breaks v1"))

    def test_summary_flag_form(self):
        code, _ = self.ask(["--job", str(self.job), "--question", "Implement or defer?",
                            "--summary", "CodeRabbit: rename helper", "--option", "Implement",
                            "--option", "Defer"])
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
