# spm — how it is wired into Claude Code

spm is installed **once per user** and then works in every project: the pack goes to whatever
folder the PM names, and the checker cross-checks against the repository Claude is running in
(or, failing that, the repository that holds the pack). Two ways to install it:

- **With this repository's plugin** (`/plugin install skills@mustafarslan-skills`): the skill and
  the `spm-red-team` agent come with the plugin. The prompt trigger is **not** registered, because
  a plugin-wide `UserPromptSubmit` hook would run for every plugin user. Type `/skills:spm`. If
  you want the word "spm" to load it too, copy `skills/spm/hooks/spm-trigger.py` to
  `~/.claude/hooks/` and register it by hand as in 2. below. Add `Skill(skills:spm)` to
  `permissions.allow` (see 3. below for why).
- **As a personal copy** with `sh skills/spm/install/install.sh` from a clone of this repository,
  or `sh spm/install.sh` from the PM's zip (built by `install/package.sh`). It does the wiring
  below. `--no-trigger` skips the prompt trigger.

## Files and where they go

| Repository path | Installed at | Purpose |
|---|---|---|
| `skills/spm/` (without `tests/` and `install/`) | `~/.claude/skills/spm/` | `SKILL.md`, `references/`, `scripts/check_spec.py`, `hooks/spm-trigger.py` |
| `agents/spm-red-team.md` | `~/.claude/agents/spm-red-team.md` | read-only reviewer agent (`tools: Read` only) |
| `skills/spm/hooks/spm-trigger.py` | `~/.claude/hooks/spm-trigger.py` | prompt trigger (skipped with `--no-trigger`) |
| (edits) | `~/.claude/settings.json` | trigger hook entry + `Skill(spm)` permission |

## The three hooks and permission

1. **Skill-scoped `PreToolUse` hook** — declared in the `hooks:` block of `SKILL.md`'s
   frontmatter, so it exists only once the skill is loaded:

   ```yaml
   hooks:
     PreToolUse:
       - matcher: "Write|Edit|MultiEdit|Bash"
         hooks:
           - type: command
             command: 'python3 "${CLAUDE_SKILL_DIR}/scripts/check_spec.py" --hook || exit 2'
             timeout: 60
   ```

   `|| exit 2` makes a crashed or missing checker **block** the tool call (fail closed).
   Claude Code replaces `${CLAUDE_SKILL_DIR}` with the skill's own folder, so the same line works
   for a plugin install and a copy install, from any working directory.
   **The hook stays active for the rest of the session** once the skill has loaded, so use a new
   session for unrelated work. Tell the PM this (the README does).

2. **`UserPromptSubmit` trigger** — `hooks/spm-trigger.py`, registered in `settings.json`:

   ```json
   {"hooks": {"UserPromptSubmit": [{"hooks": [
     {"type": "command", "command": "python3 \"$HOME/.claude/hooks/spm-trigger.py\"", "timeout": 5}]}]}}
   ```

   It reads `{"prompt": ...}` from stdin; if the prompt contains `spm`, `superpm` or
   `super-project-manager` as a standalone word (case-insensitive, not inside a longer word or
   hyphenated name) and does **not** start with `/spm`, it prints
   `{"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": "The user invoked spm: load the `spm` skill (Skill tool) and follow it for this request before acting."}}`.
   Any error: exit 0 silently — a broken trigger must never block a prompt.

3. **Permission `Skill(spm)`** added to `permissions.allow`. Reason: if the PM declined the
   "load this skill?" prompt, the skill's hook would never be installed and the leak gate would
   silently not run. Pre-approving removes that failure mode.

## Installer behaviour (`install/install.sh`)

- Finds the skill next to itself, in either layout (the PM's zip or this repository).
- Requires `python3` and `git` (else print a helpful message and exit 1).
- Creates `~/.claude/{skills,agents,hooks}`; **replaces** `~/.claude/skills/spm` (`rm -rf` then
  copy, leaving out `tests/` and `install/`). Local edits to the installed skill are lost on update.
- Backs up `settings.json` to `settings.json.bak-spm-<timestamp>` before touching it.
- Edits `settings.json` with a small Python snippet: **idempotent** (never adds the trigger or the
  permission twice), preserves everything else, tolerates a missing or empty file.

## Uninstaller (`install/uninstall.sh`)

Removes the skill folder, the agent, the trigger script; backs up `settings.json`; removes only
spm's own hook command and the `Skill(spm)` permission; deletes `UserPromptSubmit` or `hooks`
keys only if that leaves them empty.

## Packaging (`install/package.sh`): two zips for two audiences

- **`spm.zip` for the PM**: `spm/README.md` (from `install/PM-README.md`), `spm/spm/` (the skill),
  `spm/agents/`, `spm/hooks/`, `spm/install.sh`, `spm/uninstall.sh`. No tests.
- **`spm-verify.zip` for engineering**: only `check_spec.py`, `VERIFY.md`, and a
  `check_spec.py.sha256` file. Engineers compare the checksum **sent out of band** (in the
  handoff message), not the file inside the zip; a tampered zip could carry a tampered checksum.

## Tests

`python3 -I -m unittest discover -s skills/spm/tests` from the repository root.

## Testing a rebuild

Hooks persist for the whole session, so test in a throwaway session:

1. `claude -p` (headless) with a prompt that makes the model Write a leaky `stories.md`
   (marker on line 1, containing "the system stores…"): the write must be denied.
2. Ask it to write the same file with `cat > stories.md` in Bash: must be refused.
3. Check the install is idempotent: run `install.sh` twice, `settings.json` must hold one trigger
   entry and one permission.
4. Run `uninstall.sh`: `settings.json` must be back to its previous content (compare with the
   backup).
