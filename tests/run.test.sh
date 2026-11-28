#!/bin/sh
# Repo-level tests: sh tests/run.test.sh (each plugin has its own suite under plugins/<name>/tests/).
set -eu
cd "$(dirname "$0")/.."
py=""
for c in python3 python; do
  if "$c" -c "import sys; sys.exit(sys.version_info < (3, 9))" >/dev/null 2>&1; then py=$c; break; fi
done
[ -n "$py" ] || { echo "Python 3.9+ is required to run the tests" >&2; exit 1; }
exec "$py" -m unittest discover -s tests -v
