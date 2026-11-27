#!/bin/sh
# power-saver tests: sh plugins/power-saver/tests/run.test.sh
# Fake powercfg, nvidia-smi and schtasks; nothing on the machine is changed. The guard and setup tests run
# PowerShell against fakes on Windows and skip elsewhere. Needs Python 3.9+.
set -eu
here=$(cd "$(dirname "$0")/.." && pwd)
cd "$here"
py=""
for c in python3 python; do
  if "$c" -c "import sys; sys.exit(sys.version_info < (3, 9))" >/dev/null 2>&1; then py=$c; break; fi
done
[ -n "$py" ] || { echo "Python 3.9+ is required to run the tests" >&2; exit 1; }
out=$(mktemp)
status=0
"$py" -m unittest discover -s tests -v >"$out" 2>&1 || status=$?
tail -40 "$out"
rm -f "$out"
exit "$status"
