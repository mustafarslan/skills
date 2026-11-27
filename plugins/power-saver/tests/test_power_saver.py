"""power-saver tests. Fake powercfg, nvidia-smi, schtasks and Win32 calls: nothing on the machine changes.

The parsers run on every OS. The guard and setup scripts run in Windows PowerShell against fake tools (small .cmd
files) on Windows and are skipped elsewhere. Fixtures named *_desktop are real outputs from one Windows 11 desktop
(an AMD CPU, one NVIDIA card and an AMD integrated GPU), with the GPU's UUID replaced.
"""
import base64
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLUGIN = HERE.parent
FIX = HERE / 'fixtures'
sys.path.insert(0, str(PLUGIN / 'scripts'))

import power_saver as ps  # noqa: E402
import winpower as wp  # noqa: E402
from gpu_backends import nvidia, vendor_of  # noqa: E402

WINDOWS = sys.platform == 'win32'
SAVER = '11111111-2222-4333-8444-555555555555'
HIGH = '8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c'
VENDOR_PLAN = '99999999-aaaa-4bbb-8ccc-dddddddddddd'
CFG_BASE = {'gpu_share': 0.7, 'gpu_hot_share_on': 0.6, 'gpu_hot_share_off': 0.78, 'hot_margin_on': 6,
            'hot_margin_off': 2, 'hot_temp_on': 83, 'hot_temp_off': 87, 'hysteresis': 5}


def fix(name):
    return (FIX / name).read_text(encoding='utf-8')


def card(index=0, name='NVIDIA GeForce RTX 5090', default=575.0, lo=400.0, hi=600.0, limit=None, draw=40.0,
         temp=45.0, tlimit=44.0, uuid=None):
    return {'index': index, 'uuid': uuid or f'GPU-00000000-1111-2222-3333-44444444444{index}', 'name': name,
            'limit': default if limit is None else limit, 'default': default, 'min': lo, 'max': hi,
            'draw': draw, 'temp': temp, 'tlimit': tlimit}


CARD_5090 = dict(name='NVIDIA GeForce RTX 5090', default=575.0, lo=400.0, hi=600.0)
CARD_4070 = dict(name='NVIDIA GeForce RTX 4070', default=200.0, lo=100.0, hi=220.0)
CARD_LAPTOP = dict(name='NVIDIA GeForce RTX 4060 Laptop GPU', default=None, lo=None, hi=None, limit=None)


def smi_num(v):
    return '[N/A]' if v is None else f'{v:.2f}'


def render_qh(guid, name, subgroups):
    lines = [f'Power Scheme GUID: {guid}  ({name})']
    for sub, vals in subgroups.items():
        lines.append(f'  Subgroup GUID: {sub}  (subgroup)')
        for s, (ac, dc) in vals.items():
            lines += [f'    Power Setting GUID: {s}  (setting)', '      GUID Alias: X',
                      '      Minimum Possible Setting: 0x00000000', '      Maximum Possible Setting: 0x00000064',
                      f'    Current AC Power Setting Index: 0x{ac:08x}', f'    Current DC Power Setting Index: 0x{dc:08x}',
                      '']
    return '\n'.join(lines) + '\n'


def desktop_processor():
    vals, _ = wp.settings(fix('powercfg_qh_processor_desktop.txt'))
    return {k: (v['ac'], v['dc']) for k, v in vals.items()}


def saver_settings(proc=None, energy=True):
    p = dict(proc if proc is not None else desktop_processor())
    for k in [wp.PERFBOOSTMODE]:
        if k in p:
            p[k] = (0, 0)
    for k in [wp.PROCTHROTTLEMAX] + wp.PROCTHROTTLEMAX_CLASSES:
        if k in p:
            p[k] = (99, 99)
    s = {wp.SUB_PROCESSOR: p, wp.SUB_VIDEO: {wp.VIDEOIDLE: (120, 120)}}
    if energy:
        s[wp.SUB_ENERGYSAVER] = {wp.ESBATTTHRESHOLD: (100, 100)}
    return s


class FakeMachine:
    """powercfg, nvidia-smi, schtasks and powershell as one fake. Every argv is recorded in `calls`."""

    def __init__(self, root, gpus=None, smi=True, tlimit=True, schtasks_ok=True, adapters=None, energy=True,
                 proc=None):
        self.root = Path(root)
        self.calls = []
        proc = desktop_processor() if proc is None else proc
        es = {wp.ESBATTTHRESHOLD: (0, 30)} if energy else None
        base = {wp.SUB_PROCESSOR: proc}
        if es:
            base[wp.SUB_ENERGYSAVER] = es
        self.schemes = {
            wp.BALANCED: {'name': 'Balanced', 'subs': json.loads(json.dumps(base))},
            HIGH: {'name': 'High performance', 'subs': json.loads(json.dumps(base))},
            SAVER: {'name': 'power-saver (unattended work)', 'subs': saver_settings(proc, energy)},
        }
        self.active = wp.BALANCED
        self.gpus = gpus if gpus is not None else [card(**CARD_5090)]
        self.smi = smi
        self.tlimit = tlimit
        self.schtasks_ok = schtasks_ok
        self.adapters = adapters if adapters is not None else [
            {'Name': 'AMD Radeon(TM) Graphics', 'AdapterCompatibility': 'Advanced Micro Devices, Inc.'},
            {'Name': 'NVIDIA GeForce RTX 5090', 'AdapterCompatibility': 'NVIDIA'}]
        self.hot = {}
        self.elevated = []

    def run(self, argv, timeout=None):
        self.calls.append(list(argv))
        tool = re.split(r'[\\/]', argv[0])[-1].lower()      # Windows paths, also when the tests run on a Mac
        a = argv[1:]
        if tool == 'powercfg.exe':
            return self.powercfg(a)
        if tool == 'nvidia-smi.exe':
            return self.nvsmi(a)
        if tool == 'schtasks.exe':
            if not self.schtasks_ok:
                return 1, 'ERROR: Access is denied.\n'
            self.guard()
            return 0, 'SUCCESS: Attempted to run the scheduled task "power-saver".\n'
        if tool == 'powershell.exe':
            if '-EncodedCommand' in a:
                script = base64.b64decode(a[a.index('-EncodedCommand') + 1]).decode('utf-16-le')
                self.elevated.append(script)
                m = re.search(r'-ResultFile "([^"]+)"', script)
                if m:
                    Path(m.group(1)).write_text(json.dumps({'ok': True, 'steps': []}), encoding='utf-8')
                return 0, ''
            return 0, json.dumps(self.adapters)
        return 1, f'unknown tool {tool}'

    def powercfg(self, a):
        if a[0] == '/getactivescheme':
            return 0, f"Power Scheme GUID: {self.active}  ({self.schemes[self.active]['name']})\n"
        if a[0] == '/list':
            rows = [f"Power Scheme GUID: {g}  ({s['name']}){' *' if g == self.active else ''}"
                    for g, s in self.schemes.items()]
            return 0, 'Existing Power Schemes (* Active)\n-----------------------------------\n' + '\n'.join(rows) + '\n'
        if a[0] == '/setactive':
            if a[1] not in self.schemes:
                return 1, 'The power scheme, subgroup or setting specified does not exist.\n'
            self.active = a[1]
            return 0, ''
        if a[0] == '/qh':
            plan = self.active if a[1] == 'SCHEME_CURRENT' else a[1]
            s = self.schemes.get(plan)
            if not s or a[2] not in s['subs']:
                return 1, 'The power scheme, subgroup or setting specified does not exist.\n'
            return 0, render_qh(plan, s['name'], {a[2]: s['subs'][a[2]]})
        return 1, 'unsupported'

    def nvsmi(self, a):
        if not self.smi:
            return 9, 'NVIDIA-SMI has failed'
        q = a[0].split('=', 1)[1].split(',') if a and a[0].startswith('--query-gpu=') else None
        if q == nvidia.FIELDS:
            rows = [', '.join([str(g['index']), g['uuid'], g['name'], smi_num(g['limit']), smi_num(g['default']),
                               smi_num(g['min']), smi_num(g['max']), smi_num(g['draw']), smi_num(g['temp'])])
                    for g in self.gpus]
            return 0, '\n'.join(rows) + '\n'
        if q == nvidia.TLIMIT_FIELDS:
            if not self.tlimit:
                return 2, fix('smi_bad_field.txt').replace('bogus', 'tlimit')
            return 0, '\n'.join(f"{g['uuid']}, {smi_num(g['tlimit'])}" for g in self.gpus) + '\n'
        return 2, 'unexpected nvidia-smi call'

    def guard(self):
        """What the SYSTEM task does, in Python (guard.ps1 itself is tested against fake tools below)."""
        try:
            word = (self.root / 'mode').read_text().strip()
        except OSError:
            word = 'off'
        mode = word if word in ('on', 'off') else 'off'
        cfg = json.loads((self.root / 'config.json').read_text())
        out = []
        for g in self.gpus:
            ok, why = nvidia.adjustable(g)
            row = dict(g, i=g['index'])
            if not ok:
                row.update(result='skipped', why=why)
            else:
                hot = nvidia.is_hot(g, mode, self.hot.get(g['uuid'], False), cfg)
                self.hot[g['uuid']] = hot
                want = nvidia.target(g, mode, hot, cfg)
                row.update(want=want, hot=hot, result='set' if g['limit'] != want else 'ok')
                g['limit'] = float(want)
            out.append(row)
        entry = {'t': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'), 'mode': mode, 'gpus': out,
                 'events': [], 'notes': []}
        with open(self.root / 'guard.log', 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry) + '\n')


