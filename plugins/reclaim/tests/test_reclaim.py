"""reclaim tests: temporary git repos, fake gh/lsof/docker on PATH. No real worktree or container is touched."""
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE / 'scripts'))

import backup as backup_mod  # noqa: E402
import docker  # noqa: E402
import worktrees  # noqa: E402

OLD = time.time() - 10 * 86400  # ten days ago

FAKE_GH = r'''#!/usr/bin/env python3
import json, os, sys
m = json.load(open(os.environ['FAKE_GH']))
a = sys.argv[1:]
if a[:2] == ['pr', 'list']:
    print(json.dumps(m.get(a[a.index('--head') + 1], [])))
elif a[:2] == ['pr', 'view']:
    key = '#' + a[2]
    if key not in m: sys.exit(1)
    print(json.dumps(m[key]))
'''
# Default: one unrelated process, so lsof "worked". A FAKE_LSOF file replaces that output.
FAKE_LSOF = ('#!/bin/sh\nif [ -f "$FAKE_LSOF" ]; then cat "$FAKE_LSOF"; else printf \'p1\\ncinit\\nn/\\n\'; fi\n'
             '[ -n "${FAKE_LSOF_RC:-}" ] && exit "$FAKE_LSOF_RC"\nexit 0\n')
FAKE_DOCKER = r'''#!/usr/bin/env python3
import json, os, sys
open(os.environ['FAKE_DOCKER_LOG'], 'a').write(json.dumps(sys.argv[1:]) + '\n')
a = sys.argv[1:]
if a[0] == 'ps':
    print(open(os.environ['FAKE_DOCKER_PS']).read(), end='')
elif a[0] == 'inspect':
    print('2020-01-01T00:00:00.000Z|2020-01-01T00:00:00.000Z')
elif a[:2] == ['image', 'prune']:
    print('Total reclaimed space: 1.5GB')
'''


def sh(*cmd, cwd=None, env=None):
    e = dict(os.environ, **(env or {}))
    return subprocess.run(cmd, cwd=cwd, env=e, check=True, capture_output=True, text=True).stdout.strip()


def age_tree(path, when=OLD):
    for root, dirs, files in os.walk(path):
        for name in files + dirs:
            os.utime(os.path.join(root, name), (when, when), follow_symlinks=False)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(os.path.realpath(tempfile.mkdtemp()))
        self.bin = self.tmp / 'bin'
        self.bin.mkdir()
        for name, body in (('gh', FAKE_GH), ('lsof', FAKE_LSOF), ('docker', FAKE_DOCKER)):
            f = self.bin / name
            f.write_text(body)
            f.chmod(0o755)
        self.gh = self.tmp / 'gh.json'
        self.gh.write_text('{}')
        self.env_before = dict(os.environ)
        os.environ.update(
            PATH=f'{self.bin}:{os.environ["PATH"]}', FAKE_GH=str(self.gh),
            FAKE_LSOF=str(self.tmp / 'lsof.txt'), RECLAIM_HOME=str(self.tmp / 'data'),
            FAKE_DOCKER_LOG=str(self.tmp / 'docker.log'),
            FAKE_DOCKER_PS=str(self.tmp / 'ps.txt'),
            GIT_AUTHOR_NAME='t', GIT_AUTHOR_EMAIL='t@t', GIT_COMMITTER_NAME='t', GIT_COMMITTER_EMAIL='t@t',
        )
        self.remote = self.tmp / 'remote.git'
        sh('git', 'init', '-q', '--bare', '-b', 'main', str(self.remote))
        self.repo = self.tmp / 'repo'
        sh('git', 'clone', '-q', str(self.remote), str(self.repo))
        (self.repo / '.gitignore').write_text('.env.local\nnode_modules/\n')
        (self.repo / 'a.txt').write_text('a\n')
        self.commit(self.repo, 'init')
        sh('git', 'push', '-q', 'origin', 'HEAD:main', cwd=self.repo)
        self.backups = self.tmp / 'backups'

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.env_before)
        subprocess.run(['rm', '-rf', str(self.tmp)])

    def commit(self, path, msg, when=OLD):
        stamp = f'@{int(when)} +0000'
        sh('git', 'add', '-A', cwd=path)
        sh('git', 'commit', '-q', '-m', msg, cwd=path,
           env={'GIT_AUTHOR_DATE': stamp, 'GIT_COMMITTER_DATE': stamp})

    def worktree(self, name, push=True, detach=False, added=OLD):
        path = self.tmp / 'wt' / name
        when = {'GIT_COMMITTER_DATE': f'@{int(added)} +0000'}  # the reflog's checkout time
        if detach:
            sh('git', 'worktree', 'add', '-q', '--detach', str(path), cwd=self.repo, env=when)
        else:
            sh('git', 'worktree', 'add', '-q', '-b', name, str(path), cwd=self.repo, env=when)
        (path / f'{name}.txt').write_text(name)
        self.commit(path, name)
        if push and not detach:
            sh('git', 'push', '-q', 'origin', name, cwd=path)
        age_tree(path)
        return str(path)

    def scan(self, days=3, merged=True):
        rows = worktrees.scan([str(self.repo)], days, merged=merged, current=str(self.tmp), with_size=False)
        return {r['path']: r for r in rows['rows']}

    def set_prs(self, mapping):
        self.gh.write_text(json.dumps(mapping))


