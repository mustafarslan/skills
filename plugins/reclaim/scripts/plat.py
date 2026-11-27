"""One place for each difference between macOS (and Linux) and Windows.

On macOS and Linux every function here computes exactly what reclaim 0.3 computed in place: the same
`du`, `tar` and `lsof` calls, the same '/' path tests. Windows gets its own branch under `WINDOWS`, built
on the Win32 API through ctypes (no admin, nothing installed), never on Git Bash's Unix tools.
"""
import os
import shutil
import stat
import subprocess
import sys

WINDOWS = os.name == 'nt'
SEPS = '\\/' if WINDOWS else '/'
CREATE_NO_WINDOW = 0x08000000


# ---------- paths ----------

def strip_sep(p):
    """p without a trailing separator (POSIX: p.rstrip('/'), as before)."""
    return p.rstrip(SEPS)


def base_name(p):
    return os.path.basename(strip_sep(p))


def native(p):
    """A path as this OS writes it. git prints C:/x/y on Windows; os.path gives C:\\x\\y."""
    return os.path.normpath(p) if WINDOWS and p else p


def rel(p, start):
    """relpath with '/' separators, as git and the reports use them."""
    r = os.path.relpath(p, start)
    return r.replace('\\', '/') if WINDOWS else r


def depth(p):
    """Separator count, for depth limits (POSIX: p.count('/'), as before)."""
    return p.count('/') + (p.count('\\') if WINDOWS else 0)


def same_or_inside(child, parent):
    """True when child is parent or lies inside it."""
    if not WINDOWS:
        return child == parent or child.startswith(parent + '/')
    c = os.path.normcase(os.path.normpath(child))
    p = os.path.normcase(os.path.normpath(parent))
    try:
        return os.path.commonpath([c, p]) == p
    except ValueError:  # different drives
        return False


def long_path(p):
    """Windows: the \\\\?\\ form, so paths past 260 characters still open. POSIX: p."""
    if not WINDOWS:
        return p
    p = os.path.abspath(p)
    if p.startswith('\\\\?\\'):
        return p
    if p.startswith('\\\\'):
        return '\\\\?\\UNC\\' + p[2:]
    return '\\\\?\\' + p


def short_path(p):
    """Undo long_path for reports."""
    if WINDOWS and p.startswith('\\\\?\\UNC\\'):
        return '\\\\' + p[8:]
    if WINDOWS and p.startswith('\\\\?\\'):
        return p[4:]
    return p


def is_link_or_junction(path):
    """A symlink, or on Windows any name-surrogate reparse point (junction, directory symlink). Walks never
    enter these and deletes remove only the link: what it points to belongs to someone else."""
    try:
        st = os.lstat(path)
    except OSError:
        return False
    if stat.S_ISLNK(st.st_mode):
        return True
    if WINDOWS:
        attrs = getattr(st, 'st_file_attributes', 0)
        tag = getattr(st, 'st_reparse_tag', 0)
        return bool(attrs & 0x400) and bool(tag & 0x20000000)  # REPARSE_POINT and a name surrogate
    return False


def walk(top):
    """os.walk that never enters a junction. POSIX: os.walk exactly (it already skips symlinked folders)."""
    for root, dirs, files in os.walk(top):
        if WINDOWS:
            dirs[:] = [d for d in dirs if not is_link_or_junction(os.path.join(root, d))]
        yield root, dirs, files


# ---------- programs ----------

def which(name):
    """Full path of a program, or None. Windows: only absolute PATH entries, never the current folder
    (Windows searches it first, so a planted git.exe there would run), and only files Windows can start."""
    if not WINDOWS:
        return shutil.which(name)
    if os.path.isabs(name):
        return name if os.path.isfile(name) else None
    exts = [''] if os.path.splitext(name)[1] else \
        [e.lower() for e in os.environ.get('PATHEXT', '.COM;.EXE;.BAT;.CMD').split(';') if e]
    for d in os.environ.get('PATH', '').split(os.pathsep):
        d = d.strip().strip('"')
        if not d or not os.path.isabs(d):
            continue
        for e in exts:
            f = os.path.join(d, name + e)
            if os.path.isfile(f):
                return f
    return None