class FakeWin:
    def __init__(self, battery=False, classes=(0,) * 8, perf=95.0, cpu=None):
        self.battery = battery
        self.classes = list(classes)
        self.perf = perf
        self.cpu_info = cpu or {'name': 'Example 16-Core Processor', 'vendor': 'AuthenticAMD'}
        self.overlay = '00000000-0000-0000-0000-000000000000'
        self.blanked = 0
        self.woken = 0

    def cpu(self):
        return self.cpu_info

    def core_classes(self):
        return self.classes

    def has_battery(self):
        return self.battery

    def blank_screens(self):
        self.blanked += 1
        return True

    def wake_screens(self):
        self.woken += 1
        return True

    def get_overlay(self):
        return self.overlay

    def set_overlay(self, g):
        self.overlay = g
        return True

    def processor_performance(self, seconds=2.0):
        return self.perf


ALL_CALLS = []          # every argv any test built, for the network check at the end


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='ps-test-'))
        self.root = self.tmp / 'ProgramData' / 'power-saver'
        self.root.mkdir(parents=True)
        self.state = self.tmp / 'state'
        self.env = {'SystemRoot': r'C:\Windows', 'ProgramFiles': str(self.tmp / 'nothing'),
                    'ProgramData': str(self.tmp / 'ProgramData'), 'LOCALAPPDATA': str(self.tmp / 'local')}

    def tearDown(self):
        ALL_CALLS.extend(getattr(self, 'm', None).calls if getattr(self, 'm', None) else [])
        shutil.rmtree(self.tmp, ignore_errors=True)

    def install(self, m=None, win=None, interval=5, detected=None, **cfg):
        self.m = m or FakeMachine(self.root)
        self.win = win or FakeWin()
        c = dict(CFG_BASE, version=1, powercfg=r'C:\Windows\System32\powercfg.exe',
                 nvidia_smi=r'C:\Windows\System32\nvidia-smi.exe' if self.m.smi else '',
                 saver_plan=SAVER, fallback_plan=wp.BALANCED, energy_saver=True, screen_off_minutes=2,
                 interval_minutes=interval, run_rights=True)
        c.update(cfg)
        c['detected'] = detected if detected is not None else {
            'energy_saver': True,
            'gpus': [{'vendor': 'nvidia', 'name': g['name'], 'adjustable': nvidia.adjustable(g)[0]}
                     for g in self.m.gpus] + [{'vendor': 'amd', 'name': 'AMD Radeon(TM) Graphics',
                                              'adjustable': False,
                                              'why': 'GPU: AMD Radeon(TM) Graphics, power limit not supported on '
                                                     'Windows (AMD has no command-line tool for it), skipped'}]}
        (self.root / 'config.json').write_text(json.dumps(c), encoding='utf-8')
        (self.root / 'mode').write_text('off\n')
        self.ctx = ps.Ctx(run=self.m.run, win=self.win, root=self.root, state_dir=self.state,
                          programdata=self.tmp / 'ProgramData', env=self.env, sleep=lambda s: None)
        return self.ctx

    def results(self, out, name):
        return [lv for lv in out['levers'] if lv['lever'] == name]


# ---- parsers ----------------------------------------------------------------------------------

