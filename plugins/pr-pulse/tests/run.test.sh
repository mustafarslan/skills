#!/bin/sh
# pr-pulse tests, run by scripts/check.sh and CI: Python unit tests, then the hook smoke test.
# Everything runs against temporary stores; nothing touches Slack, GitHub or Claude.
set -eu
here=$(cd "$(dirname "$0")/.." && pwd)
cd "$here"
command -v python3 >/dev/null 2>&1 || { echo "skip: python3 not installed"; exit 0; }
HOME_TMP=$(mktemp -d)
PR_PULSE_HOME="$HOME_TMP/home" PR_PULSE_NO_NOTIFY=1 python3 -m unittest discover -s tests
bash tests/smoke.sh