def exe(name):
    """What to start for a program: its full path on Windows (so the current folder is never searched), the
    bare name elsewhere, as before."""
    return (which(name) or name) if WINDOWS else name


_BATCH_SPECIAL = set(' \t&|<>^(),;=')


def _batch_line(argv):
    """A command line for a .cmd or .bat file. cmd.exe reads | & < > ^ in its arguments as its own
    operators unless they sit inside double quotes, so every such argument is quoted. An argument cmd.exe
    can't take safely (a quote, a %, a line break) is refused: None."""
    out = []
    for i, a in enumerate(argv):
        a = str(a)
        if any(c in a for c in '"%\r\n\0') or (i and '!' in a):
            return None
        out.append(f'"{a}"' if i == 0 or not a or any(c in _BATCH_SPECIAL for c in a) else a)
    return ' '.join(out)


def run(cmd, cwd=None, check=False, timeout=120, env=None):
    """Run a command; return (returncode, stdout, stderr). Never raises for a missing binary."""
    if WINDOWS:
        return _run_windows(cmd, cwd, check, timeout, env)
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env)
    except FileNotFoundError as exc:
        return 127, '', str(exc)
    except subprocess.TimeoutExpired:
        return 124, '', f'timed out after {timeout}s: {" ".join(cmd)}'
    if check and p.returncode != 0:
        raise RuntimeError(f'{" ".join(cmd)} failed: {p.stderr.strip()}')
    return p.returncode, p.stdout, p.stderr


def _run_windows(cmd, cwd, check, timeout, env, raw=False):
    exe = which(cmd[0])
    if not exe:
        return 127, b'' if raw else '', f'{cmd[0]}: not found on PATH'
    argv = [exe] + [str(a) for a in cmd[1:]]
    line = argv
    if exe.lower().endswith(('.cmd', '.bat')):
        line = _batch_line(argv)
        if line is None:
            return 127, b'' if raw else '', f'refused: an argument {cmd[0]} (a batch file) cannot take safely'
    kw = {} if raw else {'encoding': 'utf-8', 'errors': 'replace'}
    try:
        p = subprocess.run(line, cwd=cwd, capture_output=True, timeout=timeout, env=env, stdin=subprocess.DEVNULL,
                           creationflags=CREATE_NO_WINDOW, **kw)
    except subprocess.TimeoutExpired:
        return 124, b'' if raw else '', f'timed out after {timeout}s: {" ".join(argv)}'
    except OSError as exc:
        return 127, b'' if raw else '', str(exc)
    if check and p.returncode != 0:
        raise RuntimeError(f'{" ".join(argv)} failed: {p.stderr if raw else p.stderr.strip()}')
    return p.returncode, p.stdout, p.stderr


def run_raw(cmd, timeout=60, env=None):
    """run() that returns stdout as bytes (wsl.exe prints UTF-16)."""
    if WINDOWS:
        rc, out, err = _run_windows(cmd, None, False, timeout, env, raw=True)
        return rc, out, err.decode('utf-8', 'replace') if isinstance(err, bytes) else err
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=timeout, env=env)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, b'', str(exc)
    return p.returncode, p.stdout, p.stderr.decode('utf-8', 'replace')


# ---------- disk ----------

def free_bytes(path='/'):
    return shutil.disk_usage(path).free


def disk_usage(path):
    return shutil.disk_usage(path)


def system_root():
    """'/' on macOS and Linux; on Windows the drive that holds the home folder."""
    if not WINDOWS:
        return '/'
    return os.path.splitdrive(os.path.expanduser('~'))[0] + '\\'


def volume_of(path):
    """The volume (mount point, or drive) a path lives on, from its nearest existing folder. None when even
    that can't be found (an unplugged drive)."""
    p = os.path.abspath(os.path.expanduser(str(path)))
    while not os.path.exists(p):
        parent = os.path.dirname(p)
        if parent == p:
            return None
        p = parent
    if WINDOWS:
        try:
            import ctypes
            buf = ctypes.create_unicode_buffer(1024)
            if ctypes.WinDLL('kernel32').GetVolumePathNameW(ctypes.c_wchar_p(p), buf, 1024):
                return buf.value
        except (OSError, AttributeError):
            pass
        drive = os.path.splitdrive(p)[0]
        return drive + '\\' if drive else None
    p = os.path.realpath(p)
    while not os.path.ismount(p):
        p = os.path.dirname(p)
    return p


