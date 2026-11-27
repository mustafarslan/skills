"""reclaim 0.4 tests: developer caches. HOME, USERPROFILE and LOCALAPPDATA point into a temporary folder,
PATH holds only the fakes and git, and the process table is a fixed list: no real cache is seen or cleared."""
import json
import os
import subprocess
import sys
import time
import unittest
from pathlib import Path

from test_reclaim import OLD, WINDOWS, Base, age_tree, can_symlink, install_tool  # noqa: F401

import caches  # noqa: E402
import plat  # noqa: E402

FAKE_TOOL = '''import json, os, sys
open(os.environ['FAKE_TOOL_LOG'], 'a').write(json.dumps([os.path.basename(sys.argv[0])] + sys.argv[1:]) + '\\n')
'''


class CacheBase(Base):
    def setUp(self):
        super().setUp()
        self.home = self.tmp / 'home'
        self.home.mkdir()
        os.environ.update(HOME=str(self.home), USERPROFILE=str(self.home), FAKE_TOOL_LOG=str(self.tmp / 'tools.log'))
        for var in ('CARGO_HOME', 'GRADLE_USER_HOME', 'GOCACHE', 'UV_CACHE_DIR', 'NUGET_PACKAGES', 'XDG_CACHE_HOME'):
            os.environ.pop(var, None)
        os.environ['PATH'] = os.pathsep.join([str(self.bin), os.path.dirname(plat.which('git'))])
        self.procs = []
        real = plat.processes
        plat.processes = lambda details=True: self.procs
        self.addCleanup(setattr, plat, 'processes', real)
        self.cfg = {'cache_days': 3, 'cache_dirs': []}  # OLD is ten days ago

    def fake(self, name):
        body = FAKE_TOOL if WINDOWS else f'#!{sys.executable}\n' + FAKE_TOOL
        install_tool(self.bin, name, body)

    def calls(self):
        f = self.tmp / 'tools.log'
        return [json.loads(line) for line in f.read_text().splitlines()] if f.exists() else []

    def local(self):
        if WINDOWS:
            return Path(os.environ['LOCALAPPDATA'])
        return self.home / 'Library' / 'Caches' if sys.platform == 'darwin' else self.home / '.cache'

    def npm_cache(self):
        d = (self.local() / 'npm-cache' / '_cacache') if WINDOWS else (self.home / '.npm' / '_cacache')
        (d / 'content').mkdir(parents=True)
        (d / 'content' / 'blob').write_bytes(b'x' * 1000)
        return d

    def go_cache(self):
        d = self.local() / 'go-build'
        (d / '00').mkdir(parents=True)
        (d / '00' / 'a-d').write_bytes(b'x' * 10)
        return d