class TestParsers(unittest.TestCase):
    def test_desktop_processor_settings_from_a_real_listing(self):
        vals, subs = wp.settings(fix('powercfg_qh_processor_desktop.txt'))
        self.assertEqual(subs, {wp.SUB_PROCESSOR})
        self.assertEqual(vals[wp.PERFBOOSTMODE], {'ac': 2, 'dc': 2})          # hidden setting, shown by /qh
        self.assertEqual(vals[wp.PROCTHROTTLEMAX], {'ac': 100, 'dc': 100})
        for g in wp.PROCTHROTTLEMAX_CLASSES:
            self.assertIn(g, vals)

    def test_crlf_bom_and_translated_labels_parse_the_same(self):
        text = fix('powercfg_qh_processor_desktop.txt')
        translated = (text.replace('Power Setting GUID', 'GUID des Energieeinstellung')
                      .replace('Current AC Power Setting Index', 'Index der aktuellen Wechselstromeinstellung')
                      .replace('Current DC Power Setting Index', 'Index der aktuellen Gleichstromeinstellung')
                      .replace('Possible Setting Friendly Name', 'Anzeigename'))
        a, _ = wp.settings(text)
        b, _ = wp.settings('\ufeff' + translated.replace('\n', '\r\n'))
        self.assertEqual(a, b)

    def test_energy_saver_subgroup(self):
        vals, subs = wp.settings(fix('powercfg_qh_energysaver.txt'))
        self.assertIn(wp.SUB_ENERGYSAVER, subs)
        self.assertEqual(vals[wp.ESBATTTHRESHOLD], {'ac': 0, 'dc': 30})

    def test_plan_list_and_active(self):
        rows = wp.plans(fix('powercfg_list.txt'))
        self.assertEqual(len(rows), 4)
        self.assertEqual([r['guid'] for r in rows if r['active']], [wp.BALANCED])
        self.assertIn('Away (cool and quiet)', [r['name'] for r in rows])     # parentheses inside a name
        self.assertEqual(wp.active_plan(fix('powercfg_active.txt')), wp.BALANCED)

    def test_nvidia_query_from_a_real_card(self):
        gpus = nvidia.parse_query(fix('smi_query_desktop.csv'))
        self.assertEqual(len(gpus), 1)
        g = gpus[0]
        self.assertEqual((g['default'], g['min'], g['max'], g['limit']), (575.0, 400.0, 600.0, 575.0))
        self.assertEqual(nvidia.parse_tlimit(fix('smi_tlimit_desktop.csv')), {g['uuid']: 41.0})
        self.assertEqual(nvidia.parse_tlimit(fix('smi_bad_field.txt')), {})

    def test_na_and_not_supported_are_none(self):
        for s in ('[N/A]', 'N/A', '[Not Supported]', '', '  ', '[Unknown Error]'):
            self.assertIsNone(nvidia.num(s))
        self.assertEqual(nvidia.num(' 402.50 '), 402.5)

    def test_real_temperature_report_shows_tlimit_and_no_absolute_slowdown(self):
        t = fix('smi_q_temperature_desktop.txt')
        self.assertRegex(t, r'GPU Current T.Limit Temp\s*:\s*\d+ C')
        self.assertRegex(t, r'GPU Target Temperature Specification\s*:\s*N/A')

    def test_efficiency_classes_from_a_processor_buffer(self):
        import struct

        def core(cls):
            body = bytes([0, cls]) + bytes(20) + struct.pack('<H', 1) + bytes(16)
            return struct.pack('<II', 0, 8 + len(body)) + body
        self.assertEqual(wp.efficiency_classes(core(1) * 8 + core(0) * 16), [1] * 8 + [0] * 16)

    def test_vendor_of(self):
        self.assertEqual(vendor_of('AMD Radeon(TM) Graphics', 'Advanced Micro Devices, Inc.'), 'amd')
        self.assertEqual(vendor_of('Intel(R) UHD Graphics 770', 'Intel Corporation'), 'intel')
        self.assertEqual(vendor_of('NVIDIA GeForce RTX 4070', 'NVIDIA'), 'nvidia')


# ---- the GPU arithmetic -----------------------------------------------------------------------

class TestTargets(unittest.TestCase):
    def t(self, spec, mode, hot=False, **cfg):
        return nvidia.target(card(**spec), mode, hot, dict(CFG_BASE, **cfg))

    def test_share_of_each_cards_default_inside_its_range(self):
        self.assertEqual(self.t(CARD_5090, 'on'), 402)       # 575 x 70% = 402.5, above the 400 W minimum
        self.assertEqual(self.t(CARD_5090, 'on', gpu_share=0.69), 400)    # 396.75, clamped up to the minimum
        self.assertEqual(self.t(CARD_4070, 'on'), 140)
        self.assertEqual(self.t(CARD_4070, 'on', gpu_share=0.3), 100)
        self.assertEqual(self.t(CARD_5090, 'off'), 575)

    def test_hot_steps(self):
        self.assertEqual(self.t(CARD_5090, 'on', hot=True), 400)          # 60% = 345, clamped to 400
        self.assertEqual(self.t(CARD_5090, 'off', hot=True), 448)         # 78% of 575
        self.assertEqual(self.t(CARD_4070, 'on', hot=True), 120)

    def test_share_from_config_is_clamped(self):
        self.assertEqual(self.t(CARD_4070, 'on', gpu_share=5), 200)
        self.assertEqual(self.t(CARD_4070, 'on', gpu_share='junk'), 140)

    def test_cards_that_cannot_move(self):
        self.assertFalse(nvidia.adjustable(card(**CARD_LAPTOP))[0])
        self.assertFalse(nvidia.adjustable(card(default=80.0, lo=80.0, hi=80.0))[0])
        self.assertTrue(nvidia.adjustable(card(**CARD_5090))[0])

    def test_tlimit_hysteresis(self):
        cfg = dict(CFG_BASE)
        g = card(tlimit=7.0)
        self.assertFalse(nvidia.is_hot(g, 'on', False, cfg))
        g['tlimit'] = 6.0
        self.assertTrue(nvidia.is_hot(g, 'on', False, cfg))               # at the margin: step down
        g['tlimit'] = 10.0
        self.assertTrue(nvidia.is_hot(g, 'on', True, cfg))                # not yet 5 degrees back
        g['tlimit'] = 11.0
        self.assertFalse(nvidia.is_hot(g, 'on', True, cfg))               # released
        g['tlimit'] = 3.0
        self.assertFalse(nvidia.is_hot(g, 'off', False, cfg))             # off has the smaller margin
        g['tlimit'] = 2.0
        self.assertTrue(nvidia.is_hot(g, 'off', False, cfg))

    def test_without_tlimit_the_fixed_temperatures_apply(self):
        cfg = dict(CFG_BASE)
        g = card(tlimit=None, temp=83.0)
        self.assertTrue(nvidia.is_hot(g, 'on', False, cfg))
        self.assertFalse(nvidia.is_hot(g, 'off', False, cfg))
        g['temp'] = 79.0
        self.assertTrue(nvidia.is_hot(g, 'on', True, cfg))
        g['temp'] = 78.0
        self.assertFalse(nvidia.is_hot(g, 'on', True, cfg))
        self.assertFalse(nvidia.is_hot(card(tlimit=None, temp=None), 'on', False, cfg))

    def test_smi_is_only_taken_from_admin_folders(self):
        with tempfile.TemporaryDirectory() as d:
            env = {'SystemRoot': d, 'ProgramFiles': d}
            self.assertIsNone(nvidia.find_smi(env))
            (Path(d) / 'System32').mkdir()
            (Path(d) / 'System32' / 'nvidia-smi.exe').write_text('')
            self.assertEqual(nvidia.find_smi(env), str(Path(d) / 'System32' / 'nvidia-smi.exe'))


