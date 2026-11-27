"""reclaim 0.4 tests: Docker's disk image (report on both systems, compact on Windows).

Nothing here starts PowerShell elevated, stops WSL or touches a real disk image: the steps that would are
replaced by recorders, and the disk images are small files in a temporary folder.
"""
import json
import os
import subprocess
import unittest
from pathlib import Path

from test_reclaim import HERE, WINDOWS, WINDOWS_ONLY, Base  # noqa: F401
from test_platform import hold_open

import docker  # noqa: E402
import plat  # noqa: E402
import vdisk  # noqa: E402

REAL_BLOCKERS = vdisk.blockers


class DiskBase(Base):
    def setUp(self):
        super().setUp()
        self.vhdx = self.tmp / 'disk' / 'docker_data.vhdx'
        self.vhdx.parent.mkdir()
        self.vhdx.write_bytes(b'\0' * 4096)
        self.spawned = []
        for name, fake in (('disk_paths', lambda: [(str(self.vhdx), 'data')]),
                           ('elevate', self.fake_elevate),
                           ('blockers', lambda procs=None: [])):
            real = getattr(vdisk, name)
            setattr(vdisk, name, fake)
            self.addCleanup(setattr, vdisk, name, real)
        real_run = vdisk.run

        def run(cmd, **kw):
            if cmd[0] in ('wsl', 'powershell', 'diskpart'):
                self.spawned.append(cmd)
                return 0, '', ''
            return real_run(cmd, **kw)
        vdisk.run = run
        self.addCleanup(setattr, vdisk, 'run', real_run)
        self.distros = []
        real_wsl = docker.wsl_distros
        docker.wsl_distros = lambda: self.distros
        self.addCleanup(setattr, docker, 'wsl_distros', real_wsl)
        self.live(False)

    def live(self, on):
        real = dict(docker.LIVE_ON_WINDOWS)
        docker.LIVE_ON_WINDOWS['compact'] = on
        self.addCleanup(docker.LIVE_ON_WINDOWS.update, real)

    def fake_elevate(self, script, timeout=3600):
        self.spawned.append(['elevated', script])
        result_file = script.split('-ResultFile "')[1].split('"')[0]
        Path(result_file).write_text(json.dumps({'ok': True, 'tool': 'diskpart', 'steps': ['compact vdisk']}),
                                     encoding='utf-8')
        return 0, '', ''


class TestDiskReport(DiskBase):
    def test_sizes_are_shown_against_what_docker_holds(self):
        self.tool('docker', '#!/bin/sh\nexit 1\n', 'import sys\nsys.exit(1)\n')  # down: no "inside" figures
        out = vdisk.report()
        self.assertEqual(out['disks'][0]['size'], 4096)
        self.assertIn('on_disk', out['disks'][0])
        self.assertNotIn('inside', out)

    def test_docker_df_sizes_are_read(self):
        self.assertEqual(vdisk.to_bytes('1.5GB'), 1_500_000_000)
        self.assertEqual(vdisk.to_bytes('12.3kB (40%)'), 12_300)
        self.assertEqual(vdisk.to_bytes('0B'), 0)
        self.assertEqual(vdisk.to_bytes('n/a'), 0)

    @unittest.skipIf(WINDOWS, 'macOS')
    def test_mac_never_compacts(self):
        self.assertIn('sparse', vdisk.report()['compact']['why'])
        self.assertFalse(vdisk.compact(first_live_run=True)['ok'])
        self.assertEqual(self.spawned, [])


@WINDOWS_ONLY
class TestCompact(DiskBase):
    def test_report_only_until_it_has_run_live(self):
        out = vdisk.compact()
        self.assertTrue(out['report_only'])
        self.assertEqual(self.spawned, [])

    def test_never_while_docker_runs_or_a_build_runs(self):
        vdisk.blockers = lambda procs=None: ['Docker Desktop is running or starting: quit it first']
        out = vdisk.compact(first_live_run=True)
        self.assertEqual(out['error'], 'not now')
        self.assertEqual(self.spawned, [])

    def test_docker_processes_and_docker_commands_block_it(self):
        root = Path(os.environ['LOCALAPPDATA']) / 'Programs' / 'DockerDesktop'
        procs = [{'pid': 10, 'name': 'com.docker.build.exe', 'exe': str(root / 'resources' / 'com.docker.build.exe')},
                 {'pid': 11, 'name': 'docker.exe', 'exe': 'C:\\x\\docker.exe', 'cmdline': 'docker build .'}]
        why = REAL_BLOCKERS(procs)
        self.assertEqual(len(why), 2, why)
        self.assertEqual(REAL_BLOCKERS([{'pid': 1, 'name': 'Code.exe', 'exe': 'C:\\x\\Code.exe', 'cmdline': ''}]), [])

    def test_a_running_docker_distro_needs_a_yes_to_stop(self):
        self.distros = [{'name': 'docker-desktop', 'state': 'Running', 'version': 2, 'default': False}]
        out = vdisk.compact(first_live_run=True)
        self.assertEqual(out['needs'], 'release')
        self.assertEqual(self.spawned, [])
        vdisk.compact(first_live_run=True, release=True)
        self.assertIn(['wsl', '--terminate', 'docker-desktop'], self.spawned)
        self.assertNotIn(['wsl', '--shutdown'], self.spawned)

    def test_a_held_disk_needs_a_yes_to_shut_wsl_down_and_names_the_other_distros(self):
        self.distros = [{'name': 'Ubuntu', 'state': 'Running', 'version': 2, 'default': True}]
        child = hold_open(self.vhdx)
        self.addCleanup(child.wait)
        self.addCleanup(child.kill)
        out = vdisk.compact(first_live_run=True)
        self.assertEqual((out['needs'], out['other_running']), ('shutdown', ['Ubuntu']))
        self.assertEqual(self.spawned, [])

    def test_dry_run_shows_the_one_elevated_step_and_changes_nothing(self):
        out = vdisk.compact(first_live_run=True, dry_run=True)
        self.assertTrue(out['dry_run'])
        self.assertIn('-Verb RunAs', out['would_run'])
        self.assertIn(str(self.vhdx), out['would_run'])
        self.assertEqual(self.spawned, [])

    def test_the_result_is_read_back_from_its_file(self):
        out = vdisk.compact(first_live_run=True)
        self.assertTrue(out['ok'], out)
        self.assertEqual(out['result']['tool'], 'diskpart')
        self.assertEqual([c[0] for c in self.spawned], ['elevated'])

    def test_no_result_file_is_a_failure_not_a_success(self):
        vdisk.elevate = lambda script, timeout=3600: (1, 'boom', '')
        out = vdisk.compact(first_live_run=True)
        self.assertFalse(out['ok'])
        self.assertIn('did not report back', out['error'])

    def test_the_script_itself_parses_and_reports_in_dry_run(self):
        result = self.tmp / 'r.json'
        ps = os.path.join(os.environ.get('SystemRoot', 'C:\\Windows'), 'System32', 'WindowsPowerShell', 'v1.0',
                          'powershell.exe')
        p = subprocess.run([ps, '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File',
                            str(HERE / 'scripts' / 'compact.ps1'), '-Vhdx', str(self.vhdx), '-ResultFile',
                            str(result), '-DryRun'], capture_output=True, text=True, timeout=120)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        r = json.loads(result.read_text(encoding='utf-8-sig'))
        self.assertTrue(r['ok'] and r['dry_run'])
        self.assertIn(r['tool'], ('Optimize-VHD', 'diskpart'))
        self.assertEqual(self.vhdx.read_bytes(), b'\0' * 4096)


if __name__ == '__main__':
    unittest.main()
