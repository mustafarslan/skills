"""NVIDIA GPUs through nvidia-smi: each card, its power-limit range, its temperature and its T.Limit headroom.

Pure parsing and arithmetic, plus `query(run, smi)`, which runs nvidia-smi through the caller's runner. The SYSTEM
guard (guard.ps1) does the same arithmetic in PowerShell; tests/test_power_saver.py checks that the two agree.

Reading is unprivileged. Changing a limit (`nvidia-smi -pl`) needs admin, so only the guard does it.
"""
import math
import os

FIELDS = ['index', 'uuid', 'name', 'power.limit', 'power.default_limit', 'power.min_limit', 'power.max_limit',
          'power.draw', 'temperature.gpu']
# Asked for on its own: older drivers reject the whole query when one field is unknown.
TLIMIT_FIELDS = ['uuid', 'temperature.gpu.tlimit']
FORMAT = '--format=csv,noheader,nounits'


def query_args(fields):
    return ['--query-gpu=' + ','.join(fields), FORMAT]


def num(text):
    """A number from nvidia-smi, or None for [N/A], [Not Supported], [Unknown Error] and blanks."""
    s = (text or '').strip()
    if not s or s.startswith('[') or s.upper() in ('N/A', 'NOT SUPPORTED'):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def parse_query(text):
    """Rows of the FIELDS query, as dicts. Lines that are not rows (warnings, blanks) are dropped."""
    gpus = []
    for line in (text or '').replace('\ufeff', '').splitlines():
        parts = [p.strip() for p in line.split(',')]
        if len(parts) != len(FIELDS) or not parts[0].isdigit():
            continue
        gpus.append({
            'index': int(parts[0]), 'uuid': parts[1], 'name': parts[2],
            'limit': num(parts[3]), 'default': num(parts[4]), 'min': num(parts[5]), 'max': num(parts[6]),
            'draw': num(parts[7]), 'temp': num(parts[8]), 'tlimit': None,
        })
    return gpus


def parse_tlimit(text):
    """{uuid: headroom in degrees} from the TLIMIT_FIELDS query."""
    out = {}
    for line in (text or '').replace('\ufeff', '').splitlines():
        parts = [p.strip() for p in line.split(',')]
        if len(parts) == 2 and parts[0].startswith('GPU-'):
            out[parts[0]] = num(parts[1])
    return out


def adjustable(gpu):
    """(True, '') when the card reports a power-limit range it lets you move within, else (False, why)."""
    lo, hi, default = gpu.get('min'), gpu.get('max'), gpu.get('default')
    if lo is None or hi is None or default is None:
        return False, 'power limit not adjustable on this card (nvidia-smi reports no range)'
    if hi <= lo:
        return False, 'power limit fixed on this card (min and max are the same)'
    return True, ''


def is_hot(gpu, mode, was_hot, cfg):
    """Should this card be held lower for heat? Steps down at the margin, releases `hysteresis` degrees later.

    With T.Limit (degrees left before the card slows itself down) the margin is that headroom; without it the
    fixed temperatures from config are used."""
    hyst = cfg.get('hysteresis', 5)
    tl, temp = gpu.get('tlimit'), gpu.get('temp')
    if tl is not None:
        margin = cfg.get('hot_margin_on' if mode == 'on' else 'hot_margin_off', 6 if mode == 'on' else 2)
        return tl < margin + hyst if was_hot else tl <= margin
    if temp is not None:
        limit = cfg.get('hot_temp_on' if mode == 'on' else 'hot_temp_off', 83 if mode == 'on' else 87)
        return temp > limit - hyst if was_hot else temp >= limit
    return False


def clamp_share(value, default):
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    return min(1.0, max(0.3, v))


def target(gpu, mode, hot, cfg):
    """The limit in whole watts the guard sets: a share of the card's default, inside the card's own min and max."""
    default, lo, hi = gpu['default'], gpu['min'], gpu['max']
    if mode == 'on':
        share = clamp_share(cfg.get('gpu_hot_share_on' if hot else 'gpu_share'), 0.6 if hot else 0.7)
    elif hot:
        share = clamp_share(cfg.get('gpu_hot_share_off'), 0.78)
    else:
        share = 1.0
    watts = math.floor(min(hi, max(lo, default * share)))
    if watts < lo:
        watts = math.ceil(lo)
    return int(watts)


def find_smi(environ=None):
    """nvidia-smi in the folders only an administrator can write. A copy elsewhere on PATH is never used."""
    env = os.environ if environ is None else environ
    roots = [os.path.join(env.get('SystemRoot', r'C:\Windows'), 'System32', 'nvidia-smi.exe'),
             os.path.join(env.get('ProgramFiles', r'C:\Program Files'), 'NVIDIA Corporation', 'NVSMI',
                          'nvidia-smi.exe')]
    for p in roots:
        if os.path.isfile(p):
            return p
    return None


def query(run, smi):
    """Every NVIDIA GPU with its range and temperatures. [] when nvidia-smi is missing or fails."""
    if not smi:
        return []
    code, out = run([smi] + query_args(FIELDS))
    if code != 0:
        return []
    gpus = parse_query(out)
    code, out = run([smi] + query_args(TLIMIT_FIELDS))
    tl = parse_tlimit(out) if code == 0 else {}
    for g in gpus:
        g['tlimit'] = tl.get(g['uuid'])
        ok, why = adjustable(g)
        g['adjustable'], g['why'] = ok, why
    return gpus
