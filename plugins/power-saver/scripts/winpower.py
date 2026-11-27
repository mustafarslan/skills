"""Windows pieces: powercfg output parsing (pure), and the few Win32 calls power-saver makes (ctypes, loaded lazily
so the parsers import and test on any OS). No admin needed for anything here.

powercfg's labels are translated on non-English Windows, so parsing keys on GUIDs, indentation and hex values,
never on the English words.
"""
import re
import struct
import sys
import time

GUID = r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}'
GUID_RE = re.compile(GUID)
HEX_RE = re.compile(r'0x([0-9a-fA-F]+)')

BALANCED = '381b4222-f694-41f0-9685-ff5bb260df2e'
BUILTIN_PLANS = {
    BALANCED,
    '8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c',   # High performance
    'a1841308-3541-4fab-bc81-f71556f20b4a',   # Power saver
    'e9a42b02-d5df-448d-aa00-03f14749eb61',   # Ultimate performance
}
SUB_PROCESSOR = '54533251-82be-4824-96c1-47b60b740d00'
PERFBOOSTMODE = 'be337238-0d82-4146-a960-4f3749d470c7'
PROCTHROTTLEMAX = 'bc5038f7-23e0-4960-96da-33abaf5935ec'
PROCTHROTTLEMAX_CLASSES = ['bc5038f7-23e0-4960-96da-33abaf5935ed', 'bc5038f7-23e0-4960-96da-33abaf5935ee']
SUB_VIDEO = '7516b95f-f776-4464-8c53-06167f40cc99'
VIDEOIDLE = '3c0bc021-c8a8-4e07-a973-6b14cbcb2b7e'
SUB_ENERGYSAVER = 'de830923-a562-41af-a086-e3a2c6bad2da'
ESBATTTHRESHOLD = 'e69653ca-cf7f-4f05-aa73-cb833fa90ad4'
# Windows' power-mode overlays (the slider): used on laptops only.
OVERLAY_BEST_EFFICIENCY = '961cc777-2547-4f9d-8174-7d86181b8a7a'
OVERLAY_BALANCED = '00000000-0000-0000-0000-000000000000'


def _clean(text):
    return (text or '').replace('﻿', '').replace('\r', '')


def guids(text):
    return [g.lower() for g in GUID_RE.findall(_clean(text))]


def active_plan(text):
    """`powercfg /getactivescheme` -> the GUID, or None."""
    g = guids(text)
    return g[0] if g else None


def plans(text):
    """`powercfg /list` -> [{guid, name, active}]."""
    out = []
    for line in _clean(text).splitlines():
        m = re.search(rf'({GUID})\s*\((.*)\)\s*(\*)?\s*$', line)
        if m:
            out.append({'guid': m.group(1).lower(), 'name': m.group(2).strip(), 'active': bool(m.group(3))})
    return out


def settings(text):
    """`powercfg /qh SCHEME SUBGROUP` -> ({setting guid: {'ac': int, 'dc': int}}, {subgroup guids}).

    A setting's block starts at its GUID line (indented 4) and its last two hex values are the AC and DC
    indexes, whatever language the labels are in."""
    found, subgroups = {}, set()
    current, hexes = None, []

    def close():
        if current and len(hexes) >= 2:
            found[current] = {'ac': hexes[-2], 'dc': hexes[-1]}

    for line in _clean(text).splitlines():
        indent = len(line) - len(line.lstrip(' '))
        g = GUID_RE.search(line)
        if g and indent == 2:
            close()
            current, hexes = None, []
            subgroups.add(g.group(0).lower())
        elif g and indent == 4:
            close()
            current, hexes = g.group(0).lower(), []
        elif current:
            hexes.extend(int(h, 16) for h in HEX_RE.findall(line))
    close()
    return found, subgroups


def efficiency_classes(buf):
    """EfficiencyClass of each core from a GetLogicalProcessorInformationEx(RelationProcessorCore) buffer.

    Each record is: DWORD Relationship, DWORD Size, then PROCESSOR_RELATIONSHIP (BYTE Flags, BYTE EfficiencyClass,
    ...). Two or more classes means a hybrid CPU (performance and efficiency cores)."""
    classes, off = [], 0
    while off + 10 <= len(buf):
        rel, size = struct.unpack_from('<II', buf, off)
        if size <= 0:
            break
        if rel == 0:
            classes.append(buf[off + 9])
        off += size
    return classes


# ---- Win32 calls (Windows only) --------------------------------------------------------------

