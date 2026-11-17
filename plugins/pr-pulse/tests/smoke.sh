#!/usr/bin/env bash
# Offline smoke test: pipes fake hook events into the scripts. Sends nothing to Slack.
# Run from anywhere: bash tests/smoke.sh
export PR_PULSE_ENV_FILE=/nonexistent PR_PULSE_CONFIG=/nonexistent
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
S="$ROOT/scripts"
export PR_PULSE_HOME; PR_PULSE_HOME="$(mktemp -d)"
export PR_PULSE_NO_GH=1                 # don't call the real gh
REPO="$(mktemp -d)"; git -C "$REPO" init -q
SID="test-session-1"
URL="https://github.com/acme/sandbox/pull/42"
pass=0 fail=0
check() { if eval "$2"; then echo "ok   $1"; pass=$((pass+1)); else echo "FAIL $1"; fail=$((fail+1)); fi; }

expand() { jq -nc --arg p "$1" --arg s "$2" --arg c "$REPO" \
  '{session_id:$s, cwd:$c, hook_event_name:"UserPromptExpansion", expansion_type:"slash_command",
    command_name:($p|ltrimstr("/")|split(" ")[0]), command_args:($p|split(" ")[1:]|join(" ")),
    command_source:"plugin", prompt:$p}'; }
bash_event() { jq -nc --arg cmd "$1" --arg out "$2" --arg s "$3" --arg c "$REPO" \
  '{session_id:$s, cwd:$c, hook_event_name:"PostToolUse", tool_name:"Bash",
    tool_input:{command:$cmd}, tool_response:{stdout:$out, stderr:"", interrupted:false, isImage:false}}'; }

create="gh pr create --title 'Add thing' --body 'Body'"

out="$(bash_event "$create" "$URL" "$SID" | PR_PULSE_SLACK_WEBHOOK_URL=https://hooks.slack.com/x "$S/on-pr-created.sh")"
check "off session does nothing" '[ -z "$out" ]'
check "the opening session is recorded even with pr-pulse off" '[ "$(sqlite3 "$PR_PULSE_HOME/pulse.db" "SELECT sid FROM pr_origin WHERE url='"'"'$URL'"'"'")" = "$SID" ]'

out="$(expand "/pr-pulse:on" "$SID" | "$S/toggle.sh")"
check "toggle on blocks prompt with a message" 'jq -e ".decision==\"block\" and (.reason|test(\"ON for this session\"))" <<<"$out" >/dev/null'

out="$(expand "/pr-pulse:status" "$SID" | "$S/toggle.sh")"
check "status reports ON" 'jq -e ".reason|test(\"is ON\")" <<<"$out" >/dev/null'

out="$(expand "/other-plugin:status" "$SID" | "$S/toggle.sh")"
check "other plugins' commands are ignored" '[ -z "$out" ]'

out="$(bash_event "$create" "$URL" "$SID" | PR_PULSE_SLACK_WEBHOOK_URL=https://hooks.slack.com/x "$S/on-pr-created.sh")"
check "gh pr create asks Claude to save the announcement" 'jq -e ".hookSpecificOutput.additionalContext|test(\"pr-pulse announce https://github.com/acme/sandbox/pull/42\")" <<<"$out" >/dev/null'
check "the hook never asks the session to post to Slack itself" '! jq -e ".hookSpecificOutput.additionalContext|test(\"post.sh\")" <<<"$out" >/dev/null'
check "the hook records the opened PR for the unannounced backstop" '[ "$(sqlite3 "$PR_PULSE_HOME/pulse.db" "SELECT state FROM announcements WHERE url='"'"'$URL'"'"'")" = open ]'

out="$(bash_event "$create" "$URL" "$SID" | env -u PR_PULSE_SLACK_WEBHOOK_URL "$S/on-pr-created.sh")"
check "missing webhook variable is reported" 'jq -e ".hookSpecificOutput.additionalContext|test(\"not set\")" <<<"$out" >/dev/null'

