#!/bin/sh
# reclaim tests: sh plugins/reclaim/tests/run.test.sh
# Temporary git repos with fake gh/lsof/docker on PATH; nothing real is removed. Needs python3 and git.
set -eu
here=$(cd "$(dirname "$0")/.." && pwd)
cd "$here"
command -v python3 >/dev/null 2>&1 || { echo "python3 is required to run the tests" >&2; exit 1; }
command -v git >/dev/null 2>&1 || { echo "git is required to run the tests" >&2; exit 1; }
out=$(mktemp)
status=0
python3 -m unittest discover -s tests -v >"$out" 2>&1 || status=$?
tail -40 "$out"
rm -f "$out"
exit "$status"
