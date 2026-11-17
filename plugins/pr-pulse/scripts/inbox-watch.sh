#!/usr/bin/env bash
# inbox-watch.sh [session_id] — run under the Monitor tool by a session that takes pr-pulse work.
# Prints one line per new job in ~/.claude/pr-pulse/inbox/<sid>.jsonl; each line wakes the session.
# Touches <sid>.live every 5 s so the daemon knows a watcher is listening. One watcher per session.
set -uo pipefail
# shellcheck source=forward.sh disable=SC1091
source "$(dirname "${BASH_SOURCE[0]}")/forward.sh" "$@"
sid="${1:-${CLAUDE_CODE_SESSION_ID:-}}"
[[ "$sid" =~ ^[A-Za-z0-9._-]+$ ]] || { echo "pr-pulse watch: no valid session id"; exit 1; }
home="${PR_PULSE_HOME:-$HOME/.claude/pr-pulse}"
dir="$home/inbox"; mkdir -p "$dir"
f="$dir/$sid.jsonl"; off="$dir/$sid.offset"; live="$dir/$sid.live"; pidf="$dir/$sid.pid"
touch "$f"
if [ -f "$pidf" ] && kill -0 "$(cat "$pidf" 2>/dev/null)" 2>/dev/null; then
  echo "pr-pulse watch: already watching for this session (pid $(cat "$pidf")); nothing to do"
  exit 0
fi
echo $$ >"$pidf"
trap 'rm -f "$pidf" "$live"' EXIT
trap 'exit 0' INT TERM   # exit runs the EXIT trap; a bare cleanup trap would keep looping
# Start after what is already there, unless jobs were delivered while nobody watched.
seen="$(cat "$off" 2>/dev/null || echo 0)"
# No "armed" line: every line wakes the session, and the Monitor is re-armed every 30 minutes,
# so an armed line made an idle session take a turn (and look busy) for nothing.
while true; do
  : >"$live"
  total="$(wc -l <"$f" | tr -d ' ')"
  if [ "$total" -gt "$seen" ]; then
    tail -n +"$((seen + 1))" "$f" | head -n "$((total - seen))" | while IFS= read -r line; do
      if command -v jq >/dev/null 2>&1; then
        jq -r 'if .answer then "pr-pulse: answer to question \(.answer) (job \(.job)): \(.text)"
               else "pr-pulse: job \(.job) — \(.action) for \(.ref). Run `pr-pulse job show \(.job)` and follow it." end' <<<"$line" 2>/dev/null \
          || echo "pr-pulse: new job: $line"
      else
        echo "pr-pulse: new job: $line"
      fi
    done
    seen="$total"; echo "$seen" >"$off"
  fi
  sleep 5
done
