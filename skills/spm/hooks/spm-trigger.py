#!/usr/bin/env python3
"""UserPromptSubmit hook: when the prompt says spm / superpm / super-project-manager, tell Claude
to load the spm skill. Silent otherwise."""
import json
import re
import sys

try:
    prompt = json.load(sys.stdin).get('prompt') or ''
except Exception:  # noqa: BLE001 - a broken trigger must never block the prompt
    sys.exit(0)
if re.search(r'(?<![\w-])(spm|superpm|super-project-manager)(?![\w-])', prompt, re.I) \
        and not prompt.lstrip().startswith('/spm'):
    print(json.dumps({'hookSpecificOutput': {
        'hookEventName': 'UserPromptSubmit',
        'additionalContext': 'The user invoked spm: load the `spm` skill (Skill tool) and follow it '
                             'for this request before acting.'}}))
sys.exit(0)