class TestVerdicts(Base):
    def test_old_clean_branch_is_removed(self):
        p = self.worktree('old-clean')
        self.assertEqual(self.scan()[p]['verdict'], 'remove')

    def test_old_tree_with_a_fresh_new_file_is_kept(self):
        p = self.worktree('edited')
        (Path(p) / 'notes.txt').write_text('x')  # untracked, written just now
        row = self.scan()[p]
        self.assertEqual(row['verdict'], 'keep')
        self.assertIn('edited since the cutoff', row['reasons'])

    def test_fresh_mtime_on_a_clean_tracked_file_does_not_count(self):
        p = self.worktree('touched')
        os.utime(Path(p) / 'a.txt', None)  # a tool rewrote it with the same content
        self.assertEqual(self.scan()[p]['verdict'], 'remove')

    def test_fresh_ignored_file_is_backed_up_not_activity(self):
        p = self.worktree('env-rewritten')
        (Path(p) / '.env.local').write_text('A=1\n')  # gitignored, written just now
        row = self.scan()[p]
        self.assertEqual(row['verdict'], 'backup+remove')
        self.assertEqual(row['ignored'], ['.env.local'])

    def test_worktree_nested_inside_keeps_the_outer_and_survives(self):
        p = self.worktree('outer')
        (Path(p) / '.gitignore').write_text('.env.local\nnode_modules/\ninner/\n')
        sh('git', 'add', '-A', cwd=p)
        self.commit(p, 'ignore inner')
        sh('git', 'push', '-q', 'origin', 'outer', cwd=p)
        inner = Path(p) / 'inner' / 'wt'
        sh('git', 'worktree', 'add', '-q', '-b', 'inner-b', str(inner), cwd=self.repo)
        (inner / 'a.txt').write_text('uncommitted work\n')
        age_tree(p)
        row = self.scan()[p]
        self.assertEqual(row['verdict'], 'keep')
        self.assertIn('holds another checkout: inner/wt', row['reasons'])
        worktrees.remove([p], str(self.backups), backup_mod.backup)
        self.assertEqual((inner / 'a.txt').read_text(), 'uncommitted work\n')

    def test_repo_inside_a_build_named_folder_keeps_the_tree(self):
        p = self.worktree('distrepo')
        sh('git', 'init', '-q', str(Path(p) / 'dist' / 'proj'))
        (Path(p) / 'dist' / 'proj' / 'w.txt').write_text('mine')
        age_tree(p)
        row = self.scan()[p]
        self.assertEqual(row['verdict'], 'keep')
        self.assertIn('holds another checkout: dist/proj', row['reasons'])

    def test_a_foreign_repo_inside_an_ignored_folder_keeps_the_tree(self):
        p = self.worktree('holder')
        (Path(p) / '.gitignore').write_text('.env.local\nnode_modules/\nsecret/\n')
        sh('git', 'init', '-q', str(Path(p) / 'secret'))
        (Path(p) / 'secret' / 'work.txt').write_text('mine')
        sh('git', 'add', '-A', cwd=str(Path(p) / 'secret'))
        sh('git', 'commit', '-q', '-m', 'w', cwd=str(Path(p) / 'secret'))
        sh('git', 'add', '-A', cwd=p)
        self.commit(p, 'ignore secret')
        sh('git', 'push', '-q', 'origin', 'holder', cwd=p)
        age_tree(p)
        row = self.scan()[p]
        self.assertEqual(row['verdict'], 'keep')
        self.assertIn('holds another checkout: secret', row['reasons'])

    def test_non_ascii_file_edited_recently_is_kept(self):
        p = self.worktree('turkce')
        (Path(p) / 'özet-ş.md').write_text('x')  # git C-quotes this without -z
        row = self.scan()[p]
        self.assertEqual(row['verdict'], 'keep')
        self.assertIn('edited since the cutoff', row['reasons'])

    def test_failed_lsof_keeps_everything(self):
        p = self.worktree('no-lsof')
        os.environ['FAKE_LSOF_RC'] = '127'
        (self.tmp / 'lsof.txt').write_text('')
        row = self.scan()[p]
        self.assertEqual(row['verdict'], 'keep')
        self.assertIn('could not list running processes (lsof)', row['reasons'])

    def test_worktree_just_added_on_an_old_commit_is_kept(self):
        p = self.worktree('just-added', push=True)
        sh('git', 'checkout', '-q', '--detach', cwd=p, env={'GIT_COMMITTER_DATE': f'@{int(time.time())} +0000'})
        sh('git', 'checkout', '-q', 'just-added', cwd=p)
        row = self.scan()[p]
        self.assertEqual(row['verdict'], 'keep')
        self.assertIn('newer than the cutoff', row['reasons'])

    def test_main_checkout_is_kept(self):
        self.worktree('side')  # a repo with only its main checkout is not scanned at all
        self.assertEqual(self.scan()[str(self.repo)]['verdict'], 'keep')

    def test_unreachable_detached_head_is_kept(self):
        p = self.worktree('detached', detach=True)
        row = self.scan()[p]
        self.assertEqual(row['verdict'], 'keep')
        self.assertIn('detached HEAD no branch holds', row['reasons'])

    def test_branch_with_unpushed_commits_is_kept(self):
        p = self.worktree('unpushed', push=False)
        row = self.scan()[p]
        self.assertEqual(row['verdict'], 'keep')
        self.assertTrue(any('on no remote' in r for r in row['reasons']))

    def test_open_pr_wins_over_an_older_merged_pr(self):
        p = self.worktree('reused')
        head = sh('git', 'rev-parse', 'HEAD', cwd=p)
        self.set_prs({'reused': [{'number': 1, 'state': 'MERGED', 'headRefOid': head},
                                 {'number': 2, 'state': 'OPEN', 'headRefOid': head}]})
        row = self.scan()[p]
        self.assertEqual(row['verdict'], 'keep')
        self.assertIn('open PR #2', row['reasons'])

    def test_merged_pr_removes_a_new_tree(self):
        p = self.worktree('merged-new')
        age_tree(p, time.time())  # files touched just now, by a checkout or a build
        head = sh('git', 'rev-parse', 'HEAD', cwd=p)
        self.set_prs({'merged-new': [{'number': 5, 'state': 'MERGED', 'headRefOid': head}]})
        row = self.scan(days=30)[p]  # far too new to go by age
        self.assertEqual(row['verdict'], 'remove')
        self.assertEqual(row['merged_prs'], [5])

    def test_merged_tree_with_fresh_uncommitted_edits_is_kept(self):
        p = self.worktree('merged-dirty')
        head = sh('git', 'rev-parse', 'HEAD', cwd=p)
        (Path(p) / 'a.txt').write_text('still working\n')
        self.set_prs({'merged-dirty': [{'number': 7, 'state': 'MERGED', 'headRefOid': head}]})
        row = self.scan()[p]
        self.assertEqual(row['verdict'], 'keep')
        self.assertIn('edited since the cutoff', row['reasons'])

    def test_merged_pr_that_does_not_hold_local_head_is_kept(self):
        p = self.worktree('after-merge')
        merged_head = sh('git', 'rev-parse', 'HEAD', cwd=p)
        (Path(p) / 'later.txt').write_text('later')
        self.commit(p, 'work after the merge')
        age_tree(p)
        self.set_prs({'after-merge': [{'number': 6, 'state': 'MERGED', 'headRefOid': merged_head}]})
        row = self.scan()[p]
        self.assertEqual(row['verdict'], 'keep')
        self.assertEqual(row['merged_prs'], [])

    def test_failed_pr_lookup_keeps_the_tree(self):
        p = self.worktree('gh-down')
        (self.bin / 'gh').write_text('#!/bin/sh\n[ "$1" = auth ] && exit 0\nexit 1\n')  # logged in, lookups fail
        row = self.scan()[p]
        self.assertEqual(row['verdict'], 'keep')
        self.assertIn('PR lookup failed', row['reasons'])

    def test_process_inside_keeps_the_tree(self):
        p = self.worktree('busy')
        (self.tmp / 'lsof.txt').write_text(f'p123\ncvim\nn{os.path.realpath(p)}/sub\n')
        row = self.scan()[p]
        self.assertEqual(row['verdict'], 'keep')
        self.assertIn('in use by vim', row['reasons'])

    def test_dirty_tree_needs_a_backup(self):
        p = self.worktree('dirty')
        (Path(p) / 'a.txt').write_text('changed\n')
        age_tree(p)
        self.assertEqual(self.scan()[p]['verdict'], 'backup+remove')