def dir_size(path):
    """Bytes a folder holds. POSIX: `du -sk` (fast, the real block count), as before. Windows: a walk that
    never follows a link or junction (what they point to is counted where it lives)."""
    if not WINDOWS:
        rc, out, _ = run(['du', '-sk', str(path)], timeout=600)
        return int(out.split()[0]) * 1024 if rc == 0 and out else 0
    total, stack = 0, [long_path(str(path))]
    while stack:
        d = stack.pop()
        try:
            with os.scandir(d) as it:
                for e in it:
                    try:
                        if e.is_symlink() or is_link_or_junction(e.path):
                            continue
                        if e.is_dir(follow_symlinks=False):
                            stack.append(e.path)
                        else:
                            total += e.stat(follow_symlinks=False).st_size
                    except OSError:
                        continue
        except OSError:
            continue
    return total


def allocated_bytes(path):
    """Bytes a file really takes on disk (less than its size when it is sparse), or None."""
    if WINDOWS:
        try:
            import ctypes
            from ctypes import wintypes
            k = ctypes.WinDLL('kernel32', use_last_error=True)
            k.GetCompressedFileSizeW.restype = wintypes.DWORD
            k.GetCompressedFileSizeW.argtypes = (wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD))
            high = wintypes.DWORD(0)
            low = k.GetCompressedFileSizeW(long_path(path), ctypes.byref(high))
            if low == 0xFFFFFFFF and ctypes.get_last_error():
                return None
            return (high.value << 32) | low
        except (OSError, AttributeError):
            return None
    try:
        return os.stat(path).st_blocks * 512
    except (OSError, AttributeError):
        return None


# ---------- Windows: who holds a folder or file ----------

GENERIC_READ = 0x80000000
OPEN_EXISTING = 3
FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
ERROR_SHARING_VIOLATION, ERROR_LOCK_VIOLATION = 32, 33
GONE = (2, 3)  # file or path not found: it went away meanwhile


def _k32():
    import ctypes
    from ctypes import wintypes
    k = ctypes.WinDLL('kernel32', use_last_error=True)
    k.CreateFileW.restype = wintypes.HANDLE
    k.CreateFileW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                              wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE)
    k.CloseHandle.argtypes = (wintypes.HANDLE,)
    k.OpenProcess.restype = wintypes.HANDLE
    k.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    k.ReadProcessMemory.argtypes = (wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t,
                                    ctypes.POINTER(ctypes.c_size_t))
    k.QueryFullProcessImageNameW.argtypes = (wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                             ctypes.POINTER(wintypes.DWORD))
    k.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    k.CreateToolhelp32Snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)
    k.IsWow64Process.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL))
    return k


def exclusive_open_error(path, folder=False):
    """Open path with no sharing at all and close it again; nothing is changed. 0 when nobody else has it
    open, else the Windows error (32: another process has it open, a folder included when it is a process's
    current folder). Only the exact path counts: a process in a subfolder holds that subfolder, not this."""
    import ctypes
    from ctypes import wintypes
    k = _k32()
    flags = FILE_FLAG_OPEN_REPARSE_POINT | (FILE_FLAG_BACKUP_SEMANTICS if folder else 0)
    h = k.CreateFileW(long_path(path), GENERIC_READ, 0, None, OPEN_EXISTING, flags, None)
    if h == wintypes.HANDLE(-1).value:
        return ctypes.get_last_error() or -1
    k.CloseHandle(h)
    return 0


def _walk_entries(top, want_dirs):
    """(path, is_dir) for everything under top (top itself first when want_dirs), never entering a link."""
    if want_dirs:
        yield top, True
    stack = [top]
    while stack:
        d = stack.pop()
        try:
            with os.scandir(d) as it:
                entries = list(it)
        except OSError:
            continue
        for e in entries:
            if e.is_symlink() or is_link_or_junction(e.path):
                continue
            try:
                is_dir = e.is_dir(follow_symlinks=False)
            except OSError:
                continue
            if is_dir:
                if e.name == '.git':
                    continue  # git's own folder of a main checkout; a worktree has a .git file
                stack.append(e.path)
                if want_dirs:
                    yield e.path, True
            elif not want_dirs:
                yield e.path, False