# ---- detect -----------------------------------------------------------------------------------

class TestDetect(Base):
    def detect(self, m, win=None, smi=True):
        self.m = m
        if smi:
            sysdir = self.tmp / 'win' / 'System32'
            sysdir.mkdir(parents=True, exist_ok=True)
            (sysdir / 'nvidia-smi.exe').write_text('')
            self.env['SystemRoot'] = str(self.tmp / 'win')
        else:
            self.env['SystemRoot'] = str(self.tmp / 'empty')      # no nvidia-smi in the system folders
        ctx = ps.Ctx(run=m.run, win=win or FakeWin(), root=self.root, state_dir=self.state,
                     programdata=self.tmp / 'ProgramData', env=self.env, sleep=lambda s: None)
        return ps.detect(ctx)

    def test_desktop_one_nvidia_card_and_an_amd_igpu(self):
        d = self.detect(FakeMachine(self.root))
        nv = [g for g in d['gpus'] if g['vendor'] == 'nvidia']
        self.assertEqual(len(nv), 1)
        self.assertTrue(nv[0]['adjustable'])
        self.assertEqual((nv[0]['min_w'], nv[0]['default_w'], nv[0]['max_w']), (400.0, 575.0, 600.0))
        self.assertTrue(nv[0]['tlimit'])
        self.assertIn('GPU: AMD Radeon(TM) Graphics, power limit not supported on Windows (AMD has no '
                      'command-line tool for it), skipped', d['notes'])
        self.assertFalse(d['cpu']['hybrid'])
        self.assertTrue(d['cpu']['boost_mode_setting'])
        self.assertEqual(d['cpu']['extra_core_classes'], [1, 2])
        self.assertTrue(d['energy_saver'])
        self.assertFalse(d['laptop'])

    def test_two_nvidia_cards(self):
        m = FakeMachine(self.root, gpus=[card(0, **CARD_5090), card(1, **CARD_4070)],
                        adapters=[{'Name': 'NVIDIA GeForce RTX 5090', 'AdapterCompatibility': 'NVIDIA'},
                                  {'Name': 'NVIDIA GeForce RTX 4070', 'AdapterCompatibility': 'NVIDIA'}])
        d = self.detect(m)
        self.assertEqual([g['name'] for g in d['gpus']], ['NVIDIA GeForce RTX 5090', 'NVIDIA GeForce RTX 4070'])
        self.assertIn('2 NVIDIA GPU(s)', [lv for lv in d['levers'] if lv['lever'] == 'gpu'][0]['why'])

    def test_no_gpu_tool_intel_igpu_only(self):
        m = FakeMachine(self.root, smi=False, gpus=[],
                        adapters=[{'Name': 'Intel(R) UHD Graphics 770', 'AdapterCompatibility': 'Intel Corporation'},
                                  {'Name': 'Microsoft Basic Display Adapter', 'AdapterCompatibility': 'Microsoft'}])
        d = self.detect(m, smi=False)
        self.assertEqual([g['vendor'] for g in d['gpus']], ['intel'])
        gpu = [lv for lv in d['levers'] if lv['lever'] == 'gpu'][0]
        self.assertEqual(gpu['result'], 'skipped')
        self.assertIsNone(d['tools']['nvidia_smi'])

    def test_nvidia_adapter_without_nvidia_smi_is_named(self):
        m = FakeMachine(self.root, smi=False, gpus=[],
                        adapters=[{'Name': 'NVIDIA GeForce GTX 1060', 'AdapterCompatibility': 'NVIDIA'}])
        d = self.detect(m, smi=False)
        self.assertIn('nvidia-smi not found', d['notes'][0])

    def test_laptop_gpu_that_refuses_a_limit(self):
        m = FakeMachine(self.root, gpus=[card(**CARD_LAPTOP)], adapters=[])
        d = self.detect(m, win=FakeWin(battery=True))
        self.assertFalse(d['gpus'][0]['adjustable'])
        self.assertTrue(any('not adjustable' in n for n in d['notes']))
        self.assertTrue(d['laptop'])
        self.assertIn('power_mode', [lv['lever'] for lv in d['levers']])

    def test_intel_hybrid(self):
        d = self.detect(FakeMachine(self.root), win=FakeWin(classes=[1] * 8 + [0] * 16,
                                                            cpu={'name': 'Hybrid CPU', 'vendor': 'GenuineIntel'}))
        self.assertTrue(d['cpu']['hybrid'])
        self.assertEqual(d['cpu']['cores'], 24)

    def test_cpu_without_the_boost_mode_setting(self):
        proc = {k: v for k, v in desktop_processor().items() if k != wp.PERFBOOSTMODE}
        d = self.detect(FakeMachine(self.root, proc=proc))
        cpu = [lv for lv in d['levers'] if lv['lever'] == 'cpu'][0]
        self.assertEqual(cpu['result'], 'applies')
        self.assertIn('boost mode setting not on this PC', cpu['why'])

    def test_no_energy_saver(self):
        d = self.detect(FakeMachine(self.root, energy=False))
        self.assertFalse(d['energy_saver'])
        self.assertEqual([lv for lv in d['levers'] if lv['lever'] == 'energy_saver'][0]['result'], 'skipped')

    def test_an_older_hand_made_guard_and_plan_are_found(self):
        old = self.tmp / 'ProgramData' / 'OldGuard'
        old.mkdir(parents=True)
        (old / 'guard.ps1').write_text('& nvidia-smi -pl $want | Out-Null\n')
        m = FakeMachine(self.root)
        away = '22222222-3333-4444-8555-666666666666'
        proc = dict(desktop_processor())
        proc[wp.PROCTHROTTLEMAX] = (99, 100)
        m.schemes[away] = {'name': 'Away', 'subs': {wp.SUB_PROCESSOR: proc}}
        del m.schemes[SAVER]
        d = self.detect(m)
        self.assertEqual(d['predecessors']['scripts'][0]['dir'], str(old))
        self.assertEqual(d['predecessors']['plans'], [{'guid': away, 'name': 'Away', 'max_processor_state': 99}])


# ---- on / off ---------------------------------------------------------------------------------

