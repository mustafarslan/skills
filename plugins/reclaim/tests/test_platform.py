"""reclaim 0.4 tests: the platform layer and the Windows port. Same fakes as test_reclaim.py.

The Windows tests use real processes, real open files and real junctions in temporary folders; nothing
outside them is touched. On macOS and Linux they skip, and the POSIX tests in the other files cover the same
cases there.
"""
import json
import os
import subprocess
import sys
import time
import unittest
from pathlib import Path

from test_reclaim import HERE, POSIX_ONLY, WINDOWS, WINDOWS_ONLY, Base, age_tree, can_symlink, sh  # noqa: F401

import backup as backup_mod  # noqa: E402
import docker  # noqa: E402
import plat  # noqa: E402
import worktrees  # noqa: E402

FIXTURES = HERE / 'tests' / 'fixtures' / 'windows'


def junction(link, target):
    """A directory junction (no admin needed, unlike a symlink)."""
    subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(target)], check=True, capture_output=True)


def hold_open(path, cwd=None):
    """A child process that keeps path open (or, with cwd, sits in a folder) until killed."""
    code = 'import sys, time\nf = open(sys.argv[1]) if sys.argv[1] != "-" else None\nprint("ready", flush=True)\n' \
           'time.sleep(120)\n'
    p = subprocess.Popen([sys.executable, '-c', code, str(path) if path else '-'], cwd=cwd, stdout=subprocess.PIPE,
                         text=True)
    p.stdout.readline()
    p.stdout.close()
    return p


class TestPaths(unittest.TestCase):
    def test_posix_inside_test_is_the_old_string_test(self):
        real = plat.WINDOWS
        plat.WINDOWS = False
        self.addCleanup(setattr, plat, 'WINDOWS', real)
        self.assertTrue(plat.same_or_inside('/a/b', '/a'))
        self.assertTrue(plat.same_or_inside('/a', '/a'))
        self.assertFalse(plat.same_or_inside('/ab', '/a'))
        self.assertFalse(plat.same_or_inside('/A/b', '/a'))  # as before: no case folding off Windows

    @WINDOWS_ONLY
    def test_windows_inside_test_folds_case_and_separators(self):
        self.assertTrue(plat.same_or_inside('C:\\Work\\Repo\\wt', 'c:/work/repo'))
        self.assertTrue(plat.same_or_inside('c:/work/repo', 'C:\\Work\\Repo\\'))
        self.assertFalse(plat.same_or_inside('C:\\Work\\Repo2', 'C:\\Work\\Repo'))
        self.assertFalse(plat.same_or_inside('D:\\Work', 'C:\\Work'))

    @WINDOWS_ONLY
    def test_git_paths_become_windows_paths(self):
        self.assertEqual(plat.native('C:/Users/x/wt'), 'C:\\Users\\x\\wt')
        self.assertEqual(plat.base_name('C:\\a\\wt-12\\'), 'wt-12')
        self.assertEqual(plat.rel('C:\\a\\inner\\wt', 'C:\\a'), 'inner/wt')

    def test_batch_file_arguments_are_quoted_or_refused(self):
        line = plat._batch_line(['C:\\bin\\docker.cmd', 'inspect', '-f', '{{.A}}|{{.B}}', 'id'])
        self.assertEqual(line, '"C:\\bin\\docker.cmd" inspect -f "{{.A}}|{{.B}}" id')
        self.assertIsNone(plat._batch_line(['x.cmd', '%PATH%']))
        self.assertIsNone(plat._batch_line(['x.cmd', 'a"b']))


class TestPrograms(Base):
    @WINDOWS_ONLY
    def test_which_never_picks_a_program_in_the_current_folder(self):
        planted = self.tmp / 'cwd'
        planted.mkdir()
        (planted / 'git.exe').write_bytes(b'MZ')
        old = os.getcwd()
        os.chdir(planted)
        self.addCleanup(os.chdir, old)
        found = plat.which('git')
        self.assertTrue(found and os.path.isabs(found))
        self.assertNotEqual(os.path.dirname(found).lower(), str(planted).lower())

    @WINDOWS_ONLY
    def test_a_pipe_reaches_a_batch_file_intact(self):
        plat.run(['docker', 'inspect', '-f', '{{.State.FinishedAt}}|{{.Created}}', 'abc'])
        calls = [json.loads(line) for line in (self.tmp / 'docker.log').read_text().splitlines()]
        self.assertEqual(calls[-1], ['inspect', '-f', '{{.State.FinishedAt}}|{{.Created}}', 'abc'])

    def test_missing_program_is_127_not_an_exception(self):
        rc, _, _ = plat.run(['no-such-program-reclaim'])
        self.assertEqual(rc, 127)