def busy_dirs(top, limit=1):
    """Windows: folders in top (top included) that some process holds open, its current folder for one.
    Stops at `limit`. [] when none; None when the probe itself does not work here."""
    if not WINDOWS:
        return []
    found = []
    try:
        for d, _ in _walk_entries(long_path(top), want_dirs=True):
            err = exclusive_open_error(d, folder=True)
            if err in GONE or err == 0:
                continue
            found.append(rel(short_path(d), top) if short_path(d) != top else '.')
            if len(found) >= limit:
                break
    except (OSError, AttributeError, ImportError):
        return None
    return found


def held_files(top, limit=5):
    """Windows: files under top that another process has open, which a delete would trip on partway.
    {'count': n, 'files': [first few, relative], 'by': [process names]} or None when it can't be checked.
    POSIX deletes open files fine, so there it is always {'count': 0}."""
    if not WINDOWS:
        return {'count': 0, 'files': [], 'by': []}
    files, count = [], 0
    try:
        for f, _ in _walk_entries(long_path(top), want_dirs=False):
            err = exclusive_open_error(f)
            if err == 0 or err in GONE:
                continue
            count += 1
            if len(files) < limit:
                files.append(short_path(f))
    except (OSError, AttributeError, ImportError):
        return None
    by = lockers(files) if files else []
    return {'count': count, 'files': [rel(f, top) for f in files], 'by': by}


def lockers(paths):
    """Windows: names of the processes holding these files open (Restart Manager, read-only), or []."""
    if not WINDOWS or not paths:
        return []
    try:
        import ctypes
        from ctypes import wintypes
        rm = ctypes.WinDLL('rstrtmgr')

        class UniqueProcess(ctypes.Structure):
            _fields_ = [('pid', wintypes.DWORD), ('start', wintypes.FILETIME)]

        class ProcessInfo(ctypes.Structure):
            _fields_ = [('process', UniqueProcess), ('app', wintypes.WCHAR * 256), ('service', wintypes.WCHAR * 64),
                        ('type', ctypes.c_int), ('status', wintypes.ULONG), ('session', wintypes.DWORD),
                        ('restartable', wintypes.BOOL)]
        session = wintypes.DWORD(0)
        key = ctypes.create_unicode_buffer(33)
        if rm.RmStartSession(ctypes.byref(session), 0, key) != 0:
            return []
        try:
            arr = (wintypes.LPCWSTR * len(paths))(*[long_path(p) for p in paths])
            if rm.RmRegisterResources(session, len(paths), arr, 0, None, 0, None) != 0:
                return []
            needed, have, reasons = wintypes.UINT(0), wintypes.UINT(0), wintypes.DWORD(0)
            rc = rm.RmGetList(session, ctypes.byref(needed), ctypes.byref(have), None, ctypes.byref(reasons))
            if rc not in (0, 234) or not needed.value:
                return []
            infos = (ProcessInfo * needed.value)()
            have = wintypes.UINT(needed.value)
            if rm.RmGetList(session, ctypes.byref(needed), ctypes.byref(have), infos, ctypes.byref(reasons)) != 0:
                return []
            return sorted({f'{infos[i].app} (pid {infos[i].process.pid})' for i in range(have.value)})
        finally:
            rm.RmEndSession(session)
    except (OSError, AttributeError):
        return []


# ---------- processes ----------

