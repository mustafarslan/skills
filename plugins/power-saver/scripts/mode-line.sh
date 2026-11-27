#!/bin/sh
# SessionStart hook: one line when power-saver's mode is on, so a session doesn't take a slow build for a bug.
# Reads two files, runs no command. Always exits 0 and stays silent when anything is missing.
here=$(dirname "$0")
for py in python3 python; do
  if "$py" -c "import sys; sys.exit(sys.version_info < (3, 9))" >/dev/null 2>&1; then
    "$py" "$here/power_saver.py" mode-line 2>/dev/null
    exit 0
  fi
done
if py -3 -c "" >/dev/null 2>&1; then
  py -3 "$here/power_saver.py" mode-line 2>/dev/null
fi
exit 0