class TestOnOff(Base):
    def test_on_switches_everything_and_checks_it(self):
        ctx = self.install()
        out = ps.cmd_on(ctx)
        self.assertEqual(out['mode'], 'on')
        self.assertEqual(self.m.active, SAVER)
        self.assertEqual((self.root / 'mode').read_text().strip(), 'on')
        cpu = self.results(out, 'cpu')[0]
        self.assertEqual(cpu['result'], 'applied', cpu)
        self.assertIn('boost mode off', cpu['why'])
        self.assertIn('max processor state 99%', cpu['why'])
        gpus = self.results(out, 'gpu')
        self.assertEqual([g['result'] for g in gpus], ['skipped', 'applied'])
        self.assertIn('AMD', gpus[0]['why'])
        self.assertIn('402 W', gpus[1]['why'])
        self.assertEqual(self.m.gpus[0]['limit'], 402.0)
        self.assertEqual(self.results(out, 'screen')[0]['result'], 'applied')
        self.assertEqual(self.win.blanked, 1)
        self.assertEqual(self.results(out, 'energy_saver')[0]['result'], 'applied')
        for lv in out['levers']:
            self.assertIn(lv['result'], ('applied', 'skipped', 'pending', 'failed'))
        self.assertEqual(ctx.state()['back_plan'], wp.BALANCED)

    def test_keep_screen(self):
        out = ps.cmd_on(self.install(), keep_screen=True)
        self.assertEqual(self.results(out, 'screen')[0], {'lever': 'screen', 'result': 'skipped',
                                                          'why': '--keep-screen'})
        self.assertEqual(self.win.blanked, 0)

    def test_on_twice_never_saves_the_saver_plan_as_the_one_before(self):
        ctx = self.install()
        self.m.active = HIGH
        ps.cmd_on(ctx)
        ps.cmd_on(ctx)
        self.assertEqual(ctx.state()['back_plan'], HIGH)
        out = ps.cmd_off(ctx)
        self.assertEqual(self.m.active, HIGH)
        self.assertEqual(self.results(out, 'cpu')[0]['result'], 'applied')

    def test_off_twice_or_before_on_leaves_the_plan_in_use(self):
        ctx = self.install()
        self.m.active = HIGH
        ps.cmd_off(ctx)
        self.assertEqual(self.m.active, HIGH)
        ps.cmd_on(ctx)
        ps.cmd_off(ctx)
        ps.cmd_off(ctx)
        self.assertEqual(self.m.active, HIGH)
        self.assertNotIn(['/setactive', wp.BALANCED], [c[1:] for c in self.m.calls])

    def test_a_guard_run_already_in_flight_in_the_old_mode_is_not_taken_as_the_result(self):
        ctx = self.install()
        real = self.m.guard
        state = {'n': 0}

        def in_flight():
            state['n'] += 1
            if state['n'] == 1:            # the periodic run that started before the switch, still in 'off'
                with open(self.root / 'guard.log', 'a') as f:
                    f.write(json.dumps({'t': '2026-11-27T12:00:00Z', 'mode': 'off', 'gpus': [
                        dict(self.m.gpus[0], i=0, want=575, result='ok')]}) + chr(10))
                return
            real()
        self.m.guard = in_flight
        out = ps.cmd_on(ctx)
        self.assertEqual(self.results(out, 'gpu')[-1]['result'], 'applied')
        self.assertIn('402 W', self.results(out, 'gpu')[-1]['why'])
        self.assertEqual(state['n'], 2)

    def test_off_goes_back_to_a_vendor_plan(self):
        ctx = self.install()
        self.m.schemes[VENDOR_PLAN] = {'name': 'Vendor Turbo', 'subs': {}}
        self.m.active = VENDOR_PLAN
        ps.cmd_on(ctx)
        out = ps.cmd_off(ctx)
        self.assertEqual(self.m.active, VENDOR_PLAN)
        self.assertIn('Vendor Turbo', self.results(out, 'cpu')[0]['why'])
        self.assertEqual(self.m.gpus[0]['limit'], 575.0)
        self.assertIn('575 W', self.results(out, 'gpu')[-1]['why'])
        self.assertEqual(self.win.woken, 1)
        self.assertEqual((self.root / 'mode').read_text().strip(), 'off')

    def test_the_saved_plan_was_deleted(self):
        ctx = self.install()
        self.m.schemes[VENDOR_PLAN] = {'name': 'Vendor Turbo', 'subs': {}}
        self.m.active = VENDOR_PLAN
        ps.cmd_on(ctx)
        del self.m.schemes[VENDOR_PLAN]
        out = ps.cmd_off(ctx)
        self.assertEqual(self.m.active, wp.BALANCED)
        self.assertIn('was deleted: back to Balanced', out['notes'][0])

    def test_boost_still_on_is_reported(self):
        out = ps.cmd_on(self.install(win=FakeWin(perf=121.3)))
        cpu = self.results(out, 'cpu')[0]
        self.assertEqual(cpu['result'], 'failed')
        self.assertIn('boost still on: this CPU ignores the setting', cpu['why'])

    def test_no_run_rights_means_pending_with_the_interval(self):
        out = ps.cmd_on(self.install(m=FakeMachine(self.root, schtasks_ok=False)))
        self.assertIn('within 5 minutes', self.results(out, 'gpu')[-1]['why'])
        self.assertEqual(self.results(out, 'gpu')[-1]['result'], 'pending')
        out = ps.cmd_on(self.install(m=FakeMachine(self.root, schtasks_ok=False), interval=1))
        self.assertIn('within a minute', self.results(out, 'gpu')[-1]['why'])

    def test_two_gpus_and_a_laptop_card_that_refuses(self):
        gpus = [card(0, **CARD_5090), card(1, **CARD_4070), card(2, **CARD_LAPTOP)]
        out = ps.cmd_on(self.install(m=FakeMachine(self.root, gpus=gpus)))
        g = self.results(out, 'gpu')
        self.assertEqual([x['result'] for x in g], ['skipped', 'applied', 'applied', 'skipped'])
        self.assertIn('140 W', g[2]['why'])
        self.assertIn('not adjustable', g[3]['why'])

    def test_no_nvidia_at_all(self):
        m = FakeMachine(self.root, smi=False, gpus=[], adapters=[])
        out = ps.cmd_on(self.install(m=m, detected={'energy_saver': True, 'gpus': []}))
        self.assertEqual(self.results(out, 'gpu'), [{'lever': 'gpu', 'result': 'skipped',
                                                     'why': 'no NVIDIA GPU (nvidia-smi not found)'}])
        self.assertEqual(self.results(out, 'cpu')[0]['result'], 'applied')

    def test_laptop_power_mode_set_and_put_back(self):
        win = FakeWin(battery=True)
        win.overlay = 'ded574b5-45a0-4f42-8737-46345c09c238'
        ctx = self.install(win=win)
        out = ps.cmd_on(ctx)
        self.assertEqual(win.overlay, wp.OVERLAY_BEST_EFFICIENCY)
        self.assertEqual(self.results(out, 'power_mode')[0]['result'], 'applied')
        ps.cmd_off(ctx)
        self.assertEqual(win.overlay, 'ded574b5-45a0-4f42-8737-46345c09c238')

    def test_energy_saver_off_in_config(self):
        out = ps.cmd_on(self.install(energy_saver=False))
        self.assertEqual(self.results(out, 'energy_saver')[0]['result'], 'skipped')

    def test_not_set_up(self):
        ctx = ps.Ctx(run=FakeMachine(self.root).run, win=FakeWin(), root=self.tmp / 'none', state_dir=self.state,
                     env=self.env)
        with self.assertRaises(ps.NotSetUp):
            ps.cmd_on(ctx)

    def test_mode_file_not_writable(self):
        ctx = self.install()
        ctx.write_mode = lambda w: (False, 'could not write the mode file (Access is denied)')
        out = ps.cmd_on(ctx)
        self.assertEqual(out['levers'][0]['result'], 'failed')
        self.assertEqual(self.m.active, wp.BALANCED)

    def test_reboot_while_on_status_flags_the_reset_card(self):
        ctx = self.install()
        ps.cmd_on(ctx)
        self.m.gpus[0]['limit'] = 575.0            # a reboot puts the card back to its default
        self.m.guard()                             # the startup trigger
        self.assertEqual(self.m.gpus[0]['limit'], 402.0)
        self.assertEqual(ps.cmd_status(ctx)['mode'], 'on')


