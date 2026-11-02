#!/usr/bin/env bash
# local-checks.sh — run a repository's local checks: the ones a clean git merge or rebase
# cannot catch (a second migration head, a stale generated file), and on request the
# project's full local suite. Shared by the rebase and commit skills.
#
# Usage: local-checks.sh [--full]
#   (no flag)  the `### quick` checks from the repo's project facts
#   --full     the `### quick` checks, then the `### full` checks
#
# Where the checks come from, first match wins:
#   1. <repo>/.claude/local-checks.sh — the repo's own script; run with the same flag.
#   2. <repo>/.claude/project-facts.md, its `## checks` section:
#
#        ## checks
#        ### quick
#        - migration-head: `alembic heads | grep -c . | grep -qx 1`
#        ### full
#        - lint: `npm run lint`
#        - test: `npm test`
#
#      One check per line, `- <name>: `<command>``. A section that says `none` means the
#      project has no local checks.
#
# Each command runs with bash from the repository root. Every check runs even after one
# fails. $GIT_SKILLS_SCRIPTS points at this folder, so a facts line can call the helpers
# here, e.g. `"$GIT_SKILLS_SCRIPTS/generated-fresh.sh" 'npm run gen:api' api/generated`.
#
# Last line of output, and exit code:
#   LOCAL_CHECKS_OK <mode>             0  every check passed
#   LOCAL_CHECKS_NONE                  0  the project says it has no local checks
#   LOCAL_CHECKS_FAILED: <names>       1  at least one check failed
#   NO_PROJECT_FACTS                   3  no facts file and no repo script: ask the user, then
#                                         write .claude/project-facts.md (see the template)
#   NO_CHECKS_SECTION                  3  the facts file has no `## checks` section
#   MALFORMED_CHECKS                   3  a line under ### quick/full is not a check; fix the
#                                         file (do not rewrite it from scratch)
#   usage error                        2
set -uo pipefail

mode=${1:-}
case "$mode" in
  ''|--full) ;;
  *) echo "usage: $0 [--full]" >&2; exit 2 ;;
esac

GIT_SKILLS_SCRIPTS=$(cd "$(dirname "$0")" && pwd)
export GIT_SKILLS_SCRIPTS
top=$(git rev-parse --show-toplevel 2>/dev/null) || { echo "local-checks: not in a git work tree" >&2; exit 2; }
cd "$top" || exit 2

if [ -f .claude/local-checks.sh ]; then
  echo "== using the repository's own .claude/local-checks.sh"
  exec bash .claude/local-checks.sh ${mode:+"$mode"}
fi

facts=.claude/project-facts.md
[ -f "$facts" ] || { echo "NO_PROJECT_FACTS"; exit 3; }

# The `## checks` section, up to the next `## ` heading, with <!-- --> comments removed (they
# may span lines), so a comment can never be read as part of a command.
if ! grep -qE '^## +checks[[:space:]]*$' "$facts"; then echo "NO_CHECKS_SECTION"; exit 3; fi
section=$(awk '
  { line = $0; out = ""
    while (line != "") {
      if (incom) { i = index(line, "-->"); if (i == 0) { line = "" } else { line = substr(line, i + 3); incom = 0 } }
      else { i = index(line, "<!--"); if (i == 0) { out = out line; line = "" } else { out = out substr(line, 1, i - 1); line = substr(line, i + 4); incom = 1 } }
    }
    print out }' "$facts" | awk '/^## /{inside = ($0 ~ /^## +checks[[:space:]]*$/); next} inside')

# tier<TAB>name<TAB>command for every `- name: `command`` line under ### quick / ### full.
# Any other non-blank line under a tier (except `none`) is malformed: say so rather than skip it.
rows=$(printf '%s\n' "$section" | awk '
  /^### +quick[[:space:]]*$/ {tier = "quick"; next}
  /^### +full[[:space:]]*$/  {tier = "full"; next}
  /^### / {tier = ""; next}
  tier == "" {next}
  { line = $0; sub(/[[:space:]]+$/, "", line) }
  line == "" {next}
  tolower(line) ~ /^[-* ]*none$/ {next}
  line ~ /^- [A-Za-z0-9_.-]+: `.*`$/ {
    name = line; sub(/^- /, "", name); sub(/:.*/, "", name)
    cmd = line; sub(/^- [A-Za-z0-9_.-]+: `/, "", cmd); sub(/`$/, "", cmd)
    printf "%s\t%s\t%s\n", tier, name, cmd; next
  }
  { printf "MALFORMED\t%s\n", line }')

if printf '%s\n' "$rows" | grep -q '^MALFORMED'; then
  echo "local-checks: lines under ## checks that are not \`- name: \`command\`\`:" >&2
  printf '%s\n' "$rows" | sed -n 's/^MALFORMED\t/  /p' >&2
  echo "MALFORMED_CHECKS"; exit 3
fi

if [ -z "$rows" ]; then
  if printf '%s\n' "$section" | grep -qiE '^[-* ]*none([^a-z]|$)'; then echo "LOCAL_CHECKS_NONE"; exit 0; fi
  echo "local-checks: the ## checks section lists no check in the \`- name: \`command\`\` form" >&2
  echo "NO_CHECKS_SECTION"; exit 3
fi

failed=""
ran=0
while IFS=$'\t' read -r tier name cmd; do
  [ "$tier" = full ] && [ "$mode" != --full ] && continue
  ran=$((ran + 1))
  echo "== $name: $cmd"
  if bash -c "$cmd" </dev/null; then echo "-- $name: ok"; else echo "-- $name: FAILED"; failed="$failed $name"; fi
done <<<"$rows"

if [ "$ran" -eq 0 ]; then echo "LOCAL_CHECKS_NONE"; exit 0; fi
if [ -n "$failed" ]; then echo "LOCAL_CHECKS_FAILED:$failed"; exit 1; fi
echo "LOCAL_CHECKS_OK ${mode:-quick}"