class Win:
    """The real machine. Tests pass a fake with the same methods."""

    def cpu(self):
        """{'name', 'vendor'} from the registry."""
        try:
            import winreg
            k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'HARDWARE\DESCRIPTION\System\CentralProcessor\0')
            name = winreg.QueryValueEx(k, 'ProcessorNameString')[0].strip()
            vendor = winreg.QueryValueEx(k, 'VendorIdentifier')[0].strip()
            return {'name': name, 'vendor': vendor}
        except OSError:
            return {'name': 'unknown', 'vendor': 'unknown'}

    def core_classes(self):
        import ctypes
        from ctypes import wintypes
        k = ctypes.WinDLL('kernel32', use_last_error=True)
        n = wintypes.DWORD(0)
        k.GetLogicalProcessorInformationEx(0, None, ctypes.byref(n))
        if not n.value:
            return []
        buf = ctypes.create_string_buffer(n.value)
        if not k.GetLogicalProcessorInformationEx(0, buf, ctypes.byref(n)):
            return []
        return efficiency_classes(buf.raw[:n.value])

    def has_battery(self):
        import ctypes

        class SPS(ctypes.Structure):
            _fields_ = [('ACLineStatus', ctypes.c_ubyte), ('BatteryFlag', ctypes.c_ubyte),
                        ('BatteryLifePercent', ctypes.c_ubyte), ('SystemStatusFlag', ctypes.c_ubyte),
                        ('BatteryLifeTime', ctypes.c_ulong), ('BatteryFullLifeTime', ctypes.c_ulong)]
        s = SPS()
        if not ctypes.WinDLL('kernel32').GetSystemPowerStatus(ctypes.byref(s)):
            return False
        return s.BatteryFlag not in (128, 255)        # 128: no system battery; 255: unknown

    def blank_screens(self):
        """SC_MONITORPOWER 2: screens go dark, stay connected. Posted, not sent: a hung window can't block it."""
        import ctypes
        from ctypes import wintypes
        u = ctypes.WinDLL('user32', use_last_error=True)
        u.PostMessageW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
        return bool(u.PostMessageW(0xFFFF, 0x0112, 0xF170, 2))

    def wake_screens(self):
        """SC_MONITORPOWER -1, a display-required ping and a one-pixel mouse nudge (Windows ignores -1 at times)."""
        import ctypes
        from ctypes import wintypes
        u = ctypes.WinDLL('user32', use_last_error=True)
        u.PostMessageW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
        ok = bool(u.PostMessageW(0xFFFF, 0x0112, 0xF170, -1))
        ctypes.WinDLL('kernel32').SetThreadExecutionState(0x00000002)     # ES_DISPLAY_REQUIRED
        u.mouse_event(0x0001, 1, 0, 0, 0)
        u.mouse_event(0x0001, -1, 0, 0, 0)
        return ok

    def _guid(self, text=None):
        import ctypes
        import uuid

        class G(ctypes.Structure):
            _fields_ = [('b', ctypes.c_ubyte * 16)]
        g = G()
        if text:
            ctypes.memmove(ctypes.byref(g), uuid.UUID(text).bytes_le, 16)
        return g

    def get_overlay(self):
        import ctypes
        import uuid
        g = self._guid()
        try:
            fn = ctypes.WinDLL('powrprof').PowerGetEffectiveOverlayScheme
        except (OSError, AttributeError):
            return None
        if fn(ctypes.byref(g)) != 0:
            return None
        return str(uuid.UUID(bytes_le=bytes(g.b)))

    def set_overlay(self, guid):
        import ctypes
        try:
            fn = ctypes.WinDLL('powrprof').PowerSetActiveOverlayScheme
        except (OSError, AttributeError):
            return False
        return fn(self._guid(guid)) == 0

    def processor_performance(self, seconds=2.0):
        """`% Processor Performance` (_Total) while one core is kept busy. Above 100 means the CPU is boosting.
        PdhAddEnglishCounter, so it works on any display language. None when the counter isn't there."""
        import ctypes
        import subprocess
        from ctypes import wintypes
        try:
            pdh = ctypes.WinDLL('pdh')
        except OSError:
            return None

        class V(ctypes.Structure):
            _fields_ = [('CStatus', wintypes.DWORD), ('pad', wintypes.DWORD), ('doubleValue', ctypes.c_double)]
        q, c = ctypes.c_void_p(), ctypes.c_void_p()
        if pdh.PdhOpenQueryW(None, None, ctypes.byref(q)) != 0:
            return None
        busy = None
        try:
            path = r'\Processor Information(_Total)\% Processor Performance'
            if pdh.PdhAddEnglishCounterW(q, ctypes.c_wchar_p(path), None, ctypes.byref(c)) != 0:
                return None
            busy = subprocess.Popen([sys.executable, '-c', 'import time\nt=time.time()+%f\nwhile time.time()<t: pass'
                                     % (seconds + 1)], creationflags=0x08000000)
            pdh.PdhCollectQueryData(q)
            time.sleep(seconds)
            pdh.PdhCollectQueryData(q)
            v = V()
            if pdh.PdhGetFormattedCounterValue(c, 0x00000200, None, ctypes.byref(v)) != 0:   # PDH_FMT_DOUBLE
                return None
            return round(v.doubleValue, 1)
        finally:
            if busy:
                busy.kill()
            pdh.PdhCloseQuery(q)
