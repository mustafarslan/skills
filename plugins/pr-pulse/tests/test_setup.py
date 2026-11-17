"""Setup tests: env file, secret handling, manifest link, config, doctor. No Slack, no clipboard."""
import importlib.util
import contextlib
import io
import json
import os
import shutil
import stat
import sys
import tempfile
import unittest
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TMP = Path(tempfile.mkdtemp(prefix="pp-setup-"))
os.environ.setdefault("PR_PULSE_HOME", str(TMP / "home"))
os.environ["PR_PULSE_ENV_FILE"] = str(TMP / "cfg" / "env")
os.environ["PR_PULSE_CONFIG"] = str(TMP / "cfg" / "config.json")
sys.path.insert(0, str(ROOT / "scripts"))
import db       # noqa: E402
import envfile  # noqa: E402

envfile.ENV = Path(os.environ["PR_PULSE_ENV_FILE"])
db.CONFIG_PATH = Path(os.environ["PR_PULSE_CONFIG"])


def load_cli():
    spec = importlib.util.spec_from_loader("pp_cli_setup", loader=None)
    mod = importlib.util.module_from_spec(spec)
    mod.__file__ = str(ROOT / "scripts" / "pr-pulse")
    exec(compile((ROOT / "scripts" / "pr-pulse").read_text(), mod.__file__, "exec"), mod.__dict__)
    return mod


cli = load_cli()
TOKEN = "xoxb-" + "1234567890-abcdefghijklmnopqrstu"   # split: a fake that secret scanners skip


def run(fn, con, args, clipboard=None):
    out = io.StringIO()
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = out, out
    orig_run, orig_sub = cli.core.run, cli.subprocess.run
    cli.core.run = lambda a, **k: clipboard if a == ["pbpaste"] else orig_run(a, **k)
    cli.subprocess.run = lambda *a, **k: None          # pbcopy (clear clipboard)
    orig_ident, orig_restart = cli.slack.identity, cli.restart_daemon_if_running
    cli.slack.identity = lambda: {"team": "Acme", "bot": "pr-pulse", "bot_user": "UB", "bot_id": "B",
                                  "scopes": ["chat:write"]}
    cli.restart_daemon_if_running = lambda: False
    code = 0
    try:
        fn(con, args)
    except SystemExit as e:
        code = e.code
    finally:
        sys.stdout, sys.stderr = old_out, old_err
        cli.core.run, cli.subprocess.run = orig_run, orig_sub
        cli.slack.identity, cli.restart_daemon_if_running = orig_ident, orig_restart
    return code, out.getvalue()


