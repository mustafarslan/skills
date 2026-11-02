#!/bin/sh
# Remove spm: the skill, its red-team agent, the "spm" prompt trigger and its permission.
# Touches nothing else in ~/.claude/settings.json (a backup is written first).
set -eu
CLAUDE="$HOME/.claude"
rm -rf "$CLAUDE/skills/spm"
rm -f "$CLAUDE/agents/spm-red-team.md" "$CLAUDE/hooks/spm-trigger.py"
SETTINGS="$CLAUDE/settings.json"
if [ -f "$SETTINGS" ]; then
  cp "$SETTINGS" "$SETTINGS.bak-spm-$(date +%Y%m%d%H%M%S)"
  python3 -I - "$SETTINGS" <<'PY'
import json, sys
path = sys.argv[1]
with open(path, encoding='utf-8') as fh:
    data = json.load(fh)
command = 'python3 "$HOME/.claude/hooks/spm-trigger.py"'
groups = data.get('hooks', {}).get('UserPromptSubmit', [])
for g in groups:
    g['hooks'] = [h for h in g.get('hooks', []) if h.get('command') != command]
if groups:
    data['hooks']['UserPromptSubmit'] = [g for g in groups if g.get('hooks')]
    if not data['hooks']['UserPromptSubmit']:
        del data['hooks']['UserPromptSubmit']
    if not data['hooks']:
        del data['hooks']
allow = data.get('permissions', {}).get('allow')
if allow and 'Skill(spm)' in allow:
    allow.remove('Skill(spm)')
with open(path, 'w', encoding='utf-8') as fh:
    json.dump(data, fh, indent=2, ensure_ascii=False)
    fh.write('\n')
PY
fi
echo "spm removed."
