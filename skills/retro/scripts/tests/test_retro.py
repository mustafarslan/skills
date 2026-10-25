#!/usr/bin/env python3
"""Checks for the /retro scripts. Run: python3 skills/retro/scripts/tests/test_retro.py"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
# The hook lives in the skill's hooks/ folder, beside scripts/.
HOOK = SCRIPTS.parent / 'hooks' / 'retro-reminder.sh'
REPO = 'acme/widgets'
NO_CONFIG = 'retro: no config at {path} \u2014 run /retro --setup (see references/install.md)'


def run(args, env, stdin=''):
    return subprocess.run(args, input=stdin, capture_output=True, text=True, env=env)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name) / 'retro'
        env = {k: v for k, v in os.environ.items() if k != 'RETRO_CONFIG'}
        self.env = dict(env, RETRO_HOME=str(self.home), RETRO_TODAY='2026-10-20', RETRO_SCRIPTS=str(SCRIPTS))
        self.write_config()
        # A throwaway checkout whose folder name gives nothing away, so the git-remote check is what decides.
        self.main = Path(self.tmp.name) / 'checkout'
        self.main.mkdir()
        subprocess.run(['git', 'init', '-q', str(self.main)], check=True)
        subprocess.run(['git', '-C', str(self.main), 'remote', 'add', 'origin',
                        f'git@github.com:{REPO}.git'], check=True)

    def tearDown(self):
        self.tmp.cleanup()

    def state(self, *args, **env):
        return run([sys.executable, str(SCRIPTS / 'state.py'), *args], dict(self.env, **env))

    def write_config(self, **fields):
        self.home.mkdir(parents=True, exist_ok=True)
        (self.home / 'config.json').write_text(json.dumps({'repo': REPO, **fields}))

    def write_state(self, **fields):
        self.home.mkdir(parents=True, exist_ok=True)
        (self.home / 'state.json').write_text(json.dumps(fields))

    def hook(self, cwd=None, source='startup', **env):
        payload = json.dumps({'cwd': cwd or str(self.main), 'source': source, 'hook_event_name': 'SessionStart'})
        return run(['/bin/sh', str(HOOK)], dict(self.env, **env), payload)


class Reminder(Base):
    def test_silent_before_first_run(self):
        self.assertEqual(self.hook().stdout, '')
        self.assertFalse((self.home / 'state.json').exists())

    def test_fires_once_a_day_when_due_and_stamps_first(self):
        self.write_state(last_run='2026-10-05')
        out = self.hook()
        self.assertEqual(out.returncode, 0)
        ctx = json.loads(out.stdout)['hookSpecificOutput']
        self.assertEqual(ctx['hookEventName'], 'SessionStart')
        self.assertIn('15 days', ctx['additionalContext'])
        self.assertEqual(json.loads((self.home / 'state.json').read_text())['last_reminded'], '2026-10-20')
        self.assertEqual(self.hook().stdout, '', 'second session the same day must stay silent')
        self.assertNotEqual(self.hook(RETRO_TODAY='2026-10-21').stdout, '', 'fires again next day')

    def test_silent_when_not_due(self):
        self.write_state(last_run='2026-10-10')
        self.assertEqual(self.hook().stdout, '')

    def test_silent_under_snooze_and_after_skip(self):
        self.write_state(last_run='2026-10-01')
        self.assertEqual(self.state('snooze', '3').returncode, 0)
        self.assertEqual(self.hook().stdout, '')
        self.assertNotEqual(self.hook(RETRO_TODAY='2026-10-23').stdout, '')
        self.state('skip', RETRO_TODAY='2026-10-23')
        self.assertEqual(self.hook(RETRO_TODAY='2026-11-05').stdout, '')
        self.assertNotEqual(self.hook(RETRO_TODAY='2026-11-06').stdout, '')

    def test_silent_on_resume_and_outside_main_repo(self):
        self.write_state(last_run='2026-10-01')
        self.assertEqual(self.hook(source='resume').stdout, '')
        self.assertEqual(self.hook(cwd=str(Path.home() / 'work/widgets-docs')).stdout, '')
        self.assertEqual(self.hook(cwd=self.tmp.name).stdout, '')
        other = Path(self.tmp.name) / 'widgets'  # right folder name, wrong remote
        subprocess.run(['git', 'init', '-q', str(other)], check=True)
        subprocess.run(['git', '-C', str(other), 'remote', 'add', 'origin',
                        'git@github.com:acme/widgets-infra.git'], check=True)
        self.assertEqual(self.hook(cwd=str(other)).stdout, '', 'the remote wins over the folder name')

    def test_a_configured_repo_is_detected_by_its_remote(self):
        self.write_state(last_run='2026-10-01')
        self.assertNotEqual(self.hook().stdout, '', 'remote acme/widgets matches the configured repo')
        self.write_state(last_run='2026-10-01')  # a fired reminder stamps the day; start each check fresh
        self.write_config(repo='other-org/gadgets')
        self.assertEqual(self.hook().stdout, '', 'a checkout of some other repo stays silent')
        self.write_config(repo='other-org/gadgets', remote_regex=r'[/:]acme/widgets(\.git)?$')
        self.assertNotEqual(self.hook().stdout, '', 'remote_regex overrides the one derived from the name')

    def test_folder_name_is_the_fallback_without_a_remote(self):
        self.write_state(last_run='2026-10-01')
        gone = str(Path(self.tmp.name) / 'gone' / 'widgets' / 'wt')  # a removed worktree: no git, no remote
        self.assertNotEqual(self.hook(cwd=gone).stdout, '')
        self.write_state(last_run='2026-10-01')
        self.write_config(repo_folder='gadgets')
        self.assertEqual(self.hook(cwd=gone).stdout, '')

    def test_missing_config_is_silent_and_stamps_nothing(self):
        self.write_state(last_run='2026-10-01')
        (self.home / 'config.json').unlink()
        out = self.hook()
        self.assertEqual((out.returncode, out.stdout, out.stderr), (0, '', ''))
        direct = self.state('remind', '--cwd', str(self.main))
        self.assertEqual((direct.returncode, direct.stdout, direct.stderr), (0, '', ''))
        self.assertIsNone(json.loads((self.home / 'state.json').read_text()).get('last_reminded'))

    def test_broken_config_never_fails_session_start(self):
        self.write_state(last_run='2026-10-01')
        (self.home / 'config.json').write_text('{not json')
        out = self.hook()
        self.assertEqual((out.returncode, out.stdout), (0, ''))

    def test_interval_comes_from_state_then_config(self):
        self.write_state(last_run='2026-10-10')  # 10 days ago
        self.assertEqual(self.hook().stdout, '', 'default interval is 14 days')
        self.write_config(reminder_interval_days=7)
        self.assertNotEqual(self.hook(RETRO_TODAY='2026-10-20').stdout, '', 'config interval of 7 days is due')
        self.write_state(last_run='2026-10-01', interval_days=30)
        self.assertEqual(self.hook().stdout, '', 'state.json interval_days wins over the config')

    def test_fires_without_source_field(self):
        self.write_state(last_run='2026-10-01')
        payload = json.dumps({'cwd': str(self.main)})
        self.assertNotEqual(run(['/bin/sh', str(HOOK)], self.env, payload).stdout, '')

    def test_parallel_tabs_fire_once(self):
        self.write_state(last_run='2026-10-01')
        payload = json.dumps({'cwd': str(self.main), 'source': 'startup'})
        procs = [subprocess.Popen(['/bin/sh', str(HOOK)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  text=True, env=self.env) for _ in range(6)]
        outs = [p.communicate(payload)[0] for p in procs]
        self.assertEqual(sum(1 for o in outs if o.strip()), 1)
        json.loads((self.home / 'state.json').read_text())

    def test_broken_state_never_fails_session_start(self):
        self.home.mkdir(parents=True, exist_ok=True)
        (self.home / 'state.json').write_text('{not json')
        out = self.hook()
        self.assertEqual((out.returncode, out.stdout), (0, ''))


class Record(Base):
    def test_record_arms_and_keeps_history(self):
        run_file = Path(self.tmp.name) / 'run.json'
        run_file.write_text(json.dumps({'run_id': 'r1', 'applied': [{'key': 'a::b', 'signature': {}}],
                                        'rejected': [{'key': 'c::d', 'reason': 'no'}]}))
        self.assertEqual(self.state('record', str(run_file)).returncode, 0)
        st = json.loads(self.state('show').stdout)
        self.assertEqual(st['last_run'], '2026-10-20')
        self.assertEqual(st['applied'][0]['status'], 'applied')
        self.assertEqual(st['rejected'][0]['run_id'], 'r1')
        self.state('mark-reverted', 'r1')
        self.assertEqual(json.loads(self.state('show').stdout)['applied'][0]['status'], 'reverted')


class BackupRestore(Base):
    def setUp(self):
        super().setUp()
        self.work = Path(self.tmp.name) / 'work'
        self.work.mkdir()
        self.edited = self.work / 'CLAUDE.md'
        self.edited.write_text('line one\nline two\nline three\nline four\nline five\n')
        self.created = self.work / 'new-rule.md'
        self.deleted = self.work / 'old-memory.md'
        self.deleted.write_text('stale memory\n')
        self.originals = {p: p.read_bytes() for p in (self.edited, self.deleted)}

    def backup(self, *args):
        out = run([sys.executable, str(SCRIPTS / 'backup.py'), *args], self.env)
        self.assertEqual(out.returncode, 0, out.stderr)

    def restore(self, *args):
        return run([sys.executable, str(SCRIPTS / 'restore.py'), *args], self.env)

    def apply_retro(self):
        paths = [str(self.edited), str(self.created), str(self.deleted)]
        self.backup('r1', *paths)
        self.edited.write_text('line one\nline two RETRO\nline three\nline four\nline five\n')
        self.created.write_text('retro rule\n')
        self.deleted.unlink()
        self.backup('r1', '--after', *paths)

    def test_untouched_since_retro_restores_exactly(self):
        self.apply_retro()
        self.assertEqual(self.restore('r1', '--dry-run').returncode, 0)
        self.assertTrue(self.created.exists(), 'dry run changes nothing')
        out = self.restore('r1')
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        for path, data in self.originals.items():
            self.assertEqual(path.read_bytes(), data)
        self.assertFalse(self.created.exists())

    def test_later_edits_survive_restore(self):
        self.apply_retro()
        self.edited.write_text('line one\nline two RETRO\nline three\nline four\nline five USER\n')
        self.created.write_text('retro rule\nuser addition\n')
        out = self.restore('r1')
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertEqual(self.edited.read_text(),
                         'line one\nline two\nline three\nline four\nline five USER\n')
        self.assertEqual(self.created.read_text(), 'retro rule\nuser addition\n', 'edited new file kept')

    def test_overlapping_later_edit_is_left_alone(self):
        self.apply_retro()
        overlapping = 'line one\nline two RETRO and USER\nline three\nline four\nline five\n'
        self.edited.write_text(overlapping)
        out = self.restore('r1')
        self.assertEqual(out.returncode, 1)
        self.assertEqual(self.edited.read_text(), overlapping)
        self.assertTrue(list((self.home / 'backups' / 'r1' / 'conflicts').rglob('CLAUDE.md')))
        self.assertIn('conflict', out.stdout)

    def test_restore_is_itself_undoable(self):
        self.apply_retro()
        retro_version = self.edited.read_bytes()
        self.restore('r1')
        kept = list((self.home / 'backups' / 'r1' / 'pre-restore').rglob('CLAUDE.md'))
        self.assertEqual(kept[0].read_bytes(), retro_version)

    def test_repo_entries_are_never_touched(self):
        repo_file = self.work / 'repo-rule.md'
        repo_file.write_text('team rule\n')
        self.backup('r2', '--repo', str(self.work), '--pr', 'https://github.com/x/y/pull/9', str(repo_file))
        repo_file.write_text('changed later\n')
        out = self.restore('r2')
        self.assertEqual(repo_file.read_text(), 'changed later\n')
        self.assertIn('pull/9', out.stdout)

    def test_interrupted_apply_is_a_problem_not_a_success(self):
        self.write_state(applied=[{'key': 'k', 'run_id': 'r4', 'status': 'applied'}])
        self.backup('r4', str(self.edited), str(self.deleted))
        self.edited.write_text('line one\nline two RETRO\n')
        self.deleted.unlink()  # No --after: the session died mid-apply.
        out = self.restore('r4')
        self.assertEqual(out.returncode, 1)
        self.assertEqual(self.edited.read_text(), 'line one\nline two RETRO\n', 'unknown edit left alone')
        self.assertEqual(self.deleted.read_bytes(), self.originals[self.deleted], 'missing original back')
        self.assertEqual(json.loads((self.home / 'state.json').read_text())['applied'][0]['status'], 'applied')

    def test_merge_keeps_crlf_line_endings(self):
        crlf = self.work / 'win.md'
        crlf.write_bytes(b'a\r\nb\r\nc\r\nd\r\ne\r\n')
        self.backup('r5', str(crlf))
        crlf.write_bytes(b'a\r\nb RETRO\r\nc\r\nd\r\ne\r\n')
        self.backup('r5', '--after', str(crlf))
        crlf.write_bytes(b'a\r\nb RETRO\r\nc\r\nd\r\ne USER\r\n')
        out = self.restore('r5')
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertEqual(crlf.read_bytes(), b'a\r\nb\r\nc\r\nd\r\ne USER\r\n')

    def test_only_restores_named_paths_and_does_not_mark_state(self):
        self.write_state(applied=[{'key': 'k', 'run_id': 'r1', 'status': 'applied'}])
        self.apply_retro()
        out = self.restore('r1', '--only', str(self.created))
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertFalse(self.created.exists())
        self.assertIn('RETRO', self.edited.read_text(), 'paths not named are untouched')
        self.assertEqual(json.loads((self.home / 'state.json').read_text())['applied'][0]['status'], 'applied')

    def test_only_matching_nothing_refuses(self):
        self.apply_retro()
        out = self.restore('r1', '--only', str(self.work / 'typo.md'))
        self.assertEqual(out.returncode, 2)
        self.assertIn('RETRO', self.edited.read_text())

    def test_unknown_argument_refuses(self):
        self.apply_retro()
        out = self.restore('r1', '--dryrun')
        self.assertEqual(out.returncode, 2)
        self.assertTrue(self.created.exists())

    def test_full_restore_leaves_repo_cards_applied(self):
        self.write_state(applied=[{'key': 'p', 'run_id': 'r1', 'status': 'applied', 'pr': None},
                                  {'key': 'r', 'run_id': 'r1', 'status': 'applied', 'pr': 'https://x/pull/1'}])
        self.apply_retro()
        self.assertEqual(self.restore('r1').returncode, 0)
        statuses = {e['key']: e['status'] for e in json.loads((self.home / 'state.json').read_text())['applied']}
        self.assertEqual(statuses, {'p': 'reverted', 'r': 'applied'})

    def test_second_restore_keeps_first_pre_restore_copy(self):
        self.apply_retro()
        self.restore('r1')
        self.edited.write_text('user rewrote it later\n')
        self.restore('r1')
        copies = sorted((self.home / 'backups' / 'r1' / 'pre-restore').glob('*'))
        self.assertGreaterEqual(len(copies), 1)
        found = [p.read_text() for p in (self.home / 'backups' / 'r1' / 'pre-restore').rglob('CLAUDE.md')]
        self.assertIn('line one\nline two RETRO\nline three\nline four\nline five\n', found)

    def test_first_snapshot_wins(self):
        self.backup('r3', str(self.edited))
        self.edited.write_text('mid-run\n')
        self.backup('r3', str(self.edited))
        manifest = json.loads((self.home / 'backups' / 'r3' / 'manifest.json').read_text())
        copy = self.home / 'backups' / 'r3' / manifest['entries'][0]['backup']
        self.assertEqual(copy.read_bytes(), self.originals[self.edited])


class Extract(Base):
    def test_keeps_only_typed_turns_with_prev_action(self):
        root = Path(self.tmp.name) / 'projects'
        main = root / '-home-me-work-widgets-X'
        infra = root / '-home-me-work-widgets-infra-Y'
        main.mkdir(parents=True)
        infra.mkdir()
        cwd_main = '/home/me/work/widgets/X'
        ts = '2026-10-19T10:00:00.000Z'

        def user(content, **kw):
            return {'type': 'user', 'cwd': cwd_main, 'sessionId': 's1', 'timestamp': ts,
                    'message': {'role': 'user', 'content': content}, **kw}
        lines = [
            {'type': 'assistant', 'cwd': cwd_main, 'message': {'content': [
                {'type': 'text', 'text': 'I decided to add a new table.'},
                {'type': 'tool_use', 'name': 'Edit', 'input': {'file_path': '/x/src/a.py'}}]}},
            user([{'type': 'tool_result', 'content': 'ok'}]),
            user('<task-notification>\n<task-id>1</task-id>'),
            user('<system-reminder>noise</system-reminder>', isMeta=True),
            user('don\'t assume, ask me with AskUserQuestion <pasted_content id="a">secret</pasted_content>'),
            user('<command-message>review</command-message>\n<command-name>/review</command-name>\n'
                 '<command-args>42</command-args>'),
            user('This session is being continued from a previous conversation that ran out'),
            {'type': 'pr-link', 'sessionId': 's1', 'prNumber': 42},
        ]
        (main / 's1.jsonl').write_text(''.join(json.dumps(l) + '\n' for l in lines))
        infra_line = user('infra correction')
        infra_line['cwd'] = '/home/me/work/widgets-infra/Y'
        (infra / 's2.jsonl').write_text(json.dumps(infra_line) + '\n')
        out_file, sess_file = Path(self.tmp.name) / 't.jsonl', Path(self.tmp.name) / 's.jsonl'
        out = run([sys.executable, str(SCRIPTS / 'extract_sessions.py'), '--since', '2026-10-01',
                   '--projects-root', str(root), '--out', str(out_file), '--sessions-out', str(sess_file)],
                  self.env)
        self.assertEqual(out.returncode, 0, out.stderr)
        rows = [json.loads(l) for l in out_file.read_text().splitlines()]
        self.assertEqual([r['text'] for r in rows],
                         ["don't assume, ask me with AskUserQuestion [pasted]", '/review 42'])
        self.assertEqual(rows[0]['prev_action'], {'tool': 'Edit', 'target': '/x/src/a.py'})
        self.assertEqual(rows[0]['prev_text'], 'I decided to add a new table.')
        self.assertEqual(json.loads(sess_file.read_text())['pr_links'], [42])

    def test_sessions_that_ran_retro_are_skipped_even_namespaced(self):
        root = Path(self.tmp.name) / 'projects'
        for name, command in (('-x-a', 'retro'), ('-x-b', 'skills:retro'), ('-x-c', 'review')):
            d = root / name
            d.mkdir(parents=True)
            rec = {'type': 'user', 'cwd': str(self.main), 'sessionId': name, 'timestamp': '2026-10-19T10:00:00.000Z',
                   'message': {'role': 'user', 'content': f'<command-name>/{command}</command-name>'}}
            (d / 's.jsonl').write_text(json.dumps(rec) + '\n')
        out_file = Path(self.tmp.name) / 't.jsonl'
        out = run([sys.executable, str(SCRIPTS / 'extract_sessions.py'), '--since', '2026-10-01',
                   '--projects-root', str(root), '--out', str(out_file)], self.env)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual([json.loads(l)['session'] for l in out_file.read_text().splitlines()], ['-x-c'])

    def test_a_clone_with_any_folder_name_counts_by_its_remote(self):
        root = Path(self.tmp.name) / 'projects'
        clone = Path(self.tmp.name) / 'code' / 'wdg'
        clone.mkdir(parents=True)
        subprocess.run(['git', 'init', '-q', str(clone)], check=True)
        subprocess.run(['git', '-C', str(clone), 'remote', 'add', 'origin',
                        f'https://github.com/{REPO}.git'], check=True)
        other = Path(self.tmp.name) / 'code' / 'side-project'
        other.mkdir(parents=True)
        subprocess.run(['git', 'init', '-q', str(other)], check=True)
        for name, cwd in (('-x-code-wdg', clone), ('-x-code-side-project', other)):
            d = root / name
            d.mkdir(parents=True)
            rec = {'type': 'user', 'cwd': str(cwd), 'sessionId': name, 'timestamp': '2026-10-19T10:00:00.000Z',
                   'message': {'role': 'user', 'content': 'check CI after the push'}}
            (d / 's.jsonl').write_text(json.dumps(rec) + '\n')
        out_file = Path(self.tmp.name) / 't.jsonl'
        out = run([sys.executable, str(SCRIPTS / 'extract_sessions.py'), '--since', '2026-10-01',
                   '--projects-root', str(root), '--out', str(out_file)], self.env)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual([json.loads(l)['session'] for l in out_file.read_text().splitlines()], ['-x-code-wdg'])

    def test_extract_refuses_without_config(self):
        (self.home / 'config.json').unlink()
        out = run([sys.executable, str(SCRIPTS / 'extract_sessions.py'), '--since', '2026-10-01', '--count', 'x',
                   '--projects-root', self.tmp.name], self.env)
        self.assertNotEqual(out.returncode, 0)
        self.assertEqual(out.stderr.strip(), NO_CONFIG.format(path=self.home / 'config.json'))


class Config(Base):
    def load(self, **env):
        return run([sys.executable, str(SCRIPTS / 'config.py'), 'show'], dict(self.env, **env))

    def test_defaults_come_from_the_repo_name(self):
        cfg = json.loads(self.load().stdout)
        self.assertEqual((cfg['repo'], cfg['repo_folder'], cfg['base_branch']), (REPO, 'widgets', 'main'))
        self.assertEqual(cfg['default_checkout'], str(Path.home() / 'code' / 'widgets'))
        self.assertEqual(cfg['remote_regex'], r'[/:]widgets(\.git)?/?$')
        self.assertEqual((cfg['issue_tracker'], cfg['instructions_file'], cfg['instructions_cap_bytes'],
                          cfg['reminder_interval_days']), ('none', 'AGENTS.md', None, 14))

    def test_explicit_fields_and_nulls(self):
        self.write_config(repo_folder='wdg', remote_regex=None, default_checkout='/srv/w', base_branch='trunk',
                          issue_tracker='Linear', issue_team='Core', issue_prefix='CORE',
                          instructions_file='CLAUDE.md', instructions_cap_bytes=8192)
        cfg = json.loads(self.load().stdout)
        self.assertEqual((cfg['repo_folder'], cfg['default_checkout'], cfg['base_branch']), ('wdg', '/srv/w', 'trunk'))
        self.assertEqual((cfg['issue_tracker'], cfg['issue_team'], cfg['issue_prefix']), ('linear', 'Core', 'CORE'))
        self.assertEqual((cfg['instructions_file'], cfg['instructions_cap_bytes']), ('CLAUDE.md', 8192))

    def test_retro_config_names_the_file(self):
        other = Path(self.tmp.name) / 'elsewhere.json'
        other.write_text(json.dumps({'repo': 'other-org/gadgets'}))
        self.assertEqual(json.loads(self.load(RETRO_CONFIG=str(other)).stdout)['repo'], 'other-org/gadgets')

    def test_missing_config_is_one_clear_line(self):
        (self.home / 'config.json').unlink()
        out = self.load()
        self.assertEqual(out.returncode, 1)
        self.assertEqual(out.stderr.strip(), NO_CONFIG.format(path=self.home / 'config.json'))

    def test_bad_values_are_refused_with_one_line(self):
        for fields in ({'repo': 'widgets'}, {'issue_tracker': 'jira'}, {'instructions_cap_bytes': 0},
                       {'reminder_interval_days': 'weekly'}, {'remote_regex': '('}):
            (self.home / 'config.json').write_text(json.dumps({'repo': REPO, **fields}))
            out = self.load()
            self.assertEqual(out.returncode, 1, fields)
            self.assertEqual(len(out.stderr.strip().splitlines()), 1, fields)
            self.assertTrue(out.stderr.startswith('retro: bad config at '), out.stderr)

    def test_scripts_that_need_the_repo_refuse_without_config(self):
        (self.home / 'config.json').unlink()
        for script, args in (('gather_prs.py', ['--since', '2026-10-01', '--out', str(self.home / 'p.jsonl')]),
                             ('window.py', ['--days', '14'])):
            out = run([sys.executable, str(SCRIPTS / script), *args], self.env)
            self.assertNotEqual(out.returncode, 0, script)
            self.assertEqual(out.stderr.strip(), NO_CONFIG.format(path=self.home / 'config.json'), script)

    def test_undo_and_bookkeeping_work_without_config(self):
        (self.home / 'config.json').unlink()
        self.assertEqual(self.state('show').returncode, 0)
        self.assertEqual(self.state('mark-reverted', 'r1', '--personal-only').returncode, 0)


class Window(unittest.TestCase):
    def test_idle_days_do_not_count(self):
        sys.path.insert(0, str(SCRIPTS))
        import datetime as dt
        from window import pick_since
        today = dt.date(2026, 7, 14)
        weekdays = {today - dt.timedelta(days=i) for i in range(60)
                    if (today - dt.timedelta(days=i)).weekday() < 5}
        weekend_work = {dt.date(2026, 7, 11)}  # one Saturday with activity counts
        w = pick_since(weekdays | weekend_work, today, 14, today - dt.timedelta(days=56))
        self.assertEqual(w['active_days'], 14)
        self.assertEqual(w['since'], '2026-06-26')
        self.assertIn('2026-07-12', w['skipped'])
        self.assertNotIn('2026-07-11', w['skipped'])

    def test_stops_at_horizon_when_too_quiet(self):
        sys.path.insert(0, str(SCRIPTS))
        import datetime as dt
        from window import pick_since
        today = dt.date(2026, 7, 14)
        w = pick_since({today}, today, 14, today - dt.timedelta(days=56))
        self.assertEqual((w['active_days'], w['since']), (1, '2026-05-19'))


class GatherDigest(unittest.TestCase):
    def test_rebased_commits_are_not_rework(self):
        sys.path.insert(0, str(SCRIPTS))
        from gather_prs import digest
        pr = {'number': 1, 'title': 't', 'url': 'u', 'mergedAt': 'm', 'baseRefName': 'main',
              'author': {'login': 'a', '__typename': 'User'}, 'labels': {'nodes': []},
              'body': 'Scope: B\n', 'userContentEdits': {'totalCount': 2, 'nodes': [
                  {'editedAt': '2026-10-01T00:00:00Z', 'diff': 'Scope: A\n'}]},
              'commits': {'totalCount': 3, 'nodes': [
                  {'commit': {'messageHeadline': 'Add A', 'authoredDate': '2026-10-01T00:00:00Z'}},
                  {'commit': {'messageHeadline': 'Revert "Add A"', 'authoredDate': '2026-10-03T00:00:00Z'}},
                  {'commit': {'messageHeadline': 'Drop dead guards', 'authoredDate': '2026-10-03T01:00:00Z'}}]},
              'timelineItems': {'nodes': [{'__typename': 'HeadRefForcePushedEvent'},
                                          {'__typename': 'RenamedTitleEvent', 'previousTitle': 'A',
                                           'currentTitle': 'B'}]},
              'reviews': {'nodes': [{'state': 'CHANGES_REQUESTED', 'submittedAt': '2026-10-02T00:00:00Z',
                                     'author': {'login': 'r', '__typename': 'User'}}]},
              'reviewThreads': {'totalCount': 0, 'nodes': []}}
        d = digest(pr)['drift']
        self.assertEqual(d['commits_after_first_review'], 2)
        self.assertEqual(d['rework_commits'], ['Revert "Add A"'], 'plain "Drop …" subjects are not rework')
        self.assertEqual(d['title_renames'], ['A -> B'])
        self.assertEqual((d['body']['added'], d['body']['removed']), (['Scope: B'], ['Scope: A']))


if __name__ == '__main__':
    unittest.main(verbosity=1)
