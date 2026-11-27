#!/bin/sh
# reclaim tests: sh plugins/reclaim/tests/run.test.sh
# Temporary git repos with fake gh/lsof/docker on PATH; nothing real is removed. Needs Python 3.9+ and git.
# On Windows (Git Bash) the Windows tests run too: real child processes, open files and junctions, all in
# temporary folders.
set -eu
here=$(cd "$(dirname "$0")/.." && pwd)
cd "$here"
py=""
for c in python3 python; do
  if "$c" -c "import sys; sys.exit(sys.version_info < (3, 9))" >/dev/null 2>&1; then py=$c; break; fi
done
[ -n "$py" ] || { echo "Python 3.9+ is required to run the tests" >&2; exit 1; }
command -v git >/dev/null 2>&1 || { echo "git is required to run the tests" >&2; exit 1; }
out=$(mktemp)
status=0
"$py" -m unittest discover -s tests -v >"$out" 2>&1 || status=$?
tail -40 "$out"
rm -f "$out"
exit "$status"
