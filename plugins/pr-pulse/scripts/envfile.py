"""~/.config/pr-pulse/env: read and write `export KEY='value'` lines without ever sourcing the file
or printing a value. Secrets live only here (chmod 600, folder 700)."""
import os
import re
from pathlib import Path

ENV = Path(os.environ.get("PR_PULSE_ENV_FILE", str(Path.home() / ".config" / "pr-pulse" / "env")))
LINE = re.compile(r"^\s*(?:export\s+)?([A-Z0-9_]+)=(.*)$")


def read():
    out = {}
    if not ENV.exists():
        return out
    for line in ENV.read_text().splitlines():
        m = LINE.match(line)
        if m and not line.lstrip().startswith("#"):
            v = m.group(2).split(" #")[0].strip().strip("'\"")
            out[m.group(1)] = v
    return out


def set_value(key, value):
    """Replace or append `export KEY='value'`; keep every other line as it was."""
    if "'" in value or "\n" in value:
        raise ValueError("value contains a quote or a newline")
    ENV.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(ENV.parent, 0o700)
    lines = ENV.read_text().splitlines() if ENV.exists() else []
    new = f"export {key}='{value}'"
    done = False
    for i, line in enumerate(lines):
        m = LINE.match(line)
        if m and m.group(1) == key and not line.lstrip().startswith("#"):
            lines[i], done = new, True
    if not done:
        lines.append(new)
    fd = os.open(str(ENV), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write("\n".join(lines) + "\n")
    os.chmod(ENV, 0o600)


def load_into_environ():
    for k, v in read().items():
        os.environ.setdefault(k, v)