def _peb_strings(k, h):
    """(current folder, command line) of an opened process, read from its own memory; (None, None) on any
    failure. Read-only: ReadProcessMemory on a process of this user."""
    import ctypes
    from ctypes import wintypes
    ptr = ctypes.sizeof(ctypes.c_void_p)

    class PBI(ctypes.Structure):
        _fields_ = [('r1', ctypes.c_void_p), ('peb', ctypes.c_void_p), ('r2', ctypes.c_void_p * 2),
                    ('pid', ctypes.c_void_p), ('r3', ctypes.c_void_p)]
    wow = wintypes.BOOL(0)
    if ptr == 8 and k.IsWow64Process(h, ctypes.byref(wow)) and wow.value:
        return None, None  # a 32-bit process keeps its current folder in its 32-bit block
    nt = ctypes.WinDLL('ntdll')
    nt.NtQueryInformationProcess.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.ULONG,
                                             ctypes.POINTER(wintypes.ULONG))
    pbi = PBI()
    if nt.NtQueryInformationProcess(h, 0, ctypes.byref(pbi), ctypes.sizeof(pbi), None) != 0 or not pbi.peb:
        return None, None

    def read(addr, size):
        buf = ctypes.create_string_buffer(size)
        got = ctypes.c_size_t(0)
        if not k.ReadProcessMemory(h, ctypes.c_void_p(addr), buf, size, ctypes.byref(got)) or got.value != size:
            raise OSError('read')
        return buf.raw

    def ustring(addr):
        raw = read(addr, 2 * ptr)
        length = int.from_bytes(raw[:2], 'little')
        buf = int.from_bytes(raw[ptr:2 * ptr], 'little')
        return read(buf, length).decode('utf-16-le', 'replace') if length and buf else ''
    try:
        params = int.from_bytes(read(pbi.peb + 4 * ptr, ptr), 'little')
        cwd_off, cmd_off = (0x38, 0x70) if ptr == 8 else (0x24, 0x40)
        return ustring(params + cwd_off), ustring(params + cmd_off)
    except OSError:
        return None, None


def processes(details=True):
    """Every process this user can see: [{'pid', 'ppid', 'name', 'exe', 'cwd', 'cmdline'}].
    Windows: the process table, each one's program path, and (details) the current folder and command line of
    this user's own processes. POSIX: `ps`, names and command lines only. [] when the table can't be read."""
    if not WINDOWS:
        rc, out, _ = run(['ps', '-Ao', 'pid=,ppid=,args='], timeout=30)
        rows = []
        for line in out.splitlines() if rc == 0 else []:
            parts = line.split(None, 2)
            if len(parts) < 3 or not parts[0].isdigit():
                continue
            args = parts[2]
            rows.append({'pid': int(parts[0]), 'ppid': int(parts[1]) if parts[1].isdigit() else 0,
                         'name': os.path.basename(args.split()[0]) if args.split() else '', 'exe': '',
                         'cwd': None, 'cmdline': args})
        return rows
    try:
        import ctypes
        from ctypes import wintypes
        k = _k32()

        class Entry(ctypes.Structure):
            _fields_ = [('size', wintypes.DWORD), ('usage', wintypes.DWORD), ('pid', wintypes.DWORD),
                        ('heap', ctypes.c_void_p), ('module', wintypes.DWORD), ('threads', wintypes.DWORD),
                        ('ppid', wintypes.DWORD), ('pri', ctypes.c_long), ('flags', wintypes.DWORD),
                        ('exe', wintypes.WCHAR * 260)]
        k.Process32FirstW.argtypes = (wintypes.HANDLE, ctypes.POINTER(Entry))
        k.Process32NextW.argtypes = (wintypes.HANDLE, ctypes.POINTER(Entry))
        snap = k.CreateToolhelp32Snapshot(0x2, 0)
        if snap == wintypes.HANDLE(-1).value:
            return []
        rows = []
        try:
            e = Entry()
            e.size = ctypes.sizeof(Entry)
            ok = k.Process32FirstW(snap, ctypes.byref(e))
            while ok:
                rows.append({'pid': e.pid, 'ppid': e.ppid, 'name': e.exe, 'exe': '', 'cwd': None, 'cmdline': None})
                ok = k.Process32NextW(snap, ctypes.byref(e))
        finally:
            k.CloseHandle(snap)
        me = os.getpid()
        for r in rows:
            if r['pid'] in (0, 4):
                continue
            h = k.OpenProcess(0x1000 | (0x0400 | 0x0010 if details else 0), False, r['pid'])
            if not h:
                h = k.OpenProcess(0x1000, False, r['pid'])
                if not h:
                    continue
                full = False
            else:
                full = details
            try:
                buf = ctypes.create_unicode_buffer(32768)
                n = wintypes.DWORD(32768)
                if k.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)):
                    r['exe'] = buf.value
                if full and r['pid'] != me:
                    r['cwd'], r['cmdline'] = _peb_strings(k, h)
            finally:
                k.CloseHandle(h)
        return rows
    except (OSError, AttributeError, ImportError):
        return []


