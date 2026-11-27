"""reclaim 0.4 tests: free space per drive, in `df` and in the session-start warning."""
import json
import os
import shutil
import subprocess
import unittest
from collections import namedtuple

from test_reclaim import HERE, WINDOWS, Base  # noqa: F401

import common  # noqa: E402
import plat  # noqa: E402
import reclaim as cli  # noqa: E402

Usage = namedtuple('Usage', 'total used free')


class TestDrives(Base):
    def test_paths_on_one_drive_are_one_row_with_everything_it_holds(self):
        rows = common.drives([('repos', str(self.repo)), ('backups', str(self.tmp / 'not-made-yet' / 'b'))])
        row = [r for r in rows if 'repos' in r['holds']]
        self.assertEqual(len(row), 1, rows)
        self.assertIn('backups', row[0]['holds'])  # a folder not made yet counts on the drive that will hold it
        self.assertEqual(rows[0]['holds'][0], 'system')

    def test_an_unplugged_drive_is_left_out(self):
        gone = 'Q:\\nothing\\here' if WINDOWS else '/nonexistent-volume-reclaim/x'
        real = plat.volume_of
        plat.volume_of = lambda p: None if p == gone else real(p)
        self.addCleanup(setattr, plat, 'volume_of', real)
        rows = common.drives([('repos', gone)])
        self.assertFalse(any('repos' in r['holds'] for r in rows))

    def test_each_drive_is_reported_separately(self):
        vols = {'sys': plat.system_root(), 'ext': str(self.tmp / 'ext')}
        real_vol, real_du = plat.volume_of, plat.disk_usage
        plat.volume_of = lambda p: 'EXT' if str(p).startswith(vols['ext']) else 'SYS'
        plat.disk_usage = lambda v: Usage(1000e9, 0, 5e9) if v == 'EXT' else Usage(2000e9, 0, 900e9)
        self.addCleanup(setattr, plat, 'volume_of', real_vol)
        self.addCleanup(setattr, plat, 'disk_usage', real_du)
        rows = common.drives([('repos', vols['ext'] + '/r'), ("Docker's disk", vols['ext'] + '/d.vhdx')])
        self.assertEqual([(r['volume'], r['free_gb'], r['holds']) for r in rows],
                         [('SYS', 900.0, ['system']), ('EXT', 5.0, ['repos', "Docker's disk"])])

    def test_df_keeps_free_gb_and_adds_drives(self):
        data = self.tmp / 'data'
        data.mkdir(exist_ok=True)
        (data / 'config.json').write_text(json.dumps({'repos': [str(self.repo)]}))
        out = subprocess.run([os.sys.executable, str(HERE / 'scripts' / 'reclaim.py'), 'df'], capture_output=True,
                             text=True, env=dict(os.environ))
        got = json.loads(out.stdout)
        self.assertIsInstance(got['free_gb'], float)
        self.assertTrue(any('repos' in d['holds'] for d in got['drives']))


@unittest.skipUnless(shutil.which('sh'), 'the hook runs through sh (Git Bash on Windows)')
class TestHookNamesTheDrive(Base):
    def test_the_warning_names_the_drive_and_what_it_holds(self):
        data = self.tmp / 'data'
        data.mkdir(exist_ok=True)
        (data / 'config.json').write_text(json.dumps({'warn_gb': 100000, 'repos': [str(self.repo)]}))
        r = subprocess.run(['sh', str(HERE / 'scripts' / 'low-disk.sh')], capture_output=True, text=True)
        msg = json.loads(r.stdout)['systemMessage']
        self.assertIn(plat.volume_of(str(self.repo)), msg)
        self.assertIn('repos', msg)
        self.assertIn('/reclaim', msg)


if __name__ == '__main__':
    unittest.main()
