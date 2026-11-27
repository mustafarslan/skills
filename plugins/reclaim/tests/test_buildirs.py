"""reclaim 0.4 tests: build folders inside kept, idle worktrees."""
import os
import subprocess
import unittest
from pathlib import Path

from test_reclaim import WINDOWS, Base, age_tree, sh  # noqa: F401
from test_platform import hold_open

import buildirs  # noqa: E402
import worktrees  # noqa: E402

IGNORE = '.env.local\nnode_modules/\ntarget/\nIntermediate/\n'


class TestBuildDirs(Base):
    def kept_tree(self, name, push=False):
        """An old worktree kept for its unpushed commit, with a gitignored node_modules."""
        p = self.worktree(name, push=push)
        (Path(p) / '.gitignore').write_text(IGNORE)
        self.commit(p, 'ignore build folders')
        (Path(p) / 'node_modules' / 'pkg').mkdir(parents=True)
        (Path(p) / 'node_modules' / 'pkg' / 'index.js').write_bytes(b'x' * 100)
        age_tree(p)
        return p

    def offered(self, cfg=None):
        self.scan()
        out = buildirs.scan(cfg or {}, 3)
        return {(f['tree'], f['folder']): f for f in out['folders']}

    def test_an_idle_kept_tree_offers_its_ignored_build_folder(self):
        p = self.kept_tree('kept')
        row = self.scan()[p]
        self.assertEqual(row['verdict'], 'keep')
        got = self.offered()
        self.assertIn((p, 'node_modules'), got)
        self.assertEqual(got[(p, 'node_modules')]['size'] >= 100, True)
        out = buildirs.remove({}, [got[(p, 'node_modules')]['path']])
        self.assertEqual(out['results'][0]['result'], 'removed', out)
        self.assertFalse((Path(p) / 'node_modules').exists())
        self.assertTrue((Path(p) / 'kept.txt').exists())
        self.assertEqual(sh('git', 'log', '-1', '--format=%s', cwd=p), 'ignore build folders')

    def test_a_folder_git_tracks_or_does_not_ignore_is_never_offered(self):
        p = self.kept_tree('tracked')
        (Path(p) / 'target').mkdir()
        (Path(p) / 'target' / 'keep.me').write_text('tracked on purpose')
        sh('git', 'add', '-f', 'target/keep.me', cwd=p)
        self.commit(p, 'track one file in target')
        (Path(p) / 'dist').mkdir()  # not in .gitignore: untracked work, not a build folder
        (Path(p) / 'dist' / 'mine.txt').write_text('x')
        age_tree(p)
        got = self.offered()
        self.assertNotIn((p, 'target'), got)
        self.assertNotIn((p, 'dist'), got)

    def test_a_tree_kept_because_it_is_in_use_offers_nothing(self):
        p = self.kept_tree('busy')
        if WINDOWS:
            child = hold_open(None, cwd=p)
            self.addCleanup(child.wait)
            self.addCleanup(child.kill)
        else:
            (self.tmp / 'lsof.txt').write_text(f'p123\ncvim\nn{os.path.realpath(p)}\n')
        self.assertEqual(self.offered(), {})

    def test_a_recently_worked_tree_offers_nothing(self):
        p = self.kept_tree('fresh')
        (Path(p) / 'notes.txt').write_text('new work')  # an untracked file written just now
        self.assertEqual(self.offered(), {})

    def test_main_checkouts_only_when_asked(self):
        self.kept_tree('side')  # a repo with a second worktree, so the scan lists the main one
        (self.repo / '.gitignore').write_text(IGNORE)
        self.commit(self.repo, 'ignore')
        sh('git', 'push', '-q', 'origin', 'HEAD:main', cwd=self.repo)
        (self.repo / 'Intermediate').mkdir()
        (self.repo / 'Intermediate' / 'obj').write_bytes(b'x')
        age_tree(self.repo)
        self.assertNotIn((str(self.repo), 'Intermediate'), self.offered())
        self.assertIn((str(self.repo), 'Intermediate'), self.offered({'buildirs_in_main': True}))

    def test_only_offered_folders_go_and_each_is_checked_again(self):
        p = self.kept_tree('recheck')
        got = self.offered()
        self.assertEqual(buildirs.remove({}, [str(Path(p) / 'src')])['results'][0]['result'], 'skipped')
        (Path(p) / 'new-work.txt').write_text('started again')  # the tree is no longer idle
        out = buildirs.remove({}, [got[(p, 'node_modules')]['path']])
        self.assertEqual(out['results'][0]['result'], 'skipped', out)
        self.assertTrue((Path(p) / 'node_modules' / 'pkg' / 'index.js').exists())

    def test_a_link_named_like_a_build_folder_is_not_offered(self):
        p = self.worktree('linked', push=False)
        (Path(p) / '.gitignore').write_text(IGNORE)
        self.commit(p, 'ignore')
        store = self.tmp / 'store'
        store.mkdir()
        (store / 'f').write_text('shared')
        if WINDOWS:
            subprocess.run(['cmd', '/c', 'mklink', '/J', str(Path(p) / 'node_modules'), str(store)], check=True,
                           capture_output=True)
        else:
            os.symlink(str(store), str(Path(p) / 'node_modules'))
        age_tree(p)
        self.assertEqual(self.offered(), {})
        self.assertTrue((store / 'f').exists())

    def test_build_dir_names_adds_your_own(self):
        p = self.kept_tree('extra')
        (Path(p) / '.gitignore').write_text(IGNORE + '.cache-out/\n')
        self.commit(p, 'ignore more')
        (Path(p) / '.cache-out').mkdir()
        (Path(p) / '.cache-out' / 'x').write_text('x')
        age_tree(p)
        self.assertIn((p, '.cache-out'), self.offered({'build_dir_names': ['.cache-out']}))


if __name__ == '__main__':
    unittest.main()
