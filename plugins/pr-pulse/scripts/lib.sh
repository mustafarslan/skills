# shellcheck shell=bash
# Shared helpers for pr-pulse. Sourced by the other scripts, never run directly.
# Written for bash 3.2+ (macOS /bin/bash) as well as bash 5.

PR_PULSE_HOME="${PR_PULSE_HOME:-$HOME/.claude/pr-pulse}"
PR_PULSE_SESSIONS="$PR_PULSE_HOME/sessions"
# shellcheck disable=SC2034  # used by the scripts that source lib.sh
PR_PULSE_PENDING="$PR_PULSE_HOME/pending"
PR_PULSE_POSTED="$PR_PULSE_HOME/posted.tsv"
# shellcheck disable=SC2034  # used by the scripts that source lib.sh
PR_PULSE_CHANNEL="${PR_PULSE_CHANNEL_LABEL:-#pr-review}"
PR_URL_RE='https://github\.com/[^/[:space:]]+/[^/[:space:]]+/pull/[0-9]+'

pp_warn() { printf 'pr-pulse: %s\n' "$*" >&2; }

# Read pr-pulse's own secrets from ~/.config/pr-pulse/env when the session's environment lacks
# them, so a running session never needs a restart after /pr-pulse:init. The file is parsed,
# never sourced, and only these keys are taken.
PR_PULSE_ENV_FILE="${PR_PULSE_ENV_FILE:-$HOME/.config/pr-pulse/env}"
pp_load_env() {
  [ -r "$PR_PULSE_ENV_FILE" ] || return 0
  local key val
  for key in PR_PULSE_SLACK_WEBHOOK_URL PR_PULSE_SLACK_BOT_TOKEN PR_PULSE_SLACK_USER_TOKEN; do
    [ -n "${!key:-}" ] && continue
    val="$(sed -nE "s/^[[:space:]]*(export[[:space:]]+)?${key}=['\"]?([^'\" ]*)['\"]?.*$/\2/p" "$PR_PULSE_ENV_FILE" | tail -n1)"
    [ -n "$val" ] && export "$key=$val"
  done
  return 0
}
pp_load_env

# Where announcements go when they are posted with the bot token (config announce_channel).
pp_announce_channel() {
  local cfg="${PR_PULSE_CONFIG:-$HOME/.config/pr-pulse/config.json}"
  command -v jq >/dev/null 2>&1 || return 1
  local ch="" team
  [ -r "$cfg" ] && ch="$(jq -r '.announce_channel // empty' "$cfg" 2>/dev/null)"
  if [ -z "$ch" ]; then   # the team's shared channel (team.json next to the plugin)
    team="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/team.json"
    [ -r "$team" ] && ch="$(jq -r '.slack.announce_channel // empty' "$team" 2>/dev/null)"
  fi
  [ -n "$ch" ] && printf '%s' "$ch"
}

# The user's first name, shown on announcements (several people post through one shared bot).
pp_my_name() {
  local cfg="${PR_PULSE_CONFIG:-$HOME/.config/pr-pulse/config.json}" n=""
  [ -r "$cfg" ] && command -v jq >/dev/null 2>&1 && n="$(jq -r '.my_name // empty' "$cfg" 2>/dev/null)"
  [ -n "$n" ] || n="$(git config --global --get user.name 2>/dev/null | awk '{print $1}')"
  printf '%s' "$n"
}

# Who posts: "user" (config post_as, with the user's own token) or "bot".
pp_post_as() {
  local cfg="${PR_PULSE_CONFIG:-$HOME/.config/pr-pulse/config.json}" v=""
  [ -r "$cfg" ] && command -v jq >/dev/null 2>&1 && v="$(jq -r '.post_as // empty' "$cfg" 2>/dev/null)"
  [ "$v" = user ] && printf user || printf bot
}

