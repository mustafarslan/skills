"""reclaim 0.2 tests: the safety, portability and config fixes. Same fakes as test_reclaim.py."""
import json
import os
import subprocess
import sys
import time
import unittest
from pathlib import Path

from test_reclaim import HERE, Base, age_tree, sh  # noqa: F401

import backup as backup_mod  # noqa: E402
import common  # noqa: E402
import docker  # noqa: E402
import reclaim as cli  # noqa: E402
import worktrees  # noqa: E402


class TestWorktreeSafety(Base):
    def test_edited_ignored_file_changes_the_fingerprint(self):
        p = self.worktree('envfp')
        (Path(p) / '.env.local').write_text('A=1\n')
        age_tree(p)
        before = self.scan()[p]['fingerprint']
        (Path(p) / '.env.local').write_text('A=2222\n')  # same name, new content
        self.assertNotEqual(before, self.scan()[p]['fingerprint'])

    def test_edit_to_an_ignored_file_after_the_scan_skips_the_removal(self):
        p = self.worktree('envdrift')
        (Path(p) / '.env.local').write_text('A=1\n')
        age_tree(p)
        self.scan()
        (Path(p) / '.env.local').write_text('A=changed after the scan\n')
        out = worktrees.remove([p], str(self.backups), backup_mod.backup)
        self.assertEqual(out['results'][0]['result'], 'skipped')
        self.assertTrue((Path(p) / '.env.local').exists())

    def test_locked_worktree_is_kept(self):
        p = self.worktree('locked')
        sh('git', 'worktree', 'lock', p, cwd=self.repo)
        row = self.scan()[p]
        self.assertEqual(row['verdict'], 'keep')
        self.assertIn('worktree is locked', row['reasons'])

    def test_sparse_skip_worktree_files_keep_the_tree(self):
        p = self.worktree('sparse')
        sh('git', 'update-index', '--skip-worktree', 'a.txt', cwd=p)
        age_tree(p)
        row = self.scan()[p]
        self.assertEqual(row['verdict'], 'keep')
        self.assertTrue(any('skip-worktree' in r for r in row['reasons']))

    def test_main_named_branch_is_never_merged_safe(self):
        p = self.worktree('plain')
        head = sh('git', 'rev-parse', 'HEAD', cwd=p)
        sh('git', 'branch', '-m', 'master', cwd=p)  # a shared name; fork PRs from "master" must not count
        self.set_prs({'master': [{'number': 9, 'state': 'MERGED', 'headRefOid': head}]})
        age_tree(p, time.time())
        row = self.scan(days=30)[p]
        self.assertEqual(row['merged_prs'], [])
        self.assertEqual(row['verdict'], 'keep')

    def test_removing_one_tree_does_not_touch_another_trees_record(self):
        a = self.worktree('goner')
        b = self.worktree('unplugged')
        self.scan()
        sh('mv', b, b + '.away')  # looks missing, like a worktree on an unplugged disk
        seen = []
        real = worktrees.git

        def spy(path, *args, **kw):
            seen.append(args)
            return real(path, *args, **kw)
        worktrees.git = spy
        self.addCleanup(setattr, worktrees, 'git', real)
        out = worktrees.remove([a], str(self.backups), backup_mod.backup)
        self.assertEqual(out['results'][0]['result'], 'removed')
        self.assertFalse(any(x[:2] == ('worktree', 'prune') for x in seen))
        sh('mv', b + '.away', b)
        self.assertIn(b, [w for w, _ in worktrees.list_worktrees(str(self.repo))])

    def test_missing_parent_folder_is_kept_not_pruned(self):
        gone = self.tmp / 'no-such-disk' / 'wt'
        row = worktrees.inspect(str(gone), False, 0, {}, None, with_prs=False)
        self.assertEqual(row['verdict'], 'keep')

    def test_bare_repo_entry_is_not_a_checkout(self):
        bare = self.tmp / 'bare.git'
        sh('git', 'clone', '-q', '--bare', str(self.remote), str(bare))
        sh('git', 'worktree', 'add', '-q', '-b', 'w1', str(self.tmp / 'bw'), 'HEAD', cwd=bare)
        listed = worktrees.list_worktrees(str(bare))
        self.assertEqual([p for p, _ in listed], [str(self.tmp / 'bw')])

    def test_missing_gh_degrades_and_says_so(self):
        p = self.worktree('nogh')
        (self.bin / 'gh').unlink()
        os.environ['PATH'] = f'{self.bin}:/usr/bin:/bin'
        rows = worktrees.scan([str(self.repo)], 3, current=str(self.tmp), with_size=False)
        self.assertFalse(rows['prs_checked'])
        self.assertTrue(any('PRs were not checked' in w for w in rows['warnings']))
        row = {r['path']: r for r in rows['rows']}[p]
        self.assertEqual(row['verdict'], 'remove')

    def test_proc_reader_lists_cwds(self):
        proc = self.tmp / 'proc' / '77'
        proc.mkdir(parents=True)
        (proc / 'comm').write_text('editor\n')
        os.symlink(str(self.tmp), proc / 'cwd')
        found = worktrees._proc_cwds(str(self.tmp / 'proc'))
        self.assertEqual(found, {str(self.tmp): {'editor'}})


