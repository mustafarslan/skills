"""The notification banner: everything goes through its Answer menu (macOS doesn't pass a click on
the banner itself on to alerter), and a draft's summary keeps code spans whole."""
import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("PR_PULSE_HOME", tempfile.mkdtemp(prefix="pp-asker-"))
os.environ["PR_PULSE_NO_NOTIFY"] = "1"
sys.path.insert(0, str(ROOT / "scripts"))
import outbox     # noqa: E402
import questions  # noqa: E402

spec = importlib.util.spec_from_file_location("asker", ROOT / "scripts" / "pr-pulse-asker.py")
asker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(asker)


class FakeAlerter:
    """Replays a script of (activationType, activationValue) and records each banner shown."""

    def __init__(self, *replies):
        self.replies, self.shown = list(replies), []

    def __call__(self, base, extra):
        self.shown.append(base + extra)
        return self.replies.pop(0) if self.replies else ("timeout", "")


class MenuTest(unittest.TestCase):
    def show(self, *replies, options=("Fill it for me", "Drop it"), allow=True):
        fake = FakeAlerter(*replies)
        orig, asker._alert = asker._alert, fake
        try:
            ans = asker.via_alerter("pr-pulse", "o/r#1 · feedback", "Your top lines?", list(options),
                                    allow, "every finding", "Type my own lines…")
        finally:
            asker._alert = orig
        return ans, fake.shown

    def menu(self, banner):
        return banner[banner.index("--actions") + 1].split(",")

    def test_menu_has_details_and_open_session(self):
        _, shown = self.show(("actionClicked", "Fill it for me"))
        self.assertEqual(self.menu(shown[0]), [questions.DETAILS_LABEL, "Fill it for me", "Drop it",
                                               "Type my own lines…", questions.OPEN_LABEL])

    def test_a_stray_first_item_never_answers(self):
        # a keystroke from another window picks index 0 (seen live): that must be Details…
        ans, shown = self.show(("actionClicked", questions.DETAILS_LABEL), ("timeout", ""))
        self.assertEqual(self.menu(shown[0])[0], questions.DETAILS_LABEL)
        self.assertIsNone(ans)                                    # still waiting for a real answer

    def test_option_is_the_answer(self):
        self.assertEqual(self.show(("actionClicked", "Drop it"))[0], "Drop it")

    def test_open_session_from_the_menu(self):
        ans, shown = self.show(("actionClicked", questions.OPEN_LABEL))
        self.assertIs(ans, asker.OPEN)
        self.assertEqual(len(shown), 1)

    def test_details_then_back_then_answer(self):
        ans, shown = self.show(("actionClicked", questions.DETAILS_LABEL), ("closed", ""),
                               ("actionClicked", "Fill it for me"))
        self.assertEqual(ans, "Fill it for me")
        self.assertIn("every finding", shown[1])
        self.assertIn("Back", shown[1])

    def test_details_never_answers(self):
        ans, _ = self.show(("actionClicked", questions.DETAILS_LABEL), ("timeout", ""))
        self.assertIsNone(ans)

    def test_later_closed_or_timeout_leaves_it_pending(self):
        for reply in (("closed", ""), ("timeout", ""), (None, "")):
            self.assertIsNone(self.show(reply)[0])

    def test_typed_lines(self):
        ans, _ = self.show(("actionClicked", "Type my own lines…"), ("replied", "Thanks, fixed"))
        self.assertEqual(ans, "Thanks, fixed")

    def test_comma_option_maps_back(self):
        ans, _ = self.show(("actionClicked", "Fix; then merge"), options=("Fix, then merge", "Defer"))
        self.assertEqual(ans, "Fix, then merge")

    def test_short_wait(self):
        self.assertLessEqual(asker.TIMEOUT, 300)


class PlainTest(unittest.TestCase):
    def test_code_span_kept_whole(self):
        self.assertEqual(outbox.plain("Fixed in 9f41c80: the 15 `*_reviewer_validated_count` metric names"),
                         "Fixed in 9f41c80: the 15 *_reviewer_validated_count metric names")

    def test_snake_case_outside_code_kept(self):
        self.assertEqual(outbox.plain("renamed reviewer_validated_count"), "renamed reviewer_validated_count")

    def test_markdown_marks_removed(self):
        self.assertEqual(outbox.plain("## **Approved**, _nice_ work"), "Approved, nice work")
        self.assertEqual(outbox.plain("> quoted line"), "quoted line")

    def test_summary_uses_plain(self):
        summary, _, _ = outbox.summarize("Fixed: `a_b_c` now reads **plain**\n\nmore")
        self.assertEqual(summary, "Fixed: a_b_c now reads plain")


if __name__ == "__main__":
    unittest.main()


class AlerterOptInTest(unittest.TestCase):
    """Banners by default when alerter exists; dialogs when use_alerter is false or alerter is missing."""

    def run_with(self, cfg, have):
        import core
        import db as _db
        orig = (_db.load_config, core.shutil_which if hasattr(core, "shutil_which") else None)
        _db.load_config = lambda path=None: cfg
        import shutil
        real = shutil.which
        shutil.which = lambda name: ("/opt/homebrew/bin/alerter" if have else None) if name == "alerter" else real(name)
        try:
            return core.use_alerter()
        finally:
            _db.load_config = orig[0]
            shutil.which = real

    def test_default_is_banners_when_alerter_is_installed(self):
        import db
        self.assertTrue(self.run_with(dict(db.DEFAULT_CONFIG), True))
        self.assertFalse(self.run_with(dict(db.DEFAULT_CONFIG), False))   # no alerter: dialogs

    def test_use_alerter_false_means_dialogs(self):
        self.assertFalse(self.run_with({"use_alerter": False}, True))
