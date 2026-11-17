#!/usr/bin/env bash
# SessionStart hook: make sure alerter (notifications you can answer) is installed.
# If it is missing and Homebrew is there, install it in the background, at most once a day.
# Never blocks or breaks the session; says one line when it starts an install.
set -uo pipefail
# Keep the background service on this plugin's version (it runs from a fixed copy).
here="$(cd "$(dirname "$0")" && pwd)"
msg="$(python3 "$here/pr-pulse" daemon sync 2>/dev/null || true)"
# Once ever: tell an install with auto-update off how to turn it on (it is the user's setting).
home="${PR_PULSE_HOME:-$HOME/.claude/pr-pulse}"; mkdir -p "$home"
if [ ! -e "$home/autoupdate-hint.shown" ] &&
   python3 "$here/pr-pulse" autoupdate status 2>/dev/null | grep -q ': off$'; then
  : >"$home/autoupdate-hint.shown"
  hint="pr-pulse: auto-update is off, so new pr-pulse versions need a manual update. Run 'pr-pulse autoupdate on' (or /pr-pulse:init) to get them automatically."
  msg="${msg:+$msg }$hint"
fi
command -v alerter >/dev/null 2>&1 && {
  [ -n "$msg" ] && printf '{"systemMessage": "%s"}\n' "$msg"
  exit 0
}
command -v brew >/dev/null 2>&1 || exit 0
home="${PR_PULSE_HOME:-$HOME/.claude/pr-pulse}"; mkdir -p "$home"
mark="$home/alerter-install.last"; log="$home/alerter-install.log"
if [ -f "$mark" ] && [ $(( $(date +%s) - $(stat -f %m "$mark") )) -lt 86400 ]; then exit 0; fi
: >"$mark"
nohup brew install vjeantet/tap/alerter >"$log" 2>&1 </dev/null &
printf '{"systemMessage": "pr-pulse: installing alerter in the background (brew install vjeantet/tap/alerter), so you can answer pr-pulse questions from notifications. Log: %s"}\n' "$log"
exit 0