# ---- status, the mode line, the guard's log ---------------------------------------------------

class TestStatus(Base):
    def write_log(self, entries):
        with open(self.root / 'guard.log', 'w', encoding='utf-8') as f:
            f.write(fix('guard_log_older_format.txt'))               # lines in an older format are ignored
            for e in entries:
                f.write(json.dumps(e) + '\n')

    def test_averages_per_mode_last_hot_and_drift(self):
        now = datetime(2026, 11, 27, 12, 0, tzinfo=timezone.utc)
        ctx = self.install()
        ctx.now = lambda: now

        def t(minutes):
            return (now - timedelta(minutes=minutes)).strftime('%Y-%m-%dT%H:%M:%SZ')
        self.write_log([
            {'t': t(60 * 30), 'mode': 'on', 'gpus': [{'draw': 999}]},                 # older than 24 h
            {'t': t(120), 'mode': 'on', 'gpus': [{'draw': 300}, {'draw': 100}]},
            {'t': t(100), 'mode': 'on', 'gpus': [{'draw': 200}, {'draw': 0}], 'events': ['hot: GPU 0 held at 400 W']},
            {'t': t(40), 'mode': 'off', 'gpus': [{'draw': 500}]},
        ])
        self.m.active = SAVER
        s = ps.cmd_status(ctx)
        self.assertEqual(s['guard']['avg_gpu_watts_24h'], {'on': 300, 'off': 500})
        self.assertEqual(s['guard']['last_hot_step_down']['t'], t(100))
        self.assertIn('plan says saver but mode is off: the guard switches back at its next run', s['drift'])
        self.assertIn("guard hasn't run for 40 minutes", s['drift'])
        self.assertEqual(s['gpus_now'][0]['default'], 575.0)
        self.assertIn('wall meter', s['note'])

    def test_a_guard_older_than_the_plugin_is_flagged(self):
        ctx = self.install()
        stale = 'the installed guard differs from this version of the plugin: run /power-saver:setup again'
        mine = (PLUGIN / 'scripts' / 'guard.ps1').read_bytes().replace(b'\r\n', b'\n')
        (self.root / 'guard.ps1').write_bytes(mine.replace(b'\n', b'\r\n'))      # same text, CRLF
        self.assertNotIn(stale, ps.cmd_status(ctx)['drift'])
        (self.root / 'guard.ps1').write_text('# an older guard\n')
        self.assertIn(stale, ps.cmd_status(ctx)['drift'])

    def test_junk_in_the_mode_file(self):
        ctx = self.install()
        (self.root / 'mode').write_text('on; nvidia-smi -pl 9999\n')
        self.assertEqual(ctx.mode_word(), ('off', False))
        self.assertIn('the mode file holds something other than on/off (the guard treats it as off)',
                      ps.cmd_status(ctx)['drift'])
        self.assertEqual(ps.mode_line(ctx), '')

    def test_mode_line(self):
        ctx = self.install()
        self.assertEqual(ps.mode_line(ctx), '')
        (self.root / 'mode').write_text('on\n')
        self.assertEqual(ps.mode_line(ctx),
                         'power-saver is ON (CPU boost off, GPU at 70%): builds and tests run slower')
        cfg = json.loads((self.root / 'config.json').read_text())
        cfg['detected']['gpus'] = []
        (self.root / 'config.json').write_text(json.dumps(cfg))
        self.assertEqual(ps.mode_line(ctx), 'power-saver is ON (CPU boost off): builds and tests run slower')

    def test_mode_line_hook_is_silent_when_not_installed(self):
        env = dict(os.environ, POWER_SAVER_ROOT=str(self.tmp / 'nothing-here'))
        p = subprocess.run([sys.executable, str(PLUGIN / 'scripts' / 'power_saver.py'), 'mode-line'],
                           capture_output=True, text=True, env=env)
        self.assertEqual((p.returncode, p.stdout), (0, ''))


# ---- setup (the elevated part is only built here, never run) ---------------------------------

class TestSetupCommand(Base):
    def test_install_builds_one_elevated_powershell(self):
        ctx = self.install()
        out = ps.cmd_setup(ctx, share=0.7)
        self.assertTrue(out['ok'], out)
        self.assertTrue(out['users_can_start_task'])
        script = self.m.elevated[0]
        self.assertIn('-Verb RunAs', script)
        self.assertIn('setup.ps1', script)
        self.assertIn('-Action Install', script)
        self.assertIn('-Share 0.70', script)
        self.assertEqual(len(self.m.elevated), 1)

    def test_install_without_run_rights_suggests_the_minute_fallback(self):
        out = ps.cmd_setup(self.install(m=FakeMachine(self.root, schtasks_ok=False)))
        self.assertFalse(out['users_can_start_task'])
        self.assertIn('--every-minute', out['hint'])

    def test_uninstall_while_on_switches_off_first_and_passes_the_plan_back(self):
        ctx = self.install()
        self.m.active = HIGH
        ps.cmd_on(ctx)
        out = ps.cmd_setup(ctx, uninstall=True)
        self.assertEqual(out['switched_off_first']['mode'], 'off')
        self.assertEqual(self.m.active, HIGH)
        self.assertIn('-Action Uninstall', self.m.elevated[0])

    def test_share_out_of_range(self):
        self.assertIn('error', ps.cmd_setup(self.install(), share=2))

    def test_dry_run_changes_nothing(self):
        ctx = self.install()
        out = ps.cmd_setup(ctx, dry_run=True, replace_dir=r'C:\ProgramData\OldGuard',
                           remove_plan='22222222-3333-4444-8555-666666666666')
        self.assertIn('-ReplaceDir "C:\\ProgramData\\OldGuard"', out['would_run'])
        self.assertIn('-RemovePlan 22222222-3333-4444-8555-666666666666', out['would_run'])
        self.assertEqual(self.m.elevated, [])

    def test_quotes_in_a_path_cannot_break_out(self):
        argv, script = ps.elevated_command(self.install(), "-File \"C:\\it's here\\setup.ps1\"")
        self.assertIn("it''s here", script)


