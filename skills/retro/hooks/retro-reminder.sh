#!/bin/sh
# SessionStart: once /retro has run, remind in sessions of the configured repo when the interval
# (14 days by default) has passed, at most once a day. All logic (repo check, snooze, the
# once-a-day stamp) is in state.py; without ~/.claude/retro/config.json it stays silent.
# Never fail the session start: any error here stays silent. The scripts are found beside this
# hook (../scripts), else in ~/.claude/skills/retro/scripts; RETRO_SCRIPTS points at another
# scripts folder (the tests use it).
DIR=$(dirname "$0")/../scripts
[ -f "$DIR/state.py" ] || DIR=$HOME/.claude/skills/retro/scripts
python3 "${RETRO_SCRIPTS:-$DIR}/state.py" remind 2>/dev/null
exit 0