# Can announcements be posted at all? As the user: their token + announce channel, nothing else.
# As the bot: webhook, or bot token + announce channel.
pp_can_post() {
  if [ "$(pp_post_as)" = user ]; then
    [ -n "${PR_PULSE_SLACK_USER_TOKEN:-}" ] && pp_announce_channel >/dev/null
    return
  fi
  [ -n "${PR_PULSE_SLACK_WEBHOOK_URL:-}" ] && return 0
  [ -n "${PR_PULSE_SLACK_BOT_TOKEN:-}" ] && pp_announce_channel >/dev/null
}

pp_have_gh() { [ "${PR_PULSE_NO_GH:-0}" != 1 ] && command -v gh >/dev/null 2>&1; }

# Session ids become file names, so only allow safe characters.
pp_valid_sid() {
  [[ "${1:-}" =~ ^[A-Za-z0-9._-]+$ ]] && [ "$1" != "." ] && [ "$1" != ".." ]
}

pp_session_flag() { printf '%s/%s' "$PR_PULSE_SESSIONS" "$1"; }

# Flag file for the git worktree that contains dir $1. Fails outside git.
# --absolute-git-dir is per worktree (.git/worktrees/<name> for linked ones).
pp_worktree_flag() {
  local gd
  gd="$(git -C "${1:-.}" rev-parse --absolute-git-dir 2>/dev/null)" || return 1
  printf '%s/pr-pulse-on' "$gd"
}

# pp_is_on <session_id> <cwd>: prints "session" or "worktree"; fails when off.
pp_is_on() {
  local wf
  if pp_valid_sid "${1:-}" && [ -f "$(pp_session_flag "$1")" ]; then
    echo session; return 0
  fi
  if wf="$(pp_worktree_flag "${2:-.}")" && [ -f "$wf" ]; then
    echo worktree; return 0
  fi
  return 1
}

# File-name-safe key for a PR URL.
pp_key() { printf '%s' "$1" | tr -c 'A-Za-z0-9' '_'; }

PR_PULSE_DB="$PR_PULSE_HOME/pulse.db"

# Run one statement against the v2 store; silent and false when sqlite3 or the store is missing.
pp_sql() {
  [ -f "$PR_PULSE_DB" ] && command -v sqlite3 >/dev/null 2>&1 || return 1
  sqlite3 -cmd ".timeout 3000" "$PR_PULSE_DB" "$1" 2>/dev/null
}

# owner/name of the GitHub origin of dir $1, or fail.
pp_slug() {
  local remote slug
  remote="$(git -C "${1:-.}" remote get-url origin 2>/dev/null)" || return 1
  remote="${remote%.git}"
  slug="$(sed -nE 's#.*github\.com[:/]([^/]+/[^/]+)/?$#\1#p' <<<"$remote")"
  # Strict charset: the slug is put into SQL below.
  [[ "$slug" =~ ^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$ ]] || return 1
  printf '%s' "$slug"
}

# Is the repo containing dir $1 mapped in pr-pulse v2 with announce on?
pp_repo_announces() {
  local slug
  slug="$(pp_slug "${1:-.}")" || return 1
  [ "$(pp_sql "SELECT 1 FROM repos WHERE slug='$slug' AND announce=1 LIMIT 1")" = 1 ]
}

pp_already_posted() {
  if [ -f "$PR_PULSE_POSTED" ] && cut -f1 "$PR_PULSE_POSTED" | grep -Fxq -- "$1"; then return 0; fi
  [[ "$1" =~ ^${PR_URL_RE}$ ]] || return 1
  [ "$(pp_sql "SELECT 1 FROM announced WHERE url='$1' LIMIT 1")" = 1 ]
}

pp_mark_posted() {
  mkdir -p "$PR_PULSE_HOME"
  printf '%s\t%s\n' "$1" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >>"$PR_PULSE_POSTED"
  [[ "$1" =~ ^${PR_URL_RE}$ ]] || return 0
  pp_sql "INSERT OR IGNORE INTO announced(url, at) VALUES('$1', '$(date -u +%Y-%m-%dT%H:%M:%SZ)')" >/dev/null || true
  pp_sql "UPDATE announcements SET state='posted', updated_at=CAST(strftime('%s','now') AS REAL) WHERE url='$1'" >/dev/null || true
}