class TestStaged(Base):
    def test_staged_patch_is_saved(self):
        p = self.worktree('staged')
        (Path(p) / 'a.txt').write_text('staged version\n')
        sh('git', 'add', 'a.txt', cwd=p)
        (Path(p) / 'a.txt').write_text('worktree version\n')
        out = backup_mod.backup(p, str(self.backups))
        self.assertTrue(out['ok'], out)
        self.assertIn(b'staged version', (Path(out['dir']) / 'staged.patch').read_bytes())
        self.assertIn(b'worktree version', (Path(out['dir']) / 'tracked.patch').read_bytes())


class TestDockerSafety(Base):
    def ps(self, *rows):
        (self.tmp / 'ps.txt').write_text('\n'.join(json.dumps(r) for r in rows) + '\n')

    def calls(self):
        return [json.loads(line) for line in (self.tmp / 'docker.log').read_text().splitlines()]

    def patch_pgrep(self, out='4242\n'):
        real = docker.run
        docker.run = lambda cmd, **kw: (0, out, '') if cmd[0] == 'pgrep' else real(cmd, **kw)
        self.addCleanup(setattr, docker, 'run', real)

    def test_restarting_container_gets_force_others_do_not(self):
        self.ps({'Names': 'loop', 'Image': 'x', 'State': 'restarting', 'Status': 'Restarting', 'ID': 'l'},
                {'Names': 'done', 'Image': 'x', 'State': 'exited', 'Status': 'Exited', 'ID': 'd'})
        docker.remove_containers(['loop', 'done'], 3, [])
        rm = [c for c in self.calls() if c[0] == 'rm']
        self.assertIn(['rm', '-f', 'loop'], rm)
        self.assertIn(['rm', 'done'], rm)

    def test_images_are_pruned_only_when_asked(self):
        self.ps({'Names': 'done', 'Image': 'x', 'State': 'exited', 'Status': 'Exited', 'ID': 'd'})
        docker.remove_containers(['done'], 3, [])
        self.assertFalse(any(c[:2] == ['image', 'prune'] for c in self.calls()))
        docker.remove_containers(['done'], 3, [], prune_after=True)
        self.assertTrue(any(c[:2] == ['image', 'prune'] for c in self.calls()))

    def test_old_disk_full_error_does_not_look_hung(self):
        log = self.tmp / 'backend.log'
        os.environ['RECLAIM_DOCKER_LOG'] = str(log)
        log.write_text('x no space left on device\n' + 'ok line\n' * 150 + 'backend state changed to stopping\n')
        self.patch_pgrep()
        self.assertFalse(docker.hung_state()['hung'])

    def test_restart_refuses_when_state_changes_during_the_grace_wait(self):
        log = self.tmp / 'backend.log'
        os.environ['RECLAIM_DOCKER_LOG'] = str(log)
        log.write_text('x no space left on device\nbackend state changed to stopping\n')
        answers = iter(['4242\n'])  # the first look sees the process; the re-check after the grace sees none
        killed = []
        real = docker.run

        def fake(cmd, **kw):
            if cmd[0] == 'pgrep':
                return 0, next(answers, ''), ''
            if cmd[0] == 'kill':
                killed.append(cmd)
                return 0, '', ''
            return real(cmd, **kw)
        docker.run = fake
        self.addCleanup(setattr, docker, 'run', real)
        (self.bin / 'docker').write_text('#!/bin/sh\nexit 1\n')  # daemon stays down
        out = docker.restart_hung(wait=1, grace=0)
        self.assertFalse(out['ok'])
        self.assertEqual(killed, [])

    def test_status_without_docker_installed(self):
        (self.bin / 'docker').unlink()
        os.environ['PATH'] = str(self.bin)
        out = docker.status(3, [])
        self.assertFalse(out['installed'])


