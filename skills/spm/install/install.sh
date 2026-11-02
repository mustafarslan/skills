#!/bin/sh
# Install spm for this user: the skill, its red-team agent, the "spm" prompt trigger, and the
# Skill(spm) permission. Installed once, it works in every project.
# Safe to run again (it replaces the skill and never adds the trigger or permission twice).
#
# Runs from either layout:
#   the PM's zip:    spm/install.sh, with spm/spm/ (the skill), spm/agents/, spm/hooks/
#   this repository: skills/spm/install/install.sh, with the agent in agents/ at the repo root
#
# Usage: sh install.sh [--no-trigger]
#   --no-trigger   skip the UserPromptSubmit hook that loads spm when a prompt says "spm";
#                  /spm still works.
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
CLAUDE="$HOME/.claude"

TRIGGER=1
for arg in "$@"; do
  case "$arg" in
    --no-trigger) TRIGGER=0 ;;
    *) echo "install.sh: unknown option $arg" >&2; exit 64 ;;
  esac
done

if [ -f "$HERE/spm/SKILL.md" ]; then          # the PM's zip
  SKILL_SRC="$HERE/spm"
  AGENT_SRC="$HERE/agents/spm-red-team.md"
  TRIGGER_SRC="$HERE/hooks/spm-trigger.py"
elif [ -f "$HERE/../SKILL.md" ]; then         # this repository
  SKILL_SRC=$(cd "$HERE/.." && pwd)
  AGENT_SRC=$(cd "$HERE/../../.." && pwd)/agents/spm-red-team.md
  TRIGGER_SRC="$SKILL_SRC/hooks/spm-trigger.py"
else
  echo "install.sh: cannot find the spm skill next to this script" >&2; exit 1
fi
for f in "$SKILL_SRC/scripts/check_spec.py" "$AGENT_SRC" "$TRIGGER_SRC"; do
  [ -f "$f" ] || { echo "install.sh: $f is missing - run this from a full copy" >&2; exit 1; }
done

command -v python3 >/dev/null 2>&1 || { echo "spm needs python3 (on macOS: xcode-select --install)"; exit 1; }
command -v git >/dev/null 2>&1 || { echo "spm needs git"; exit 1; }

mkdir -p "$CLAUDE/skills" "$CLAUDE/agents" "$CLAUDE/hooks"
rm -rf "$CLAUDE/skills/spm"
cp -R "$SKILL_SRC" "$CLAUDE/skills/spm"
# The PM's install needs neither the test suite nor the installers inside the skill folder.
rm -rf "$CLAUDE/skills/spm/tests" "$CLAUDE/skills/spm/install"
find "$CLAUDE/skills/spm" -name '__pycache__' -type d -prune -exec rm -rf {} +
cp "$AGENT_SRC" "$CLAUDE/agents/spm-red-team.md"
[ "$TRIGGER" = 1 ] && cp "$TRIGGER_SRC" "$CLAUDE/hooks/spm-trigger.py"

SETTINGS="$CLAUDE/settings.json"
[ -f "$SETTINGS" ] && cp "$SETTINGS" "$SETTINGS.bak-spm-$(date +%Y%m%d%H%M%S)"
python3 -I - "$SETTINGS" "$TRIGGER" <<'PY'
import json, os, sys
path, trigger = sys.argv[1], sys.argv[2] == '1'
data = {}
if os.path.exists(path):
    with open(path, encoding='utf-8') as fh:
        text = fh.read().strip()
    data = json.loads(text) if text else {}
if trigger:
    command = 'python3 "$HOME/.claude/hooks/spm-trigger.py"'
    groups = data.setdefault('hooks', {}).setdefault('UserPromptSubmit', [])
    if not any(h.get('command') == command for g in groups for h in g.get('hooks', [])):
        groups.append({'hooks': [{'type': 'command', 'command': command, 'timeout': 5}]})
# Pre-approve loading the skill: if the load prompt were declined, its leak gate would not run.
allow = data.setdefault('permissions', {}).setdefault('allow', [])
if 'Skill(spm)' not in allow:
    allow.append('Skill(spm)')
with open(path, 'w', encoding='utf-8') as fh:
    json.dump(data, fh, indent=2, ensure_ascii=False)
    fh.write('\n')
PY
if [ "$TRIGGER" = 1 ]; then
  echo "spm installed. Start a new Claude Code session, then type /spm or say \"spm\"."
else
  echo "spm installed (no prompt trigger). Start a new Claude Code session, then type /spm."
fi