# ---- the guard and setup scripts, in real PowerShell against fake tools ----------------------

FAKE_TOOL = r'''
import json, os, sys
state_path = os.environ['FAKE_STATE']
st = json.load(open(state_path))
tool, a = sys.argv[1], sys.argv[2:]
st['calls'].append([tool] + a)
code, out = 0, ''
def num(v): return '[N/A]' if v is None else '%.2f' % v
if tool == 'powercfg':
    if a[0] == '/getactivescheme':
        out = 'Power Scheme GUID: %s  (x)' % st['active']
    elif a[0] == '/setactive':
        st['active'] = a[1]
elif tool == 'nvidia-smi':
    if a[0].startswith('--query-gpu=uuid,temperature.gpu.tlimit'):
        if st.get('tlimit', True):
            out = '\n'.join('%s, %s' % (g['uuid'], num(g['tlimit'])) for g in st['gpus'])
        else:
            code, out = 2, 'Field "temperature.gpu.tlimit" is not a valid field to query.'
    elif a[0].startswith('--query-gpu=index'):
        out = '\n'.join(', '.join([str(g['index']), g['uuid'], g['name'], num(g['limit']), num(g['default']),
                                   num(g['min']), num(g['max']), num(g['draw']), num(g['temp'])]) for g in st['gpus'])
    elif a[0] == '-i':
        g = [g for g in st['gpus'] if g['uuid'] == a[1]][0]
        if g.get('refuse'):
            code, out = 3, 'Changing power management limit is not supported for GPU'
        else:
            g['limit'] = float(a[3])
json.dump(st, open(state_path, 'w'))
if out: print(out)
sys.exit(code)
'''


@unittest.skipUnless(WINDOWS and shutil.which('powershell'), 'Windows PowerShell only')
class TestGuardScript(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='ps-guard-'))
        self.root = self.tmp / 'root'
        self.root.mkdir()
        (self.tmp / 'fake_tool.py').write_text(FAKE_TOOL)
        for tool in ('powercfg', 'nvidia-smi'):
            (self.tmp / f'{tool}.cmd').write_text(f'@"{sys.executable}" "{self.tmp / "fake_tool.py"}" {tool} %*\r\n')
        self.cfg = dict(CFG_BASE, powercfg=str(self.tmp / 'powercfg.cmd'), nvidia_smi=str(self.tmp / 'nvidia-smi.cmd'),
                        saver_plan=SAVER, fallback_plan=wp.BALANCED)

    def tearDown(self):
        ALL_CALLS.extend(getattr(self, 'calls', []))
        shutil.rmtree(self.tmp, ignore_errors=True)

    def guard(self, mode, gpus, active=wp.BALANCED, tlimit=True, cfg=None):
        (self.root / 'config.json').write_text(json.dumps(dict(self.cfg, **(cfg or {}))))
        if mode is not None:
            (self.root / 'mode').write_text(mode)
        st = {'active': active, 'gpus': gpus, 'tlimit': tlimit, 'calls': []}
        (self.tmp / 'state.json').write_text(json.dumps(st))
        env = dict(os.environ, FAKE_STATE=str(self.tmp / 'state.json'))
        p = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File',
                            str(PLUGIN / 'scripts' / 'guard.ps1'), '-Root', str(self.root)],
                           capture_output=True, text=True, env=env, timeout=120)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        st = json.loads((self.tmp / 'state.json').read_text())
        self.calls = st['calls']
        lines = (self.root / 'guard.log').read_text(encoding='utf-8-sig').splitlines()
        return json.loads(lines[-1]), st

    def test_on_sets_each_card_to_its_share_and_the_saver_plan(self):
        gpus = [card(0, **CARD_5090), card(1, **CARD_4070), dict(card(2, **CARD_LAPTOP))]
        entry, st = self.guard('on\n', gpus)
        self.assertEqual(st['active'], SAVER)
        self.assertEqual([g['limit'] for g in st['gpus'][:2]], [402.0, 140.0])
        for g in gpus[:2]:          # the PowerShell arithmetic agrees with the Python one
            self.assertEqual(entry['gpus'][g['index']]['want'], nvidia.target(g, 'on', False, self.cfg))
        self.assertEqual(entry['gpus'][2]['result'], 'skipped')
        self.assertEqual(entry['mode'], 'on')
        self.assertIn('plan: saver plan put back', entry['events'][0])

    def test_off_gives_the_default_back_and_replaces_a_leftover_saver_plan(self):
        entry, st = self.guard('off', [card(0, limit=402.0, **CARD_5090)], active=SAVER)
        self.assertEqual(st['gpus'][0]['limit'], 575.0)
        self.assertEqual(st['active'], wp.BALANCED)

    def test_reboot_while_on(self):
        entry, st = self.guard('on', [card(0, limit=575.0, **CARD_5090)], active=SAVER)
        self.assertEqual(st['gpus'][0]['limit'], 402.0)
        self.assertNotIn(['powercfg', '/setactive', SAVER], st['calls'])     # already the saver plan

    def test_hot_card_steps_down_and_is_released_with_hysteresis(self):
        entry, st = self.guard('on', [card(0, tlimit=5.0, **CARD_5090)])
        self.assertEqual((entry['gpus'][0]['want'], entry['gpus'][0]['hot']), (400, True))
        self.assertTrue(any(e.startswith('hot: GPU 0') for e in entry['events']))
        entry, st = self.guard('on', [card(0, tlimit=9.0, limit=400.0, **CARD_5090)])
        self.assertTrue(entry['gpus'][0]['hot'])                              # 9 < 6 + 5: still held
        entry, st = self.guard('on', [card(0, tlimit=11.0, limit=400.0, **CARD_5090)])
        self.assertFalse(entry['gpus'][0]['hot'])
        self.assertEqual(st['gpus'][0]['limit'], 402.0)

    def test_old_driver_without_tlimit_uses_the_temperature(self):
        entry, st = self.guard('off', [card(0, temp=88.0, tlimit=None, **CARD_5090)], tlimit=False)
        self.assertEqual(entry['gpus'][0]['want'], 448)
        self.assertTrue(entry['gpus'][0]['hot'])

    def test_a_card_that_refuses_the_limit_is_logged_as_failed(self):
        entry, st = self.guard('on', [dict(card(0, **CARD_5090), refuse=True)])
        self.assertEqual(entry['gpus'][0]['result'], 'failed')
        self.assertIn('refused', entry['gpus'][0]['why'])

    def test_junk_in_the_mode_file_counts_as_off_and_is_logged(self):
        entry, st = self.guard('on & nvidia-smi -pl 999 & calc', [card(0, limit=402.0, **CARD_5090)])
        self.assertEqual(entry['mode'], 'off')
        self.assertEqual(st['gpus'][0]['limit'], 575.0)
        self.assertIn('the mode file holds something other than on/off: treated as off', entry['notes'])
        self.assertNotIn('calc', json.dumps(entry))
        entry, st = self.guard(None, [card(0, **CARD_5090)])
        self.assertEqual(entry['mode'], 'off')

    def test_shares_in_config_are_clamped_again(self):
        entry, st = self.guard('on', [card(0, **CARD_4070)], cfg={'gpu_share': 0.01})
        self.assertEqual(entry['gpus'][0]['want'], 100)                      # 30% floor, then the card's minimum

    def test_comma_decimal_locale_does_not_break_parsing(self):
        (self.root / 'config.json').write_text(json.dumps(self.cfg))
        (self.root / 'mode').write_text('on')
        st = {'active': wp.BALANCED, 'gpus': [card(0, **CARD_4070)], 'tlimit': True, 'calls': []}
        (self.tmp / 'state.json').write_text(json.dumps(st))
        env = dict(os.environ, FAKE_STATE=str(self.tmp / 'state.json'))
        cmd = ("[Threading.Thread]::CurrentThread.CurrentCulture = 'de-DE'; "
               f"& '{PLUGIN / 'scripts' / 'guard.ps1'}' -Root '{self.root}'")
        subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-Command', cmd],
                       capture_output=True, text=True, env=env, timeout=120)
        st = json.loads((self.tmp / 'state.json').read_text())
        self.calls = st['calls']
        self.assertEqual(st['gpus'][0]['limit'], 140.0)