class TestDelete(Base):
    def test_read_only_files_are_deleted(self):
        d = self.tmp / 'ro'
        (d / 'sub').mkdir(parents=True)
        f = d / 'sub' / 'f.txt'
        f.write_text('x')
        os.chmod(f, 0o444)
        self.assertEqual(plat.delete_tree(d), {'ok': True})
        self.assertFalse(d.exists())

    def test_a_link_inside_is_removed_not_followed(self):
        outside = self.tmp / 'outside'
        outside.mkdir()
        (outside / 'keep.txt').write_text('precious')
        d = self.tmp / 'tree'
        d.mkdir()
        if WINDOWS:
            junction(d / 'node_modules', outside)
        elif can_symlink(self.tmp):
            os.symlink(str(outside), str(d / 'node_modules'))
        else:
            self.skipTest('no links here')
        self.assertTrue(plat.is_link_or_junction(str(d / 'node_modules')))
        self.assertEqual(plat.delete_tree(d), {'ok': True})
        self.assertEqual((outside / 'keep.txt').read_text(), 'precious')

    @WINDOWS_ONLY
    def test_paths_past_260_characters(self):
        d = self.tmp / 'deep'
        p = plat.long_path(str(d / ('x' * 120) / ('y' * 120) / ('z' * 60)))
        os.makedirs(p)
        with open(os.path.join(p, 'f.txt'), 'w') as f:
            f.write('x')
        self.assertGreater(len(plat.short_path(p)), 260)
        self.assertEqual(plat.dir_size(d), 1)
        self.assertEqual(plat.delete_tree(d), {'ok': True})

    @WINDOWS_ONLY
    def test_a_held_file_is_reported_and_left(self):
        d = self.tmp / 'held'
        d.mkdir()
        (d / 'a.txt').write_text('a')
        (d / 'b.log').write_text('b')
        p = hold_open(d / 'b.log')
        self.addCleanup(p.wait)
        self.addCleanup(p.kill)
        held = plat.held_files(str(d))
        self.assertEqual((held['count'], held['files']), (1, ['b.log']))
        self.assertTrue(any('python' in b.lower() for b in held['by']), held)

    @WINDOWS_ONLY
    def test_size_does_not_count_what_a_junction_points_to(self):
        outside = self.tmp / 'big'
        outside.mkdir()
        (outside / 'f.bin').write_bytes(b'x' * 5000)
        d = self.tmp / 'small'
        d.mkdir()
        (d / 'a').write_bytes(b'x' * 10)
        junction(d / 'link', outside)
        self.assertEqual(plat.dir_size(d), 10)


@WINDOWS_ONLY
class TestWindowsInUse(Base):
    """The deciding check on Windows: a folder some process sits in can't be opened exclusively."""

    def test_probe_sees_a_process_in_a_subfolder(self):
        p = self.worktree('busy-win')
        sub = Path(p) / 'src' / 'deep'
        sub.mkdir(parents=True)
        age_tree(p)
        child = hold_open(None, cwd=str(sub))
        self.addCleanup(child.wait)
        self.addCleanup(child.kill)
        self.assertEqual(plat.busy_dirs(p), ['src/deep'])
        row = self.scan()[p]
        self.assertEqual(row['verdict'], 'keep')
        self.assertTrue(any(r.startswith('in use by') and 'python' in r.lower() for r in row['reasons']),
                        row['reasons'])

    def test_probe_changes_nothing_and_frees_after_the_process_ends(self):
        p = self.worktree('was-busy')
        child = hold_open(None, cwd=p)
        self.assertEqual(plat.busy_dirs(p), ['.'])
        child.kill()
        child.wait()
        age_tree(p)
        self.assertEqual(plat.busy_dirs(p), [])
        self.assertEqual(self.scan()[p]['verdict'], 'remove')

    def test_a_probe_that_cannot_run_keeps_everything(self):
        p = self.worktree('no-probe')
        real = plat.busy_dirs
        plat.busy_dirs = lambda *a, **k: None
        self.addCleanup(setattr, plat, 'busy_dirs', real)
        row = self.scan()[p]
        self.assertEqual(row['verdict'], 'keep')
        self.assertIn('could not check which processes use it', row['reasons'])


