#!/bin/sh
# park tests, run by scripts/check.sh and CI. Temporary store, fake claude/osascript; no real sessions.
set -eu
here=$(cd "$(dirname "$0")/.." && pwd)
cd "$here"
command -v python3 >/dev/null 2>&1 || { echo "skip: python3 not installed"; exit 0; }
out=$(mktemp)
status=0
PARK_NO_NOTIFY=1 python3 -m unittest discover -s tests -v >"$out" 2>&1 || status=$?
tail -25 "$out"
rm -f "$out"
exit "$status"
