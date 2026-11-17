#!/usr/bin/env bash
# pr-pulse toggle.
#   Hook mode (UserPromptExpansion): no arguments, event JSON on stdin.
#     Answers /pr-pulse:on|off|status itself and blocks the prompt, so the
#     model never sees it (no tokens, no round trip).
#   Direct mode (fallback the skills call if the hook did not run):
#     toggle.sh <on|off|status> <session_id> [worktree]
set -Eeuo pipefail
# shellcheck source=forward.sh disable=SC1091
source "$(dirname "${BASH_SOURCE[0]}")/forward.sh" "$@"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$HERE/lib.sh"
trap 'pp_warn "toggle error on line $LINENO (ignored)"; exit 0' ERR

if ! command -v jq >/dev/null 2>&1; then
  pp_warn "jq not found (brew install jq). Toggle skipped."
  exit 0
fi

mode=direct action="" sid="" args="" cwd="$PWD"
if [ $# -eq 0 ]; then
  mode=hook
  input="$(cat)"
  jq -e 'type == "object"' >/dev/null 2>&1 <<<"$input" || exit 0
  prompt="$(jq -r '.prompt // ""' <<<"$input")"
  name="$(jq -r '.command_name // ""' <<<"$input")"
  sid="$(jq -r '.session_id // ""' <<<"$input")"
  cwd="$(jq -r '.cwd // ""' <<<"$input")"
  args="$(jq -r '.command_args // ""' <<<"$input")"
  # Handle only our own commands. command_name may or may not carry the
  # plugin prefix, so the typed line is checked first.
  if [[ "$prompt" =~ ^/pr-pulse:(on|off|status|pause|resume|stop|start|help|auto-review)([[:space:]]|$) ]]; then
    action="${BASH_REMATCH[1]}"
  elif [[ "$name" =~ ^pr-pulse:(on|off|status|pause|resume|stop|start|help|auto-review)$ ]]; then
    action="${BASH_REMATCH[1]}"
  else
    exit 0
  fi
else
  action="${1:-status}"
  sid="${2:-}"
  args="${*:3}"
fi

respond() {
  if [ "$mode" = hook ]; then
    jq -nc --arg r "$1" '{decision: "block", reason: $r}'
  else
    printf '%s\n' "$1"
  fi
  exit 0
}

# help needs no session id and changes nothing.
if [ "$action" = help ]; then
  readme="$(cd "$HERE/.." && pwd)/README.md"
  respond "$(sed "s#{{readme}}#$readme#" "$HERE/../prompts/help.md" 2>/dev/null || echo "pr-pulse: help text missing; see $readme")"
fi

pp_valid_sid "$sid" || respond "pr-pulse: could not read this session's id, so nothing changed."

scope=session
if [[ "$args" =~ (^|[[:space:]])worktree([[:space:]]|$) ]]; then scope=worktree; fi

sflag="$(pp_session_flag "$sid")"
wflag="$(pp_worktree_flag "$cwd" || true)"
mkdir -p "$PR_PULSE_SESSIONS"
now="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

webhook_note=""
if ! pp_can_post; then
  webhook_note=" Heads up: Slack is not set up yet, so announcements can't be posted. Run /pr-pulse:init."
fi

case "$action" in
  on)
    # Tidy up flags from sessions nobody resumed in a long time.
    find "$PR_PULSE_SESSIONS" -type f -mtime +45 -delete 2>/dev/null || true
    if [ "$scope" = worktree ]; then
      [ -n "$wflag" ] || respond "pr-pulse: $cwd is not inside a git worktree, so worktree mode is unavailable. Use /pr-pulse:on for this session instead."
      printf 'on\t%s\n' "$now" >"$wflag"
      respond "pr-pulse is ON for this worktree ($(basename "$cwd")), in this and future sessions. PRs opened here will be announced in $PR_PULSE_CHANNEL.$webhook_note"
    fi
    printf '%s\t%s\n' "$now" "$cwd" >"$sflag"
    respond "pr-pulse is ON for this session. PRs you open here will be announced in $PR_PULSE_CHANNEL.$webhook_note"
    ;;
  off)
    msg="pr-pulse is OFF for this session."
    rm -f "$sflag"
    if [ -n "$wflag" ] && [ -f "$wflag" ]; then
      rm -f "$wflag"
      msg="pr-pulse is OFF for this session and this worktree."
    fi
    respond "$msg"
    ;;
  status)
    where="$(pp_is_on "$sid" "$cwd" || true)"
    state="OFF"
    [ -z "$where" ] || state="ON ($where flag)"
    hook_state="NOT set up (/pr-pulse:init)"
    if [ -n "${PR_PULSE_SLACK_BOT_TOKEN:-}" ] && pp_announce_channel >/dev/null; then hook_state="bot token"
    elif [ -n "${PR_PULSE_SLACK_WEBHOOK_URL:-}" ]; then hook_state="webhook"; fi
    drafts="skipped"
    [ "${PR_PULSE_INCLUDE_DRAFTS:-0}" != 1 ] || drafts="included"
    count=0
    [ ! -f "$PR_PULSE_POSTED" ] || count="$(wc -l <"$PR_PULSE_POSTED" | tr -d ' ')"
    board="$(python3 "$HERE/pr-pulse" status 2>&1 || true)"
    respond "pr-pulse is $state for announcements in this session. Slack posting: $hook_state. Drafts: $drafts. PRs posted so far (v1 log): $count.

$board"
    ;;
  pause|resume|stop|start|auto-review)
    respond "$(python3 "$HERE/pr-pulse" "$action" $args 2>&1 || true)"
    ;;
  *)
    respond "pr-pulse: unknown action '$action'. Use on, off or status."
    ;;
esac