@WINDOWS_ONLY
class TestWindowsRemove(Base):
    def test_a_locked_file_keeps_the_whole_tree(self):
        p = self.worktree('locked-file')
        (Path(p) / '.gitignore').write_text('.env.local\nnode_modules/\n*.log\n')
        self.commit(p, 'ignore logs')
        sh('git', 'push', '-q', 'origin', 'locked-file', cwd=p)
        (Path(p) / 'server.log').write_text('busy')
        age_tree(p)
        child = hold_open(Path(p) / 'server.log')
        self.addCleanup(child.wait)
        self.addCleanup(child.kill)
        self.assertEqual(self.scan()[p]['verdict'], 'backup+remove')
        out = worktrees.remove([p], str(self.backups), backup_mod.backup)
        r = out['results'][0]
        self.assertEqual(r['result'], 'skipped', r)
        self.assertIn('locked by', r['why'])
        self.assertIn('server.log', r['why'])
        self.assertTrue((Path(p) / 'a.txt').exists() and (Path(p) / 'locked-file.txt').exists())

    def test_a_junction_inside_goes_with_the_tree_and_its_target_stays(self):
        outside = self.tmp / 'store'
        outside.mkdir()
        (outside / 'pkg.js').write_text('shared')
        p = self.worktree('with-junction')
        junction(Path(p) / 'node_modules', outside)
        age_tree(p)
        self.assertEqual(self.scan()[p]['verdict'], 'remove')
        out = worktrees.remove([p], str(self.backups), backup_mod.backup)
        self.assertEqual(out['results'][0]['result'], 'removed', out)
        self.assertFalse(os.path.lexists(p))
        self.assertEqual((outside / 'pkg.js').read_text(), 'shared')

    def test_an_ignored_junction_is_backed_up_as_a_link(self):
        outside = self.tmp / 'data'
        outside.mkdir()
        (outside / 'big.bin').write_bytes(b'x' * 100)
        p = self.worktree('ignored-junction')
        (Path(p) / '.gitignore').write_text('.env.local\nnode_modules/\nlinked\n')
        self.commit(p, 'ignore linked')
        sh('git', 'push', '-q', 'origin', 'ignored-junction', cwd=p)
        junction(Path(p) / 'linked', outside)
        out = backup_mod.backup(p, str(self.backups))
        self.assertTrue(out['ok'], out)
        import tarfile
        with tarfile.open(Path(out['dir']) / 'ignored.tgz') as t:
            m = t.getmember('linked')
            self.assertTrue(m.issym())
            self.assertNotIn('linked/big.bin', t.getnames())
        self.assertIn('tar.exe Windows ships', (Path(out['dir']) / 'INFO.txt').read_text())


class TestWindowsDocker(Base):
    def test_wsl_list_with_no_distros_is_empty(self):
        for name in ('wsl-l-v-no-distros.utf16.txt', 'wsl-l-v-no-distros.utf8.txt'):
            self.assertEqual(docker.parse_wsl_list((FIXTURES / name).read_bytes()), [], name)

    def test_wsl_list_rows_are_read_by_position(self):
        text = ('  NAME              STATE           VERSION\r\n* Ubuntu            Stopped         2\r\n'
                '  docker-desktop    Running         2\r\n')  # the documented layout, not a capture
        for raw in (text.encode('utf-16-le'), text.encode('utf-8')):
            rows = docker.parse_wsl_list(raw)
            self.assertEqual([(r['name'], r['state'], r['default']) for r in rows],
                             [('Ubuntu', 'Stopped', True), ('docker-desktop', 'Running', False)])

    def fake_desktop(self):
        root = Path(os.environ.get('LOCALAPPDATA', str(self.tmp))) / 'Programs' / 'DockerDesktop'
        (root / 'resources').mkdir(parents=True)
        return root

    @WINDOWS_ONLY
    def test_not_started_docker_is_down_and_never_called_hung(self):
        body = ('import sys\nsys.stderr.write(open(%r).read())\nsys.exit(1)\n'
                % str(FIXTURES / 'docker-info-not-started.txt'))
        self.tool('docker', '', body)
        out = docker.status(3, [])
        self.assertEqual((out['installed'], out['up']), (True, False))
        self.assertFalse(out['down']['hung'])
        self.assertFalse(out['down']['verified_on_windows'])

    @WINDOWS_ONLY
    def test_hung_on_windows_is_only_suspected_until_verified(self):
        root = self.fake_desktop()
        log = self.tmp / 'backend.log'
        log.write_text('x no space left on device\nbackend state changed to stopping\n')
        os.environ['RECLAIM_DOCKER_LOG'] = str(log)
        procs = [{'pid': 4242, 'name': 'com.docker.backend.exe', 'exe': str(root / 'resources' / 'com.docker.backend.exe')},
                 {'pid': 77, 'name': 'com.docker.backend.exe', 'exe': str(self.tmp / 'elsewhere.exe')}]
        real = plat.processes
        plat.processes = lambda details=True: procs
        self.addCleanup(setattr, plat, 'processes', real)
        state = docker.hung_state()
        self.assertEqual(state['pids'], [4242])  # by path: a same-named program elsewhere is not Docker's
        self.assertTrue(state['hung_suspected'])
        self.assertFalse(state['hung'])

    @WINDOWS_ONLY
    def test_revive_spawns_nothing_until_it_has_run_live(self):
        self.tool('docker', '', 'import sys\nsys.exit(1)\n')
        spawned = []
        real_run, real_start = docker.run, docker.start_detached

        def fake_run(cmd, **kw):
            if cmd[0] in ('taskkill', 'wsl'):
                spawned.append(cmd)
                return 0, '', ''
            return real_run(cmd, **kw)
        docker.run = fake_run
        docker.start_detached = spawned.append
        self.addCleanup(setattr, docker, 'run', real_run)
        self.addCleanup(setattr, docker, 'start_detached', real_start)
        out = docker.restart_hung(wait=1, grace=0)
        self.assertFalse(out['ok'])
        self.assertTrue(out['report_only'])
        self.assertEqual(spawned, [])


if __name__ == '__main__':
    unittest.main()
