"""Update-notice tests (the same file in every plugin of this marketplace). No real network: the "latest" URL is a
local file or a local fake server; the cache and the plugin folder are temporary."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN / "scripts"))
import update_check as uc  # noqa: E402


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="update-check-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = self.tmp / "root"
        (self.root / ".claude-plugin").mkdir(parents=True)
        self.data = self.tmp / "data"
        self.set_installed("0.4.0")
        self.published = self.tmp / "published.json"
        self.set_published("0.5.0")

    def set_installed(self, version):
        (self.root / ".claude-plugin" / "plugin.json").write_text(json.dumps({"name": "demo", "version": version}))

    def set_published(self, version):
        self.published.write_text(json.dumps({"name": "demo", "version": version}))

    def env(self, **extra):
        env = {k: v for k, v in os.environ.items() if not k.startswith(("MUSTAFARSLAN_", "CLAUDE_PLUGIN_"))}
        env.update(CLAUDE_PLUGIN_ROOT=str(self.root), CLAUDE_PLUGIN_DATA=str(self.data),
                   MUSTAFARSLAN_SKILLS_UPDATE_URL=self.published.as_uri())
        env.update(extra)
        return {k: v for k, v in env.items() if v is not None}

    def run_check(self, **extra):
        p = subprocess.run([sys.executable, str(PLUGIN / "scripts" / "update_check.py")], env=self.env(**extra),
                           capture_output=True, text=True, timeout=30)
        self.assertEqual(p.returncode, 0)
        return p.stdout.strip()

    def message(self, out):
        return json.loads(out)["systemMessage"]

    def age_cache(self, hours):
        cache = self.data / uc.CACHE_NAME
        data = json.loads(cache.read_text())
        data["checked_at"] = time.time() - hours * 3600
        cache.write_text(json.dumps(data))


class NoticeTest(Fixture):
    def test_newer_version_shows_one_system_message(self):
        out = self.run_check()
        self.assertEqual(
            self.message(out),
            "demo 0.5.0 is out (you have 0.4.0). Update: claude plugin marketplace update mustafarslan-skills && "
            "claude plugin update demo@mustafarslan-skills (then restart), or turn on auto-update in "
            "/plugin → Marketplaces.")
        self.assertEqual(list(json.loads(out)), ["systemMessage"])

    def test_same_version_is_silent(self):
        self.set_published("0.4.0")
        self.assertEqual(self.run_check(), "")

    def test_older_version_is_silent(self):
        self.set_published("0.3.9")
        self.assertEqual(self.run_check(), "")

    def test_opt_out_is_silent_and_does_not_fetch(self):
        self.assertEqual(self.run_check(MUSTAFARSLAN_SKILLS_UPDATE_CHECK="0"), "")
        self.assertFalse(self.data.exists())

    def test_missing_published_file_is_silent(self):
        self.published.unlink()
        self.assertEqual(self.run_check(), "")

    def test_bad_json_is_silent(self):
        self.published.write_text("{not json")
        self.assertEqual(self.run_check(), "")

    def test_missing_installed_plugin_json_is_silent(self):
        (self.root / ".claude-plugin" / "plugin.json").unlink()
        self.assertEqual(self.run_check(), "")

    def test_no_data_dir_skips_the_check(self):
        self.assertEqual(self.run_check(CLAUDE_PLUGIN_DATA=None), "")

    def test_launcher_runs_the_check(self):
        sh = shutil.which("sh")
        if not sh:
            self.skipTest("no sh on PATH")
        p = subprocess.run([sh, str(PLUGIN / "scripts" / "update-check")], env=self.env(), capture_output=True,
                           text=True, timeout=30)
        self.assertEqual(p.returncode, 0)
        self.assertIn("demo 0.5.0 is out", self.message(p.stdout))


class CacheTest(Fixture):
    def test_within_a_day_no_fetch_but_notice_still_shown(self):
        self.assertIn("0.5.0", self.message(self.run_check()))
        self.published.unlink()  # a second fetch would now fail; the cache must answer
        self.assertIn("0.5.0", self.message(self.run_check()))

    def test_cached_result_is_not_refetched_when_newer_appears(self):
        self.run_check()
        self.set_published("0.9.0")
        self.assertIn("0.5.0", self.message(self.run_check()))

    def test_after_a_day_it_fetches_again(self):
        self.run_check()
        self.age_cache(25)
        self.set_published("0.9.0")
        self.assertIn("0.9.0", self.message(self.run_check()))

    def test_failed_fetch_counts_as_a_try_and_keeps_the_last_version(self):
        self.run_check()
        self.age_cache(25)
        self.published.unlink()
        self.assertIn("0.5.0", self.message(self.run_check()))
        self.assertLess(time.time() - json.loads((self.data / uc.CACHE_NAME).read_text())["checked_at"], 600)

    def test_corrupt_cache_is_ignored(self):
        self.data.mkdir()
        (self.data / uc.CACHE_NAME).write_text("garbage")
        self.assertIn("0.5.0", self.message(self.run_check()))


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.server.hits += 1
        time.sleep(self.server.delay)
        body = json.dumps({"name": "demo", "version": "0.5.0"}).encode()
        try:
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except OSError:
            pass

    def log_message(self, *args):
        pass


class ServerTest(Fixture):
    def serve(self, delay):
        srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        srv.hits, srv.delay, srv.daemon_threads = 0, delay, True
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        return srv, "http://127.0.0.1:%d/plugin.json" % srv.server_address[1]

    def test_fetch_over_http_once_a_day(self):
        srv, url = self.serve(0)
        self.assertIn("0.5.0", self.message(self.run_check(MUSTAFARSLAN_SKILLS_UPDATE_URL=url)))
        self.assertIn("0.5.0", self.message(self.run_check(MUSTAFARSLAN_SKILLS_UPDATE_URL=url)))
        self.assertEqual(srv.hits, 1)

    def test_timeout_is_silent_and_quick(self):
        srv, url = self.serve(5)
        start = time.time()
        out = self.run_check(MUSTAFARSLAN_SKILLS_UPDATE_URL=url, MUSTAFARSLAN_SKILLS_UPDATE_TIMEOUT="0.5")
        self.assertEqual(out, "")
        self.assertLess(time.time() - start, 4)

    def test_unreachable_server_is_silent(self):
        srv, url = self.serve(0)
        srv.shutdown()
        srv.server_close()
        self.assertEqual(self.run_check(MUSTAFARSLAN_SKILLS_UPDATE_URL=url), "")

    def test_default_url_is_the_repo_raw_file_and_the_repo_can_be_overridden(self):
        captured = []
        real = uc.fetch_version
        uc.fetch_version = lambda url, timeout: captured.append((url, timeout)) or "0.5.0"
        self.addCleanup(setattr, uc, "fetch_version", real)
        old = dict(os.environ)
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(old)))
        for k in list(os.environ):
            if k.startswith("MUSTAFARSLAN_"):
                del os.environ[k]
        uc.latest_version("demo", str(self.data), time.time())
        self.assertEqual(captured, [("https://raw.githubusercontent.com/mustafarslan/skills/master/"
                                     "plugins/demo/.claude-plugin/plugin.json", 3.0)])
        os.environ["MUSTAFARSLAN_SKILLS_UPDATE_REPO"] = "someone/fork"
        (self.data / uc.CACHE_NAME).unlink()
        uc.latest_version("demo", str(self.data), time.time())
        self.assertTrue(captured[1][0].startswith("https://raw.githubusercontent.com/someone/fork/master/"))


class VersionCompareTest(unittest.TestCase):
    def test_numeric_not_text_order(self):
        self.assertTrue(uc.is_newer("0.10.0", "0.9.0"))
        self.assertFalse(uc.is_newer("0.9.0", "0.10.0"))
        self.assertTrue(uc.is_newer("1.0.0", "0.99.99"))
        self.assertTrue(uc.is_newer("0.12.2", "0.12.1"))

    def test_equal_and_trailing_zeros(self):
        self.assertFalse(uc.is_newer("1.0", "1.0.0"))
        self.assertFalse(uc.is_newer("0.4.0", "0.4.0"))
        self.assertTrue(uc.is_newer("1.0.1", "1.0"))

    def test_prerelease_is_older_than_release(self):
        self.assertTrue(uc.is_newer("1.0.0", "1.0.0-rc1"))
        self.assertFalse(uc.is_newer("1.0.0-rc1", "1.0.0"))

    def test_unparsable_is_never_newer(self):
        for bad in ("", "abc", None, "1.x", "latest"):
            self.assertFalse(uc.is_newer(bad, "0.1.0"))
            self.assertFalse(uc.is_newer("9.9.9", bad))


if __name__ == "__main__":
    unittest.main()
