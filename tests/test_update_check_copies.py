"""Every plugin carries its own copy of the update-notice script (plugins install independently): the copies, the
launcher and the test file must stay byte-for-byte identical, and every plugin must run the hook."""
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGINS = sorted(p.parent.parent for p in ROOT.glob("plugins/*/.claude-plugin/plugin.json"))
SHARED = ["scripts/update_check.py", "scripts/update-check", "tests/test_update_check.py"]


class CopiesTest(unittest.TestCase):
    def test_plugins_found(self):
        self.assertGreaterEqual(len(PLUGINS), 3)

    def test_copies_are_identical(self):
        for rel in SHARED:
            first = (PLUGINS[0] / rel).read_bytes().replace(b"\r\n", b"\n")
            for plugin in PLUGINS[1:]:
                other = (plugin / rel).read_bytes().replace(b"\r\n", b"\n")
                self.assertEqual(first, other, "%s differs between %s and %s" % (rel, PLUGINS[0].name, plugin.name))

    def test_every_plugin_runs_the_hook_at_session_start(self):
        for plugin in PLUGINS:
            hooks = json.loads((plugin / "hooks" / "hooks.json").read_text(encoding="utf-8"))
            commands = [h["command"] for entry in hooks["hooks"]["SessionStart"] for h in entry["hooks"]]
            self.assertTrue(any(c.endswith("/scripts/update-check") for c in commands), plugin.name)


if __name__ == "__main__":
    unittest.main()