class EnvFileTest(unittest.TestCase):
    def setUp(self):
        if envfile.ENV.exists():
            envfile.ENV.unlink()

    def test_set_replaces_keeps_others_and_is_private(self):
        envfile.ENV.parent.mkdir(parents=True, exist_ok=True)
        envfile.ENV.write_text("# mine\nexport OTHER='keep'\nexport PR_PULSE_SLACK_BOT_TOKEN='old'\n")
        envfile.set_value("PR_PULSE_SLACK_BOT_TOKEN", TOKEN)
        text = envfile.ENV.read_text()
        self.assertIn("# mine", text)
        self.assertIn("export OTHER='keep'", text)
        self.assertEqual(text.count("PR_PULSE_SLACK_BOT_TOKEN"), 1)
        self.assertEqual(envfile.read()["PR_PULSE_SLACK_BOT_TOKEN"], TOKEN)
        self.assertEqual(stat.S_IMODE(envfile.ENV.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(envfile.ENV.parent.stat().st_mode), 0o700)

    def test_rejects_quotes(self):
        with self.assertRaises(ValueError):
            envfile.set_value("X", "a'b")


class SecretTest(unittest.TestCase):
    def setUp(self):
        self.con = db.connect(TMP / f"s{id(self)}.db")
        if envfile.ENV.exists():
            envfile.ENV.unlink()

    def test_good_token_saved_never_printed(self):
        code, out = run(cli.cmd_secret, self.con, ["set", "bot-token", "--from-clipboard"], TOKEN)
        self.assertEqual(code, 0, out)
        self.assertNotIn(TOKEN, out)
        self.assertIn("workspace Acme", out)
        self.assertEqual(envfile.read()["PR_PULSE_SLACK_BOT_TOKEN"], TOKEN)

    def test_wrong_or_empty_clipboard_saves_nothing(self):
        for clip in ("", "https://example.com/not-a-token", "xoxp-" + "user-token-1234567890123456"):
            code, out = run(cli.cmd_secret, self.con, ["set", "bot-token", "--from-clipboard"], clip)
            self.assertNotEqual(code, 0, clip)
            self.assertFalse(envfile.ENV.exists(), clip)
            if clip:
                self.assertNotIn(clip, out)

    def test_only_from_clipboard(self):
        code, _ = run(cli.cmd_secret, self.con, ["set", "bot-token", TOKEN], TOKEN)
        self.assertNotEqual(code, 0)
        self.assertFalse(envfile.ENV.exists())

    def test_webhook_shape(self):
        good = "https://hooks.slack.com/services/T000/B000/abcdef"
        self.assertEqual(run(cli.cmd_secret, self.con, ["set", "webhook", "--from-clipboard"], good)[0], 0)
        self.assertNotEqual(run(cli.cmd_secret, self.con, ["set", "webhook", "--from-clipboard"],
                                "https://evil.example/hooks.slack.com/services/x")[0], 0)


USER_TOKEN = "xoxp-" + "1234567890-abcdefghijklmnopqrstu"   # split: a fake that secret scanners skip


class UserTokenTest(unittest.TestCase):
    """secret set user-token: only an xoxp of the person pr-pulse knows; saving it turns post_as user on."""

    def setUp(self):
        self.con = db.connect(TMP / f"u{id(self)}.db")
        for f in (envfile.ENV, db.CONFIG_PATH):
            if f.exists():
                f.unlink()
        self.orig = cli.slack.user_identity
        self.who = {"user": "ada", "user_id": "UADA", "team": "Acme", "scopes": ["chat:write", "reactions:write"]}
        cli.slack.user_identity = lambda: dict(self.who)
        os.environ.pop("PR_PULSE_SLACK_USER_TOKEN", None)

    def tearDown(self):
        cli.slack.user_identity = self.orig
        os.environ.pop("PR_PULSE_SLACK_USER_TOKEN", None)

    def save(self, clip=USER_TOKEN):
        return run(cli.cmd_secret, self.con, ["set", "user-token", "--from-clipboard"], clip)

    def config(self):
        return json.loads(db.CONFIG_PATH.read_text()) if db.CONFIG_PATH.exists() else {}

    def test_saved_sets_post_as_user_and_learns_the_slack_id(self):
        code, out = self.save()
        self.assertEqual(code, 0, out)
        self.assertNotIn(USER_TOKEN, out)
        self.assertEqual(envfile.read()["PR_PULSE_SLACK_USER_TOKEN"], USER_TOKEN)
        self.assertEqual((self.config()["post_as"], self.config()["slack_user_id"]), ("user", "UADA"))

    def test_a_bot_token_is_not_a_user_token(self):
        code, _ = self.save(TOKEN)
        self.assertNotEqual(code, 0)
        self.assertFalse(envfile.ENV.exists())

    def test_someone_elses_token_is_refused_and_not_saved(self):
        db.CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        db.CONFIG_PATH.write_text('{"slack_user_id": "UBOB"}')
        code, out = self.save()
        self.assertNotEqual(code, 0)
        self.assertIn("UBOB", out)
        self.assertFalse(envfile.ENV.exists())
        self.assertNotIn("post_as", self.config())

    def test_token_without_chat_write_is_refused(self):
        self.who["scopes"] = ["reactions:write"]
        self.assertNotEqual(self.save()[0], 0)
        self.assertFalse(envfile.ENV.exists())

    def test_refused_by_slack_saves_nothing(self):
        def refused():
            raise cli.slack.SlackError("auth.test: invalid_auth")
        cli.slack.user_identity = refused
        self.assertNotEqual(self.save()[0], 0)
        self.assertFalse(envfile.ENV.exists())

    def test_post_as_user_needs_the_token_and_only_takes_bot_or_user(self):
        self.assertNotEqual(run(cli.cmd_config, self.con, ["set", "post_as", "user"])[0], 0)
        self.assertNotEqual(run(cli.cmd_config, self.con, ["set", "post_as", "robot"])[0], 0)
        self.assertEqual(run(cli.cmd_config, self.con, ["set", "post_as", "bot"])[0], 0)

    def test_user_manifest_has_only_the_two_user_scopes(self):
        m = json.loads((ROOT / "slack/manifest-user.json").read_text())
        self.assertEqual(set(m["oauth_config"]["scopes"]), {"user"})
        self.assertEqual(set(m["oauth_config"]["scopes"]["user"]), set(cli.slack.USER_SCOPES))


class SlackSetupTest(unittest.TestCase):
    def setUp(self):
        self.con = db.connect(TMP / f"k{id(self)}.db")

    def test_manifest_url_round_trips(self):
        for kind in ("announce", "full"):
            code, out = run(cli.cmd_slack, self.con, ["manifest-url", kind])
            self.assertEqual(code, 0)
            url = out.strip()
            self.assertTrue(url.startswith("https://api.slack.com/apps?new_app=1&manifest_json="))
            m = json.loads(urllib.parse.unquote(url.split("manifest_json=", 1)[1]))
            self.assertEqual(m, json.loads((ROOT / "slack" / f"manifest-{kind}.json").read_text()))
            self.assertLess(len(url), 2000)

    def test_full_adds_exactly_the_read_and_reaction_scopes(self):
        a = set(json.loads((ROOT / "slack/manifest-announce.json").read_text())["oauth_config"]["scopes"]["bot"])
        f = set(json.loads((ROOT / "slack/manifest-full.json").read_text())["oauth_config"]["scopes"]["bot"])
        self.assertTrue(a < f)
        # reading (step 5) and reactions (verdict_style "emoji"), nothing else
        self.assertEqual(f - a, set(cli.slack.READ_SCOPES) | {cli.slack.REACT_SCOPE})

    def test_config_set_known_keys_only(self):
        code, _ = run(cli.cmd_config, self.con, ["set", "watch_channels", '["C1","C2"]'])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(db.CONFIG_PATH.read_text())["watch_channels"], ["C1", "C2"])
        code, _ = run(cli.cmd_config, self.con, ["set", "announce_channel", "C9"])
        self.assertEqual(json.loads(db.CONFIG_PATH.read_text())["announce_channel"], "C9")
        code, _ = run(cli.cmd_config, self.con, ["set", "bogus_key", "1"])
        self.assertNotEqual(code, 0)

    def test_doctor_steps(self):
        if envfile.ENV.exists():
            envfile.ENV.unlink()
        db.CONFIG_PATH.write_text("{}")
        orig = cli.slack.identity
        try:
            st = cli.doctor_state(self.con)
            self.assertFalse(st["step4_announce"])
            self.assertFalse(st["step5_read"])
            envfile.set_value("PR_PULSE_SLACK_BOT_TOKEN", TOKEN)
            os.environ.pop("PR_PULSE_SLACK_BOT_TOKEN", None)
            db.CONFIG_PATH.write_text('{"announce_channel": "C1"}')
            def revoked():
                raise cli.slack.SlackError("auth.test: invalid_auth")
            cli.slack.identity = revoked
            self.assertFalse(cli.doctor_state(self.con)["step4_announce"])   # agy: revoked token
            cli.slack.identity = lambda: {"team": "A", "bot": "b", "scopes": ["chat:write"]}
            st = cli.doctor_state(self.con)
            self.assertTrue(st["step4_announce"])
            self.assertFalse(st["step5_read"])
            cli.slack.identity = lambda: {"team": "A", "bot": "b",
                                          "scopes": ["chat:write"] + list(cli.slack.READ_SCOPES)}
            db.CONFIG_PATH.write_text('{"announce_channel": "C1", "watch_channels": ["C2"], "slack_user_id": "U1"}')
            self.assertTrue(cli.doctor_state(self.con)["step5_read"])
        finally:
            cli.slack.identity = orig
            os.environ.pop("PR_PULSE_SLACK_BOT_TOKEN", None)