class TestRemove(Base):
    def calls(self):
        seen = []
        real = worktrees.git

        def spy(path, *args, **kw):
            seen.append(args)
            return real(path, *args, **kw)
        worktrees.git = spy
        self.addCleanup(setattr, worktrees, 'git', real)
        return seen

    def test_clean_remove_never_uses_force(self):
        p = self.worktree('clean')
        self.scan()
        seen = self.calls()
        out = worktrees.remove([p], str(self.backups), backup_mod.backup)
        self.assertEqual(out['results'][0]['result'], 'removed')
        self.assertFalse(os.path.exists(p))
        removes = [a for a in seen if a[:2] == ('worktree', 'remove')]
        self.assertTrue(removes)
        self.assertTrue(all('--force' not in a for a in removes))

    def test_tree_changed_after_scan_is_skipped(self):
        p = self.worktree('drift')
        self.scan()
        f = Path(p) / 'new.txt'
        f.write_text('x')
        os.utime(f, (OLD, OLD))  # old mtime, so only the fingerprint can catch it
        out = worktrees.remove([p], str(self.backups), backup_mod.backup)
        self.assertEqual(out['results'][0]['result'], 'skipped')
        self.assertTrue(os.path.exists(f))

    def test_path_the_scan_kept_is_refused(self):
        p = self.worktree('unpushed2', push=False)
        self.scan()
        out = worktrees.remove([p], str(self.backups), backup_mod.backup)
        self.assertEqual(out['results'][0]['result'], 'skipped')
        self.assertTrue(os.path.exists(p))

    def test_failed_backup_means_no_removal(self):
        p = self.worktree('dirty2')
        (Path(p) / 'a.txt').write_text('changed\n')
        age_tree(p)
        self.scan()
        out = worktrees.remove([p], str(self.backups), lambda *_: {'ok': False, 'error': 'boom'})
        self.assertEqual(out['results'][0]['result'], 'skipped')
        self.assertTrue(os.path.exists(p))

    def test_edit_during_the_backup_stops_the_removal(self):
        p = self.worktree('racy')
        f = Path(p) / 'a.txt'
        f.write_text('first\n')
        age_tree(p)
        self.scan()

        def slow_backup(path, dest):
            r = backup_mod.backup(path, dest)
            f.write_text('second edit, same status line\n')  # lands while the tar would run
            os.utime(f, (OLD + 60, OLD + 60))
            return r
        out = worktrees.remove([p], str(self.backups), slow_backup)
        self.assertEqual(out['results'][0]['result'], 'skipped')
        self.assertEqual(f.read_text(), 'second edit, same status line\n')

    def test_dirty_tree_is_backed_up_then_removed(self):
        p = self.worktree('dirty3')
        (Path(p) / 'a.txt').write_text('changed\n')
        (Path(p) / 'new.txt').write_text('new\n')
        (Path(p) / '.env.local').write_text('SECRET=1\n')
        age_tree(p)
        self.scan()
        out = worktrees.remove([p], str(self.backups), backup_mod.backup)
        r = out['results'][0]
        self.assertEqual(r['result'], 'removed', r)
        d = Path(r['backup'])
        self.assertIn(b'changed', (d / 'tracked.patch').read_bytes())
        with tarfile.open(d / 'untracked.tgz') as t:
            self.assertIn('new.txt', t.getnames())
        with tarfile.open(d / 'ignored.tgz') as t:
            self.assertIn('.env.local', t.getnames())