out="$(bash_event "gh pr create --draft --title x" "$URL" "$SID" | PR_PULSE_SLACK_WEBHOOK_URL=https://hooks.slack.com/x "$S/on-pr-created.sh")"
check "draft is skipped with a notice" 'jq -e ".systemMessage|test(\"draft\")" <<<"$out" >/dev/null'

out="$(bash_event "gh pr create --title x" "could not create: no commits" "$SID" | "$S/on-pr-created.sh")"
check "no URL in output means no post" '[ -z "$out" ]'

out="$(printf 'Contract exports now follow org access rules & <stay> fast.\n' | "$S/post.sh" --url "$URL" --title "Enforce | access" --dry-run)"
check "post.sh builds escaped Slack payload" 'head -n1 <<<"$out" | jq -e ".text|test(\"&amp; &lt;stay&gt;\") and test(\"<https://github.com/acme/sandbox/pull/42\\\\|sandbox#42: Enforce / access>\")" >/dev/null'

out="$(printf 'x\n' | env -u PR_PULSE_SLACK_WEBHOOK_URL "$S/post.sh" --url "$URL" 2>&1 || echo "exit=$?")"
check "post.sh exits 3 without webhook" 'grep -q "exit=3" <<<"$out"'

USERCFG="$(mktemp)"; printf '{"post_as":"user","announce_channel":"C1","my_name":"Ada"}' >"$USERCFG"
out="$(printf 'x\n' | PR_PULSE_CONFIG="$USERCFG" PR_PULSE_SLACK_BOT_TOKEN=xoxb-bot PR_PULSE_SLACK_WEBHOOK_URL=https://hooks.slack.com/x \
       env -u PR_PULSE_SLACK_USER_TOKEN "$S/post.sh" --url "$URL" 2>&1 || echo "exit=$?")"
check "post_as user without a user token never falls back to the bot or webhook" 'grep -q "exit=3" <<<"$out" && grep -q "user token" <<<"$out"'
out="$(printf 'x\n' | PR_PULSE_CONFIG="$USERCFG" PR_PULSE_SLACK_USER_TOKEN=xoxp-me "$S/post.sh" --url "$URL" --dry-run)"
check "post_as user drops the '· name' suffix" 'head -n1 <<<"$out" | jq -e "(.text|test(\"Ada\")|not) and .channel==\"C1\"" >/dev/null'
rm -f "$USERCFG"

printf '%s\t%s\n' "$URL" now >>"$PR_PULSE_HOME/posted.tsv"
out="$(bash_event "$create" "$URL" "$SID" | PR_PULSE_SLACK_WEBHOOK_URL=https://hooks.slack.com/x "$S/on-pr-created.sh")"
check "already-posted PR is not announced again" '[ -z "$out" ]'

out="$(expand "/pr-pulse:off" "$SID" | "$S/toggle.sh")"
check "toggle off" 'jq -e ".reason|test(\"OFF\")" <<<"$out" >/dev/null'

out="$(expand "/pr-pulse:on worktree" "other-session" | "$S/toggle.sh")"
out2="$(bash_event "$create" "https://github.com/acme/sandbox/pull/43" "brand-new-session" | PR_PULSE_SLACK_WEBHOOK_URL=https://hooks.slack.com/x "$S/on-pr-created.sh")"
check "worktree mode covers new sessions in the same worktree" 'jq -e ".hookSpecificOutput.additionalContext" <<<"$out2" >/dev/null'

out="$(printf 'not json' | "$S/on-pr-created.sh"; echo "exit=$?")"
check "garbage input still exits 0" 'grep -q "exit=0" <<<"$out"'
out="$(printf '%s' '{"prompt":"/pr-pulse:help","session_id":"","cwd":"/tmp"}' | "$S/toggle.sh")"
check "help answers instantly, without a session id" 'jq -e ".decision == \"block\" and (.reason|test(\"COMMANDS\")) and (.reason|test(\"README.md\"))" <<<"$out" >/dev/null'

rm -rf "$PR_PULSE_HOME" "$REPO"
echo "$pass passed, $fail failed"
[ "$fail" -eq 0 ]
