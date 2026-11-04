#!/usr/bin/env bash
# make-eval-plugin.sh <out-dir> - build a one-skill plugin for `claude plugin eval`.
#
# The repository root is a marketplace (marketplace.json), not a plugin with a plugin.json, so
# `claude plugin eval` cannot target it. This copies the system-design skill, its reviewer agent
# and these evals into <out-dir> as a plugin named "skills" (so the reviewer resolves as
# skills:system-design-reviewer, as it does when the real plugin is installed). Only this skill is
# loaded in the with-skill arm.
#
# Then: cd <out-dir> && claude plugin eval . --tag smoke --runs 1 \
#         --allow-tools Write Edit Bash Agent --scaffold --no-publish
set -euo pipefail
out="${1:?usage: make-eval-plugin.sh <out-dir>}"
here="$(cd "$(dirname "$0")" && pwd)"
skill="$(dirname "$here")"
repo="$(cd "$skill/../.." && pwd)"
case "$out" in "$repo"|"$repo"/*) echo "make-eval-plugin: put <out-dir> outside the repository" >&2; exit 64 ;; esac
rm -rf "$out"
mkdir -p "$out/.claude-plugin" "$out/skills" "$out/agents"
printf '{\n  "name": "skills",\n  "version": "0.0.0-eval",\n  "description": "system-design under evaluation"\n}\n' \
  > "$out/.claude-plugin/plugin.json"
rsync -a --exclude evals --exclude __pycache__ "$skill/" "$out/skills/system-design/"
cp "$repo/agents/system-design-reviewer.md" "$out/agents/"
rsync -a --exclude results "$here/" "$out/evals/"
echo "eval plugin ready: $out"