@unittest.skipUnless(WINDOWS and shutil.which('powershell'), 'Windows PowerShell only')
class TestSetupScriptDryRun(unittest.TestCase):
    """-DryRun lists the steps and changes nothing; it runs read-only powercfg queries only."""

    def run_setup(self, *extra):
        with tempfile.TemporaryDirectory() as d:
            res = Path(d) / 'r.json'
            p = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File',
                                str(PLUGIN / 'scripts' / 'setup.ps1'), '-DryRun', '-Root', str(Path(d) / 'root'),
                                '-ResultFile', str(res)] + list(extra), capture_output=True, text=True, timeout=120)
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            return json.loads(res.read_text(encoding='utf-8-sig'))

    def test_install_steps(self):
        r = self.run_setup('-Share', '0.70')
        self.assertTrue(r['ok'], r)
        steps = '\n'.join(r['steps'])
        ALL_CALLS.append(r['steps'])
        for want in ('as the saver plan', wp.PERFBOOSTMODE + ' = 0', wp.PROCTHROTTLEMAX + ' = 99',
                     wp.VIDEOIDLE + ' = 120', 'admin-only', 'register the task power-saver',
                     'let Users run the task', 'write config.json'):
            self.assertIn(want, steps)

    def test_a_folder_made_by_someone_else_loses_their_rights(self):
        d = Path(tempfile.mkdtemp(prefix='ps-acl-'))
        root = d / 'root'
        root.mkdir()
        (root / 'guard.ps1').write_text('planted')
        subprocess.run(['icacls', str(root), '/grant', '*S-1-1-0:(OI)(CI)F'], capture_output=True)   # Everyone
        try:
            res = d / 'r.json'
            p = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File',
                                str(PLUGIN / 'scripts' / 'setup.ps1'), '-Action', 'SecureFolder', '-Root', str(root),
                                '-ResultFile', str(res)], capture_output=True, text=True, timeout=120)
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            sddl = json.loads(res.read_text(encoding='utf-8-sig'))['sddl']
            self.assertIn('D:PAI(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;0x1200a9;;;BU)', sddl)
            self.assertNotIn(';WD)', sddl)
            self.assertEqual(sddl.split('D:')[1].count('(A;'), 3)
        finally:
            user = os.environ.get('USERNAME', '')
            subprocess.run(['icacls', str(root), '/grant', f'{user}:(OI)(CI)F', '/T', '/C'], capture_output=True)
            shutil.rmtree(d, ignore_errors=True)

    def test_uninstall_steps(self):
        r = self.run_setup('-Action', 'Uninstall')
        self.assertTrue(r['ok'], r)
        ALL_CALLS.append(r['steps'])
        self.assertIn('unregister the task power-saver', r['steps'][0])


# ---- the open-source rules --------------------------------------------------------------------

BANNED_NETWORK = ['netadapter', 'netsh', 'wlan', 'wi-fi', 'wifi', 'ethernet',
                  '19cbb8fa-5279-450e-9fac-8a3d5fedd0c1',     # Wireless Adapter Settings subgroup
                  'f15576e8-98b7-4186-b944-eafa664402d9']     # Networking connectivity in Standby


class TestZzRules(unittest.TestCase):
    """Runs last (by name), so ALL_CALLS holds every command the other tests built."""

    def test_no_command_touches_network_adapters(self):
        self.assertGreater(len(ALL_CALLS), 50)
        blob = json.dumps(ALL_CALLS).lower()
        for word in BANNED_NETWORK:
            self.assertNotIn(word, blob)

    def test_no_script_mentions_network_adapters(self):
        for f in (PLUGIN / 'scripts').rglob('*'):
            if f.is_file() and f.suffix in ('.py', '.ps1', '.sh', ''):
                text = f.read_text(encoding='utf-8', errors='replace').lower()
                for word in BANNED_NETWORK:
                    self.assertNotIn(word, text, f'{f.name} mentions {word}')

    def test_scripts_hard_code_no_hardware(self):
        for f in list((PLUGIN / 'scripts').rglob('*')) + list((PLUGIN / 'skills').rglob('*')):
            if f.is_file() and f.suffix in ('.py', '.ps1', '.sh', '.md', ''):
                text = f.read_text(encoding='utf-8', errors='replace')
                for word in ('5090', '9950', '575', 'X3D'):
                    self.assertNotIn(word, text, f'{f.name} hard-codes {word}')

    def test_plugin_text_is_generic(self):
        words = ['unreal', 'godot', 'game', 'bubble', 'c:\\users\\musta', 'pcguard', 'pc-away', 'pc-back',
                 'pc-unattended']
        me = Path(__file__).resolve()
        for f in PLUGIN.rglob('*'):
            if not f.is_file() or f.resolve() == me or '__pycache__' in f.parts:
                continue
            text = f.read_text(encoding='utf-8', errors='replace').lower()
            for word in words:
                self.assertNotIn(word, text, f'{f.relative_to(PLUGIN)} mentions {word}')

    def test_powershell_scripts_are_ascii(self):
        for f in (PLUGIN / 'scripts').glob('*.ps1'):
            f.read_bytes().decode('ascii')

    def test_guard_never_looks_tools_up_on_path(self):
        text = (PLUGIN / 'scripts' / 'guard.ps1').read_text()
        self.assertNotIn('Get-Command', text)
        self.assertNotRegex(text, r'&\s*(nvidia-smi|powercfg)\b')


if __name__ == '__main__':
    unittest.main()