class VersionTest(unittest.TestCase):
    def test_only_newer_replaces(self):
        self.assertTrue(cli.version_newer("0.5.1", "0.5.0"))
        self.assertTrue(cli.version_newer("0.10.0", "0.9.9"))
        self.assertTrue(cli.version_newer("0.5.0", ""))           # nothing installed yet
        self.assertFalse(cli.version_newer("0.5.0", "0.5.0"))
        self.assertFalse(cli.version_newer("0.4.0", "0.5.0"))     # older plugin: keep the newer build
        self.assertFalse(cli.version_newer("", "0.5.0"))
        self.assertFalse(cli.version_newer("x.y", "0.5.0"))


class AppCopyTest(unittest.TestCase):
    """The service runs from a fixed copy (~/.claude/pr-pulse/app), refreshed on plugin update."""

    def setUp(self):
        self.cur = cli.current
        self.saved = (self.cur.APP, self.cur.CACHE, self.cur.INSTALLED, cli.PLIST, cli.daemon_running)
        self.tmp = Path(tempfile.mkdtemp())
        self.cur.APP, self.cur.CACHE = self.tmp / "app", self.tmp / "cache"
        self.cur.INSTALLED = self.tmp / "installed_plugins.json"     # missing: newest in the cache
        cli.PLIST = self.tmp / "x.plist"
        cli.PLIST.write_text("")
        cli.daemon_running = lambda: (False, "")
        self.con = db.connect(self.tmp / "p.db")

    def tearDown(self):
        self.cur.APP, self.cur.CACHE, self.cur.INSTALLED, cli.PLIST, cli.daemon_running = self.saved

    def plugin(self, root, v):
        shutil.copytree(ROOT, root, ignore=lambda d, n: [x for x in n if x in ("tests", "__pycache__")])
        pj = root / ".claude-plugin" / "plugin.json"
        pj.write_text(json.dumps(dict(json.loads(pj.read_text()), version=v)))

    def sync(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cli.cmd_daemon(self.con, ["sync"])
        return out.getvalue()

    def test_sync_takes_the_installed_plugin(self):
        # Live 2026-11-11: `pr-pulse daemon sync` kept 0.7.2 while 0.7.3 sat in the plugin cache.
        self.plugin(self.cur.APP, "0.7.2")
        self.plugin(self.cur.CACHE / "m" / "pr-pulse" / "0.7.2", "0.7.2")
        self.plugin(self.cur.CACHE / "m" / "pr-pulse" / "0.7.3", "0.7.3")
        self.assertEqual(cli.newest_installed().name, "0.7.3")
        self.assertIn("now runs 0.7.3", self.sync())
        self.assertEqual(cli.plugin_version(self.cur.APP), "0.7.3")
        self.assertEqual(self.sync(), "")                  # nothing changed: quiet, stays
        self.assertEqual(cli.plugin_version(self.cur.APP), "0.7.3")

    def test_sync_follows_a_same_version_change(self):
        inst = self.cur.CACHE / "m" / "pr-pulse" / "0.7.3"
        self.plugin(inst, "0.7.3")
        self.sync()
        (inst / "prompts" / "job.md").write_text("new words, same version")
        self.assertIn("now runs 0.7.3", self.sync())
        self.assertEqual((self.cur.APP / "prompts" / "job.md").read_text(), "new words, same version")

    def test_sync_app_copies_code_not_tests_and_is_repeatable(self):
        v = cli.sync_app()
        self.assertEqual(v, json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())["version"])
        for must in ("scripts/pr-pulsed.py", "scripts/pr-pulse", "prompts/job.md", "team.json",
                     "slack/manifest-full.json", ".claude-plugin/plugin.json"):
            self.assertTrue((self.cur.APP / must).exists(), must)
        self.assertFalse((self.cur.APP / "tests").exists())
        self.assertEqual((self.cur.APP / ".source").read_text().strip(), str(ROOT))
        self.assertEqual(cli.sync_app(), v)                 # again: replaced cleanly
        self.assertFalse(self.cur.APP.with_name("app.new").exists())
        self.assertFalse(self.cur.APP.with_name("app.old").exists())

