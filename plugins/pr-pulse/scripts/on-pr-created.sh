#!/usr/bin/env bash
# PostToolUse hook. When a session with pr-pulse ON opens a PR (gh pr create,
# gh pr ready, or a GitHub MCP create_pull_request call), hand Claude the PR
# details and ask it to write the announcement and run post.sh.
# Never breaks the session: every internal problem ends in exit 0.
set -Eeuo pipefail
# shellcheck source=forward.sh disable=SC1091
source "$(dirname "${BASH_SOURCE[0]}")/forward.sh" "$@"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$HERE/lib.sh"
trap 'pp_warn "hook error on line $LINENO (ignored)"; exit 0' ERR

if ! command -v jq >/dev/null 2>&1; then
  pp_warn "jq not found (brew install jq). pr-pulse is inactive."
  exit 0
fi

input="$(cat)"
jq -e 'type == "object"' >/dev/null 2>&1 <<<"$input" || exit 0
sid="$(jq -r '.session_id // ""' <<<"$input")"
cwd="$(jq -r '.cwd // ""' <<<"$input")"
tool="$(jq -r '.tool_name // ""' <<<"$input")"

# 1. Cheapest check first: is pr-pulse on for this session or worktree? If not, the repo may
#    still be mapped with announce on (v2); that costs a git + sqlite call, so it waits until
#    we know this call opened a PR (step 2b).
on_flag=0
pp_is_on "$sid" "$cwd" >/dev/null && on_flag=1

emit_context() {
  jq -nc --arg c "$1" '{hookSpecificOutput: {hookEventName: "PostToolUse", additionalContext: $c}}'
  exit 0
}
emit_notice() {
  jq -nc --arg m "$1" '{systemMessage: $m}'
  exit 0
}

# 2. Find the PR URL and whether it is a draft.
url="" draft="" kind=""
if [ "$tool" = Bash ]; then
  cmd="$(jq -r '.tool_input.command // ""' <<<"$input")"
  case "$cmd" in "$HERE/post.sh"*) exit 0 ;; esac   # our own posting step
  if [[ "$cmd" =~ gh[[:space:]]+pr[[:space:]]+create ]]; then
    kind=create
  elif [[ "$cmd" =~ gh[[:space:]]+pr[[:space:]]+ready ]] && [[ ! "$cmd" =~ --undo ]]; then
    kind=ready
  else
    exit 0
  fi
  out="$(jq -r '.tool_response | if type == "object" then ((.stdout // "") + "\n" + (.stderr // "")) else tostring end' <<<"$input")"
  url="$(grep -oE "$PR_URL_RE" <<<"$out" | head -n1 || true)"

  if [ "$kind" = create ]; then
    if [[ "$cmd" =~ (^|[[:space:]])(--draft|-d)([[:space:]]|=|$) ]]; then draft=true; fi
  else
    [ "${PR_PULSE_POST_ON_READY:-1}" = 1 ] || exit 0
    # gh pr ready prints no URL; take it from the command or ask gh.
    [ -n "$url" ] || url="$(grep -oE "$PR_URL_RE" <<<"$cmd" | head -n1 || true)"
    if [ -z "$url" ] && pp_have_gh; then
      sel="$(sed -nE 's/.*gh[[:space:]]+pr[[:space:]]+ready[[:space:]]+#?([0-9]+).*/\1/p' <<<"$cmd")"
      if [ -n "$sel" ]; then
        url="$(cd "$cwd" && gh pr view "$sel" --json url -q .url 2>/dev/null || true)"
      else
        url="$(cd "$cwd" && gh pr view --json url -q .url 2>/dev/null || true)"
      fi
    fi
    draft=false
  fi
elif [[ "$tool" =~ create_pull_request$ ]]; then
  kind=create
  url="$(jq -r '.tool_response | tostring' <<<"$input" | grep -oE "$PR_URL_RE" | head -n1 || true)"
  if [ "$(jq -r '.tool_input.draft // false' <<<"$input")" = true ]; then draft=true; fi
else
  exit 0
fi

