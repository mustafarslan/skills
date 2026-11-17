# shellcheck shell=bash
# Sourced first by every pr-pulse bash entry point: from any copy other than the service's own
# (~/.claude/pr-pulse/app), run the same script there instead, so a session that loaded an
# older pr-pulse still runs the current one. The service's copy is kept current by the daemon,
# by every Bash call (post-guard), and at session start. See current.py.
#   source "$(dirname "${BASH_SOURCE[0]}")/forward.sh" "$@"
if [ -z "${PR_PULSE_FORWARDED:-}" ]; then
  _pp_self="${BASH_SOURCE[1]:-$0}"
  _pp_dir="$(cd "$(dirname "$_pp_self")" && pwd -P)"
  _pp_app="${PR_PULSE_HOME:-$HOME/.claude/pr-pulse}/app/scripts"
  if [ -f "$_pp_app/$(basename "$_pp_self")" ] && [ "$(cd "$_pp_app" && pwd -P)" != "$_pp_dir" ]; then
    export PR_PULSE_FORWARDED=1
    export PR_PULSE_LOADED_FROM="${PR_PULSE_LOADED_FROM:-$(dirname "$_pp_dir")}"
    exec bash "$_pp_app/$(basename "$_pp_self")" "$@"
  fi
  unset _pp_self _pp_dir _pp_app
fi
