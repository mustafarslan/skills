#!/usr/bin/env bash
# Post one PR announcement to Slack through an incoming webhook.
#
#   post.sh --url <pr-url> [--title <title>] [--force] [--dry-run] < announcement.txt
#   post.sh --url <pr-url> --text "<announcement>"
#
# The webhook URL comes only from PR_PULSE_SLACK_WEBHOOK_URL and is never printed.
# Exit codes: 0 posted (or dry run) | 2 usage | 3 webhook variable missing or invalid
#             4 already posted | 5 Slack rejected the post | 6 jq or curl missing
set -Eeuo pipefail
# shellcheck source=forward.sh disable=SC1091
source "$(dirname "${BASH_SOURCE[0]}")/forward.sh" "$@"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$HERE/lib.sh"

die() { local code="$1"; shift; printf 'post.sh: %s\n' "$*" >&2; exit "$code"; }

url="" title="" text="" force=0 dry="${PR_PULSE_DRY_RUN:-0}"
while [ $# -gt 0 ]; do
  case "$1" in
    --url)     [ $# -ge 2 ] || die 2 "--url needs a value"; url="$2"; shift 2 ;;
    --title)   [ $# -ge 2 ] || die 2 "--title needs a value"; title="$2"; shift 2 ;;
    --text)    [ $# -ge 2 ] || die 2 "--text needs a value"; text="$2"; shift 2 ;;
    --force)   force=1; shift ;;
    --dry-run) dry=1; shift ;;
    *)         die 2 "unknown argument: $1" ;;
  esac
done

for t in jq curl; do
  command -v "$t" >/dev/null 2>&1 || die 6 "$t is not installed"
done

[[ "$url" =~ ^${PR_URL_RE}$ ]] || die 2 "--url must be a GitHub pull request URL"
[[ "$url" =~ github\.com/([^/]+)/([^/]+)/pull/([0-9]+) ]]
ref="${BASH_REMATCH[2]}#${BASH_REMATCH[3]}"

if [ -z "$text" ] && [ ! -t 0 ]; then text="$(cat)"; fi
[ -n "$(printf '%s' "$text" | tr -d '[:space:]')" ] || die 2 "the announcement text is empty"

if [ "$force" != 1 ] && pp_already_posted "$url"; then
  die 4 "already posted $url (pass --force to post it again)"
fi

# Two ways to post: the bot token + announce_channel (what /pr-pulse:init sets up), or a v1
# incoming webhook. The token wins when both are there.
# With post_as "user" it posts with the user's own token, or not at all: never as the bot.
hook="${PR_PULSE_SLACK_WEBHOOK_URL:-}"
tok="${PR_PULSE_SLACK_BOT_TOKEN:-}"
as_user=0
if [ "$(pp_post_as)" = user ]; then as_user=1; tok="${PR_PULSE_SLACK_USER_TOKEN:-}"; hook=""; fi
chan="$(pp_announce_channel || true)"
mode=""
if [ -n "$tok" ] && [ -n "$chan" ]; then mode=token
elif [ -n "$hook" ]; then mode=webhook
fi
if [ "$dry" != 1 ]; then
  if [ -z "$mode" ] && [ "$as_user" = 1 ]; then
    die 3 "post_as is user, but your Slack user token is missing. Run /pr-pulse:init slack."
  fi
  [ -n "$mode" ] || die 3 "Slack is not set up for announcements. Run /pr-pulse:init."
  if [ "$mode" = webhook ]; then
    case "$hook" in
      https://hooks.slack.com/*) ;;
      *) die 3 "PR_PULSE_SLACK_WEBHOOK_URL does not look like a Slack incoming webhook URL" ;;
    esac
  fi
fi

# Title: flag, then the hook's cached gh metadata, then gh itself.
cache="$PR_PULSE_PENDING/$(pp_key "$url").json"
if [ -z "$title" ] && [ -f "$cache" ]; then title="$(jq -r '.title // ""' "$cache" 2>/dev/null || true)"; fi
if [ -z "$title" ] && pp_have_gh; then title="$(gh pr view "$url" --json title -q .title 2>/dev/null || true)"; fi

# Slack mrkdwn needs &, < and > escaped. jq does it, so bash version quirks don't matter.
who="$(pp_my_name)"
[ "$as_user" = 1 ] && who=""   # posted as the person: the message already shows who
payload="$(jq -nc --arg summary "$text" --arg url "$url" --arg ref "$ref" --arg title "$title" --arg who "$who" '
  def esc: gsub("&"; "&amp;") | gsub("<"; "&lt;") | gsub(">"; "&gt;");
  ($summary | sub("\\s+$"; "") | esc) as $s
  | ($title | gsub("\\|"; "/") | esc) as $t
  | { text: ($s + "\n<" + $url + "|" + $ref + (if $t == "" then "" else ": " + $t end) + ">"
             + (if $who == "" then "" else " · " + ($who | esc) end)),
      unfurl_links: false, unfurl_media: false }')"

if [ "$mode" = token ]; then
  payload="$(jq -c --arg ch "$chan" '. + {channel: $ch}' <<<"$payload")"
fi

if [ "$dry" = 1 ]; then
  printf '%s\n' "$payload"
  echo "dry run: nothing was sent"
  exit 0
fi

if [ "$mode" = token ]; then
  # The token goes in a header read from a process substitution, never on the command line (ps).
  if ! resp="$(curl -sS --max-time 10 -H 'Content-Type: application/json; charset=utf-8' \
        -H @<(printf 'Authorization: Bearer %s\n' "$tok") \
        --data "$payload" "${PR_PULSE_SLACK_API:-https://slack.com/api/}chat.postMessage" 2>&1)" \
     || [ "$(jq -r '.ok // false' <<<"$resp" 2>/dev/null)" != true ]; then
    die 5 "Slack rejected the post: $(jq -r '.error // empty' <<<"$resp" 2>/dev/null || printf '%s' "$resp" | head -c 200)"
  fi
elif ! resp="$(curl -sS --fail-with-body --max-time 10 \
      -H 'Content-Type: application/json' --data "$payload" "$hook" 2>&1)"; then
  die 5 "Slack rejected the post: $(printf '%s' "$resp" | head -c 200 | tr '\n' ' ')"
fi

pp_mark_posted "$url"
rm -f "$cache"
echo "posted $url to $PR_PULSE_CHANNEL"
