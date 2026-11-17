"""Which /pr-review, /pr-feedback, /pr-merge a job uses: the user's own, else the repo's; a job with
neither is skipped before any session starts. Both directions."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("PR_PULSE_HOME", tempfile.mkdtemp(prefix="pp-skills-"))
os.environ["PR_PULSE_NO_NOTIFY"] = "1"
sys.path.insert(0, str(ROOT / "scripts"))
import core      # noqa: E402
import db        # noqa: E402
import dispatch  # noqa: E402


def skill(base, name):
    d = Path(base) / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text("---\nname: x\ndescription: x\n---\n")


class SkillSourceTest(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        self.repo = Path(tempfile.mkdtemp())
        self._home = os.environ.get("HOME")
        os.environ["HOME"] = str(self.home)

    def tearDown(self):
        os.environ["HOME"] = self._home

    def test_missing_everywhere(self):
        self.assertIsNone(core.skill_source("pr-review", str(self.repo)))

    def test_repo_version_used_when_no_personal_one(self):
        skill(self.repo / ".claude" / "skills", "pr-review")
        self.assertEqual(core.skill_source("pr-review", str(self.repo)), "repo")
        self.assertIsNone(core.skill_source("pr-review", None))   # other repos don't have it

    def test_personal_version_wins(self):
        skill(self.repo / ".claude" / "skills", "merge")
        skill(self.home / ".claude" / "skills", "merge")
        self.assertEqual(core.skill_source("merge", str(self.repo)), "personal")

    def test_dispatch_skips_a_job_with_no_skill_and_runs_one_with_the_repo_skill(self):
        con = db.connect(Path(tempfile.mkdtemp()) / "pulse.db")
        con.execute("INSERT INTO repos(path, slug, added_at) VALUES(?, 'o/r', 0)", (str(self.repo),))
        for n in (1, 2):
            con.execute("INSERT INTO prs(url, slug, n, kind, state) VALUES(?, 'o/r', ?, 'review', 'OPEN')",
                        (f"https://github.com/o/r/pull/{n}", n))
        no = db.enqueue(con, "https://github.com/o/r/pull/1", "review", 3)
        cfg = dict(db.DEFAULT_CONFIG, spawn_workers=True)
        spawned = []
        orig = dispatch.spawn_worker
        dispatch.spawn_worker = lambda c, job, cfg, dry=False: spawned.append(job["id"]) or (
            db.claim(c, job["id"], "w") and db.set_job(c, job["id"], "delivered"))
        try:
            dispatch.dispatch(con, cfg)
            self.assertEqual(con.execute("SELECT status FROM jobs WHERE id=?", (no,)).fetchone()[0], "failed")
            self.assertEqual(spawned, [])
            skill(self.repo / ".claude" / "skills", "pr-review")
            yes = db.enqueue(con, "https://github.com/o/r/pull/2", "review", 3)
            dispatch.dispatch(con, cfg)
            self.assertEqual(spawned, [yes])
        finally:
            dispatch.spawn_worker = orig


if __name__ == "__main__":
    unittest.main()