def windows_cwds():
    """Windows: {real current folder: {process names}} for this user's processes, or None when no process
    could be read at all (the in-use probe still decides; this only names who is there)."""
    rows = processes()
    if not rows:
        return None
    cwds = {}
    for r in rows:
        if r['cwd']:
            cwd = strip_sep(r['cwd']) or r['cwd']
            if len(cwd) == 2 and cwd[1] == ':':
                cwd += '\\'
            cwds.setdefault(os.path.normcase(os.path.realpath(cwd)), set()).add(r['name'])
    return cwds


def running(names, procs=None):
    """Processes whose program (or, for scripts run by an interpreter, a word of the command line) is one of
    names (lower case, without .exe). [(pid, name)]."""
    wanted = {n.lower() for n in names}
    found = []
    for r in procs if procs is not None else processes():
        prog = os.path.basename(r.get('exe') or r.get('name') or '').lower()
        prog = prog[:-4] if prog.endswith('.exe') else prog
        words = set()
        for w in (r.get('cmdline') or '').replace('"', ' ').split()[:4]:
            b = os.path.basename(w.replace('\\', '/')).lower()
            for ext in ('.exe', '.cmd', '.js', '.cjs', '.mjs', '.py'):
                if b.endswith(ext):
                    b = b[:-len(ext)]
            words.add(b)
        if prog in wanted or wanted & words:
            found.append((r['pid'], r.get('name') or prog))
    return found


def delete_tree(path, files=True):
    """Delete path and everything in it, the one routine for worktree leftovers, build folders and caches.

    - A link or junction is removed as a link: never entered, never followed, its target untouched.
    - Read-only files and folders are made writable first (Windows refuses to delete them otherwise).
    - Long paths work (the \\\\?\\ form on Windows).
    - files=False removes only links and the folders left empty, and keeps every real file.
    Returns {'ok': True} or {'ok': False, 'left': n files still there, 'first': [a few], 'error': ...}.
    """
    top = long_path(str(path))
    errors = []

    def unlink(p, is_dir_link=False):
        for attempt in (0, 1):
            try:
                if is_dir_link:
                    os.rmdir(p)
                else:
                    os.unlink(p)
                return
            except FileNotFoundError:
                return
            except OSError as exc:
                if attempt or not WINDOWS:
                    errors.append(f'{short_path(p)}: {exc.strerror or exc}')
                    return
                try:
                    os.chmod(p, stat.S_IWRITE | stat.S_IREAD)
                except OSError:
                    pass

    def link_is_dir(p):
        try:
            return WINDOWS and bool(os.lstat(p).st_file_attributes & 0x10)  # a junction or a folder symlink
        except (OSError, AttributeError):
            return False

    def rm(d):
        try:
            with os.scandir(d) as it:
                entries = list(it)
        except FileNotFoundError:
            return
        except OSError as exc:
            errors.append(f'{short_path(d)}: {exc.strerror or exc}')
            return
        for e in entries:
            if e.is_symlink() or is_link_or_junction(e.path):
                unlink(e.path, link_is_dir(e.path))
            elif e.is_dir(follow_symlinks=False):
                rm(e.path)
            elif files:
                unlink(e.path)
        if files or not os.listdir(d):
            unlink(d, is_dir_link=True)

    if is_link_or_junction(top):
        unlink(top, link_is_dir(top))
    elif os.path.isdir(top):
        rm(top)
    elif os.path.lexists(top) and files:
        unlink(top)
    if not os.path.lexists(top):
        return {'ok': True}
    left = [f for f, _ in _walk_entries(top, want_dirs=False)] if os.path.isdir(top) else [top]
    return {'ok': False, 'left': len(left), 'first': [short_path(f) for f in left[:5]],
            'error': errors[0] if errors else 'not everything could be deleted'}