# 2-. Remember which session opened this PR (session focus routes its jobs), before any of the
#     announce gates below: a PR is attributed even when nothing is announced.
if [ "$kind" = create ] && [ -n "$url" ] && pp_valid_sid "$sid"; then
  "$HERE/pr-pulse" focus record "$url" "$sid" >/dev/null 2>&1 || true
fi

# 2a. `pr-pulse stop` silences announcements too.
[ "$(pp_sql "SELECT value FROM settings WHERE key='stopped'")" = 1 ] && exit 0

# 2b. Not on by flag: announce only if the repo is mapped with announce on.
if [ "$on_flag" = 0 ]; then
  pp_repo_announces "$cwd" || exit 0
fi

# 3. No URL means the command failed or printed something unexpected: stay quiet.
[ -n "$url" ] || exit 0

# 4. Dedup: never announce the same PR twice.
if pp_already_posted "$url"; then exit 0; fi

# 5. Ask GitHub for the facts (title, draft state, size). Optional.
title="" size=""
if pp_have_gh; then
  meta="$(gh pr view "$url" --json title,isDraft,additions,deletions,changedFiles,baseRefName,headRefName 2>/dev/null || true)"
  if [ -n "$meta" ] && jq -e 'type == "object"' >/dev/null 2>&1 <<<"$meta"; then
    title="$(jq -r '.title // ""' <<<"$meta")"
    d="$(jq -r 'if .isDraft == null then "" else (.isDraft | tostring) end' <<<"$meta")"
    [ -z "$d" ] || draft="$d"
    size="$(jq -r '"+\(.additions // 0)/-\(.deletions // 0) in \(.changedFiles // 0) files, \(.headRefName // "?") into \(.baseRefName // "?")"' <<<"$meta")"
    mkdir -p "$PR_PULSE_PENDING"
    printf '%s\n' "$meta" >"$PR_PULSE_PENDING/$(pp_key "$url").json"
  fi
fi

# 6. Drafts are skipped unless PR_PULSE_INCLUDE_DRAFTS=1.
if [ "$draft" = true ] && [ "${PR_PULSE_INCLUDE_DRAFTS:-0}" != 1 ]; then
  emit_notice "pr-pulse: draft PR not announced. It will be announced when you run gh pr ready."
fi

# 7. Webhook missing: tell Claude to tell the user, and stop there.
if ! pp_can_post; then
  emit_context "pr-pulse is ON here and a PR was opened ($url), but Slack is not set up for announcements, so it was not announced. Tell the user this in one short sentence and suggest /pr-pulse:init. Do not try to post it another way and do not ask for any token or URL."
fi

# 8. Record the PR: if no announcement is saved for it, the daemon notifies the user, so a
#    missed announcement is never silent.
"$HERE/pr-pulse" announce open "$url" "$sid" "$title" >/dev/null 2>&1 || true

# 9. Hand over to Claude: write the summary and save it. The daemon posts it; the session never
#    writes to Slack itself (auto mode blocks outside writes a hook asked for).
guide="$(cat "$HERE/../prompts/summary-guide.md" 2>/dev/null || true)"
nl=$'\n'
facts="PR: $url"
[ -z "$title" ] || facts="$facts${nl}Title: $title"
[ -z "$size" ] || facts="$facts${nl}Size: $size"
[ "$kind" != ready ] || facts="$facts${nl}Event: this draft was just marked ready for review"

ctx="pr-pulse is ON here (this session, worktree or mapped repo) and a pull request was just opened.
$facts

Write its announcement for Slack $PR_PULSE_CHANNEL now, before you continue with anything else:
1. Write the announcement text by following the guide below. Base it on what you know about this change from this session.
2. Save it with exactly one Bash call, with the text on stdin. This only saves it on this Mac; the pr-pulse service posts it within a minute:
$HERE/pr-pulse announce $url <<'PR_PULSE_EOF'
<announcement text>
PR_PULSE_EOF
3. If the output starts with \"saved\", say \"Announcement saved; pr-pulse posts it in $PR_PULSE_CHANNEL within a minute.\" and carry on. Anything else (\"NOT POSTED YET\", an error, or the call was blocked): tell the user that in one line right away, with what the output says to do. Do not retry and do not post it another way.

$guide"

emit_context "$ctx"