class TestBackup(Base):
    def test_same_name_twice_gets_two_folders(self):
        p = self.worktree('twice')
        (Path(p) / 'new.txt').write_text('new\n')
        a = backup_mod.backup(p, str(self.backups))
        b = backup_mod.backup(p, str(self.backups))
        self.assertTrue(a['ok'] and b['ok'])
        self.assertNotEqual(a['dir'], b['dir'])

    def test_too_little_space_refuses(self):
        p = self.worktree('nospace')
        (Path(p) / 'new.txt').write_text('new\n')
        real = backup_mod.free_bytes
        backup_mod.free_bytes = lambda _p: 10
        self.addCleanup(setattr, backup_mod, 'free_bytes', real)
        out = backup_mod.backup(p, str(self.backups))
        self.assertFalse(out['ok'])
        self.assertIn('not enough free space', out['error'])

    def test_build_folders_are_not_backed_up(self):
        p = self.worktree('builds')
        (Path(p) / 'node_modules').mkdir()
        (Path(p) / 'node_modules' / 'x.js').write_text('x')
        self.assertEqual(worktrees.ignored_entries(p), [])


class TestDocker(Base):
    def test_rm_never_passes_volume_flag(self):
        (self.tmp / 'ps.txt').write_text(json.dumps(
            {'Names': 'old-db', 'Image': 'postgres:18', 'State': 'exited', 'Status': 'Exited', 'ID': 'abc'}) + '\n')
        out = docker.remove_containers(['old-db'], 3, [])
        self.assertEqual(out['results'][0]['result'], 'removed')
        calls = [json.loads(line) for line in (self.tmp / 'docker.log').read_text().splitlines()]
        rm = [c for c in calls if c[0] == 'rm']
        self.assertEqual(rm, [['rm', 'old-db']])  # no -f: a container started since is refused, not killed
        self.assertFalse(any(c[0] == 'builder' for c in calls))  # rm asked for no build-cache prune
        self.assertFalse(any('-v' in c or '--volumes' in c or c[:1] == ['volume'] for c in calls))

    def test_kept_and_running_containers_are_not_removed(self):
        (self.tmp / 'ps.txt').write_text('\n'.join(json.dumps(c) for c in [
            {'Names': 'local-db', 'Image': 'postgres', 'State': 'exited', 'Status': 'Exited', 'ID': 'a'},
            {'Names': 'web', 'Image': 'x', 'State': 'running', 'Status': 'Up', 'ID': 'b'},
        ]) + '\n')
        out = docker.remove_containers(['local-db', 'web'], 3, ['local-*'])
        self.assertEqual([r['result'] for r in out['results']], ['skipped', 'skipped'])

    def test_paused_container_is_never_stale(self):
        (self.tmp / 'ps.txt').write_text(json.dumps(
            {'Names': 'paused-svc', 'Image': 'x', 'State': 'paused', 'Status': 'Paused', 'ID': 'p'}) + '\n')
        self.assertEqual(docker.stale_containers(3, []), [])

    def test_hung_needs_process_stopping_state_and_full_disk(self):
        log = self.tmp / 'backend.log'
        os.environ['RECLAIM_DOCKER_LOG'] = str(log)
        log.write_text('x no space left on device\nbackend state changed to stopping\n')
        real = docker.run
        docker.run = lambda cmd, **kw: (0, '4242\n', '') if cmd[0] == 'pgrep' else real(cmd, **kw)
        self.addCleanup(setattr, docker, 'run', real)
        self.assertTrue(docker.hung_state()['hung'])
        log.write_text('backend state changed to stopping\n')  # no full disk in the log
        self.assertFalse(docker.hung_state()['hung'])