if __name__ == "__main__":
    unittest.main()


class AutoUpdateTest(unittest.TestCase):
    """pr-pulse autoupdate: reads Claude Code's switch for its marketplace, turns it on with a backup."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.saved = (cli.CLAUDE_SETTINGS, cli.KNOWN_MARKETPLACES, cli.marketplace_name)
        cli.CLAUDE_SETTINGS = self.tmp / "settings.json"
        cli.KNOWN_MARKETPLACES = self.tmp / "known_marketplaces.json"
        cli.marketplace_name = lambda: "team"
        cli.KNOWN_MARKETPLACES.write_text(json.dumps(
            {"team": {"source": {"source": "github", "repo": "acme/plugins"}}}))
        cli.CLAUDE_SETTINGS.write_text(json.dumps({"theme": "dark", "permissions": {"allow": ["Bash(ls)"]}}))

    def tearDown(self):
        cli.CLAUDE_SETTINGS, cli.KNOWN_MARKETPLACES, cli.marketplace_name = self.saved

    def run_cmd(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cli.cmd_autoupdate(None, list(args))
        return out.getvalue()

    def test_off_until_turned_on_then_on_with_everything_else_kept(self):
        self.assertIn(": off", self.run_cmd("status"))
        self.run_cmd("on")
        s = json.loads(cli.CLAUDE_SETTINGS.read_text())
        self.assertEqual(s["extraKnownMarketplaces"]["team"],
                         {"source": {"source": "github", "repo": "acme/plugins"}, "autoUpdate": True})
        self.assertEqual((s["theme"], s["permissions"]), ("dark", {"allow": ["Bash(ls)"]}))
        self.assertEqual(len(list(self.tmp.glob("settings.json.bak-pr-pulse-autoupdate-*"))), 1)
        self.assertIn(": on", self.run_cmd("status"))

    def test_the_plugin_menu_toggle_counts_and_a_settings_entry_wins(self):
        cli.KNOWN_MARKETPLACES.write_text(json.dumps({"team": {"source": {}, "autoUpdate": True}}))
        self.assertTrue(cli.autoupdate_on("team"))
        cli.CLAUDE_SETTINGS.write_text(json.dumps({"extraKnownMarketplaces": {"team": {"autoUpdate": False}}}))
        self.assertFalse(cli.autoupdate_on("team"))

    def test_no_install_means_no_marketplace_not_a_crash(self):
        cli.marketplace_name = self.saved[2]
        orig = cli.current.installed_root
        cli.current.installed_root = lambda: None
        try:
            self.assertEqual(cli.marketplace_name(), "")
        finally:
            cli.current.installed_root = orig

    def test_unreadable_settings_are_never_overwritten(self):
        cli.CLAUDE_SETTINGS.write_text("{not json")
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            self.run_cmd("on")
        self.assertEqual(cli.CLAUDE_SETTINGS.read_text(), "{not json")