class TestCaches(CacheBase):
    def test_a_cache_is_listed_with_its_size_and_how_it_clears(self):
        self.npm_cache()
        self.fake('npm')
        rows = {r['id']: r for r in caches.scan(self.cfg)['caches']}
        self.assertEqual(rows['npm']['size'], 1000)
        self.assertEqual((rows['npm']['how'], rows['npm']['clears_with']), ('all', 'npm cache clean --force'))
        self.assertNotIn('busy', rows['npm'])

    def test_the_tools_own_command_clears_it(self):
        self.npm_cache()
        self.fake('npm')
        out = caches.clear(self.cfg, ['npm'])
        self.assertEqual(out['results'][0]['result'], 'cleared', out)
        self.assertEqual([c[1:] for c in self.calls()], [['cache', 'clean', '--force']])

    def test_skipped_while_its_tool_runs(self):
        d = self.npm_cache()
        self.fake('npm')
        self.procs = [{'pid': 9, 'name': 'node.exe' if WINDOWS else 'node', 'exe': '',
                       'cmdline': 'node /usr/lib/node_modules/npm/bin/npm-cli.js install'}]
        self.assertIn('busy', {r['id']: r for r in caches.scan(self.cfg)['caches']}['npm'])
        out = caches.clear(self.cfg, ['npm'])
        self.assertEqual(out['results'][0]['result'], 'skipped')
        self.assertTrue((d / 'content' / 'blob').exists())
        self.assertEqual(self.calls(), [])

    def test_another_node_program_does_not_count_as_npm(self):
        self.npm_cache()
        self.procs = [{'pid': 9, 'name': 'node', 'exe': '', 'cmdline': 'node /opt/app/server.js'}]
        self.assertNotIn('busy', {r['id']: r for r in caches.scan(self.cfg)['caches']}['npm'])

    def test_without_its_tool_the_contents_go_and_the_folder_stays(self):
        d = self.go_cache()
        out = caches.clear(self.cfg, ['go'])
        self.assertEqual(out['results'][0]['result'], 'cleared', out)
        self.assertTrue(d.is_dir())
        self.assertEqual(list(d.iterdir()), [])
        self.assertEqual(out['results'][0]['freed'], 10)

    def test_a_link_inside_a_cache_is_removed_not_followed(self):
        d = self.go_cache()
        outside = self.tmp / 'mine'
        outside.mkdir()
        (outside / 'keep.txt').write_text('precious')
        if WINDOWS:
            subprocess.run(['cmd', '/c', 'mklink', '/J', str(d / 'link'), str(outside)], check=True,
                           capture_output=True)
        elif can_symlink(self.tmp):
            os.symlink(str(outside), str(d / 'link'))
        else:
            self.skipTest('no links here')
        caches.clear(self.cfg, ['go'])
        self.assertEqual((outside / 'keep.txt').read_text(), 'precious')

    def test_your_own_folder_clears_by_age(self):
        mine = self.tmp / 'my-cache'
        (mine / 'old').mkdir(parents=True)
        (mine / 'old' / 'f').write_text('x')
        (mine / 'new').mkdir()
        (mine / 'new' / 'f').write_text('y')
        age_tree(mine / 'old')
        os.utime(mine / 'old', (OLD, OLD))
        self.cfg['cache_dirs'] = [str(mine)]
        row = {r['id']: r for r in caches.scan(self.cfg)['caches']}['dir1']
        self.assertEqual((row['how'], row['old_entries']), ('by age', 1))
        caches.clear(self.cfg, ['dir1'])
        self.assertEqual(sorted(p.name for p in mine.iterdir()), ['new'])

    def test_maven_clears_whole_version_folders_by_age(self):
        repo = self.home / '.m2' / 'repository' / 'org' / 'ex' / 'lib'
        for v, when in (('1.0', OLD), ('2.0', time.time())):
            (repo / v).mkdir(parents=True)
            (repo / v / f'lib-{v}.pom').write_text('<project/>')
            (repo / v / f'lib-{v}.jar').write_bytes(b'j')
            age_tree(repo / v, when)
            os.utime(repo / v, (when, when))
        caches.clear(self.cfg, ['maven'])
        self.assertEqual(sorted(p.name for p in repo.iterdir()), ['2.0'])

    def test_a_gradle_daemon_keeps_the_gradle_cache(self):
        d = self.home / '.gradle' / 'caches' / 'modules-2' / 'files-2.1' / 'g' / 'm' / '1'
        d.mkdir(parents=True)
        (d / 'a.jar').write_bytes(b'j')
        age_tree(self.home / '.gradle')
        self.procs = [{'pid': 5, 'name': 'java', 'exe': '',
                       'cmdline': 'java -cp gradle.jar org.gradle.launcher.daemon.bootstrap.GradleDaemon 8.5'}]
        self.assertEqual(caches.clear(self.cfg, ['gradle'])['results'][0]['result'], 'skipped')
        self.assertTrue((d / 'a.jar').exists())

    def test_an_unknown_id_is_refused(self):
        self.assertEqual(caches.clear(self.cfg, ['../home'])['results'][0]['result'], 'skipped')


if __name__ == '__main__':
    unittest.main()