class TestHook(Base):
    def run_hook(self):
        return subprocess.run(['sh', str(HERE / 'scripts' / 'low-disk.sh')], capture_output=True, text=True)

    def test_silent_without_config(self):
        r = self.run_hook()
        self.assertEqual((r.returncode, r.stdout), (0, ''))

    def test_silent_with_enough_space(self):
        data = self.tmp / 'data'
        data.mkdir(exist_ok=True)
        (data / 'config.json').write_text('{"warn_gb": 0}')
        r = self.run_hook()
        self.assertEqual((r.returncode, r.stdout), (0, ''))

    def test_hook_false_turns_the_warning_off(self):
        data = self.tmp / 'data'
        data.mkdir(exist_ok=True)
        (data / 'config.json').write_text('{"warn_gb": 100000, "hook": false}')
        r = self.run_hook()
        self.assertEqual((r.returncode, r.stdout), (0, ''))

    def test_warns_below_threshold(self):
        data = self.tmp / 'data'
        data.mkdir(exist_ok=True)
        (data / 'config.json').write_text('{"warn_gb": 100000}')
        r = self.run_hook()
        self.assertEqual(r.returncode, 0)
        out = json.loads(r.stdout)
        self.assertIn('/reclaim', out['systemMessage'])
        self.assertEqual(out['hookSpecificOutput']['hookEventName'], 'SessionStart')
        self.assertEqual(self.run_hook().stdout, '')  # not again within the hour


if __name__ == '__main__':
    unittest.main()
