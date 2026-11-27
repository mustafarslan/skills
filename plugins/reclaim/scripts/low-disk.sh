#!/bin/sh
# SessionStart hook: warn when free space on / is below the configured level, at most once an hour.
# The logic lives in low_disk.py (python3 is the plugin's one hard requirement; jq is not needed).
# Always exits 0 and stays silent when anything is missing.
command -v python3 >/dev/null 2>&1 || exit 0
python3 "$(dirname "$0")/low_disk.py" 2>/dev/null
exit 0