class TestConfig(Base):
    def test_broken_config_json_falls_back_to_defaults(self):
        data = self.tmp / 'data'
        data.mkdir(exist_ok=True)
        (data / 'config.json').write_text('{not json')
        cfg = common.load_config()
        self.assertEqual(cfg['days'], 3)
        self.assertTrue(cfg['config_problems'])

    def test_wrong_type_value_uses_the_default(self):
        data = self.tmp / 'data'
        data.mkdir(exist_ok=True)
        (data / 'config.json').write_text('{"days": "three", "repos": "x"}')
        cfg = common.load_config()
        self.assertEqual((cfg['days'], cfg['repos']), (3, []))
        self.assertEqual(len(cfg['config_problems']), 2)

    def test_config_set_rejects_bad_json_and_bad_values(self):
        for args in (['config', 'set', 'days', 'abc'], ['config', 'set', 'days', '-1'],
                     ['config', 'set', 'repos', '"notalist"'], ['config', 'set', 'hook', '1']):
            self.assertEqual(cli.main(args), 2, args)

    def test_days_zero_reaches_the_scan(self):
        data = self.tmp / 'data'
        data.mkdir(exist_ok=True)
        (data / 'config.json').write_text(json.dumps({'repos': [str(self.repo)], 'days': 3}))
        seen = {}
        real = worktrees.scan

        def stub(repos, days, **kw):
            seen['days'] = days
            return {'rows': []}
        worktrees.scan = stub
        self.addCleanup(setattr, worktrees, 'scan', real)
        cli.main(['scan', '--days', '0'])
        self.assertEqual(seen['days'], 0)

    def test_atomic_write_leaves_no_temp_file(self):
        common.save_config(dict(common.DEFAULTS))
        names = [p.name for p in (self.tmp / 'data').iterdir()]
        self.assertIn('config.json', names)
        self.assertFalse([n for n in names if n.endswith('.tmp')])


class TestHookDataFolder(Base):
    """The hook is given CLAUDE_PLUGIN_DATA; the CLI (run through Bash) is not. They must agree."""

    def setUp(self):
        super().setUp()
        self.fake_home = self.tmp / 'home'
        self.fake_home.mkdir()
        self.plugin_data = self.tmp / 'plugdata' / 'reclaim-mustafarslan-skills'
        self.plugin_data.mkdir(parents=True)

    def env(self, with_plugin_data):
        env = dict(os.environ, HOME=str(self.fake_home))
        env.pop('RECLAIM_HOME', None)
        env.pop('CLAUDE_PLUGIN_DATA', None)
        if with_plugin_data:
            env['CLAUDE_PLUGIN_DATA'] = str(self.plugin_data)
        return env

    def run_hook(self):
        return subprocess.run(['sh', str(HERE / 'scripts' / 'low-disk.sh')], capture_output=True, text=True,
                              env=self.env(True))

    def test_cli_follows_the_hooks_folder_after_one_hook_run(self):
        self.run_hook()  # first session: the hook records its folder
        (self.plugin_data / 'config.json').write_text('{"warn_gb": 0, "days": 9}')
        out = subprocess.run([sys.executable, '-I', str(HERE / 'scripts' / 'reclaim.py'), 'config', 'show'],
                             capture_output=True, text=True, env=self.env(False))
        self.assertEqual(json.loads(out.stdout)['days'], 9, out.stderr)

    def test_hook_warns_from_the_folder_it_was_given(self):
        (self.plugin_data / 'config.json').write_text('{"warn_gb": 100000}')
        r = self.run_hook()
        self.assertEqual(r.returncode, 0)
        self.assertIn('/reclaim', json.loads(r.stdout)['systemMessage'])
        self.assertEqual(self.run_hook().stdout, '')  # once within the hour

    def test_hook_uses_settings_saved_in_the_fallback_folder(self):
        fb = self.fake_home / '.claude' / 'plugins' / 'data' / 'reclaim'
        fb.mkdir(parents=True)
        (fb / 'config.json').write_text('{"warn_gb": 100000}')
        r = self.run_hook()
        self.assertIn('/reclaim', json.loads(r.stdout)['systemMessage'])

    def test_hook_is_silent_without_config(self):
        r = self.run_hook()
        self.assertEqual((r.returncode, r.stdout), (0, ''))


if __name__ == '__main__':
    unittest.main()
