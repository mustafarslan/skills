#!/bin/sh
# SessionStart hook: warn when free space is below the configured level, at most once an hour.
# The logic lives in low_disk.py (Python 3.9+ is the plugin's one hard requirement; jq is not needed).
# Always exits 0 and stays silent when anything is missing. On Windows `python3` may be missing or the
# Microsoft Store's stub, so the first Python that actually runs is used.
here=$(dirname "$0")
for py in python3 python; do
  if "$py" -c "import sys; sys.exit(sys.version_info < (3, 9))" >/dev/null 2>&1; then
    "$py" "$here/low_disk.py" 2>/dev/null
    exit 0
  fi
done
if py -3 -c "import sys; sys.exit(sys.version_info < (3, 9))" >/dev/null 2>&1; then
  py -3 "$here/low_disk.py" 2>/dev/null
fi
exit 0
