"""GPU backends. v0.1 has one: NVIDIA, through nvidia-smi.

AMD and Intel GPUs have no supported command-line power limit on Windows (AMD's is the ADLX SDK inside a driver
app, Intel's lives in its own app), so they are detected, named and skipped. A backend for them goes here later,
with the same shape as nvidia.py: query(run, tool) -> list of cards, adjustable(card), target(card, mode, hot, cfg).
"""

# Display adapters that are not real GPUs: nothing to save there.
VIRTUAL = ('microsoft', 'remote', 'virtual', 'citrix', 'vmware', 'parsec', 'idd')


def vendor_of(name, maker=''):
    s = f'{maker} {name}'.lower()
    if 'nvidia' in s:
        return 'nvidia'
    if 'advanced micro devices' in s or 'amd' in s.split() or 'radeon' in s or s.startswith('amd'):
        return 'amd'
    if 'intel' in s:
        return 'intel'
    return 'other'


def unsupported_note(vendor, name):
    if vendor == 'amd':
        return f'GPU: {name}, power limit not supported on Windows (AMD has no command-line tool for it), skipped'
    if vendor == 'intel':
        return f'GPU: {name}, power limit not supported on Windows (Intel has no command-line tool for it), skipped'
    if vendor == 'nvidia':
        return f'GPU: {name}, nvidia-smi not found in the system folders, skipped'
    return f'GPU: {name}, no power-limit backend for this adapter, skipped'


def is_virtual(name, maker=''):
    s = f'{maker} {name}'.lower()
    return any(v in s for v in VIRTUAL) and 'nvidia' not in s and 'amd' not in s and 'intel' not in s
