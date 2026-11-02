#!/usr/bin/env bash
# generated-fresh.sh — fail when generated files are stale.
#
# Usage: generated-fresh.sh '<generator command>' <path>...
#
# Hashes the given files and folders, runs the generator, hashes again, and fails only if
# the hash changed. It does not diff against HEAD: that would fail on freshly regenerated,
# not-yet-committed files, which is every commit of an API change. The regenerated files
# are left in the tree, unstaged, for the caller to review and stage.
set -uo pipefail

[ $# -ge 2 ] || { echo "usage: $0 '<generator command>' <path>..." >&2; exit 2; }
gen=$1; shift

if command -v sha256sum >/dev/null 2>&1; then sum() { sha256sum; }; else sum() { shasum -a 256; }; fi
hash_paths() {
  # Missing paths hash as empty, so a generator that creates them reads as "stale".
  { find "$@" -type f -print0 2>/dev/null | LC_ALL=C sort -z | xargs -0 cat 2>/dev/null
    find "$@" -type f 2>/dev/null | LC_ALL=C sort; } | sum
}

before=$(hash_paths "$@")
bash -c "$gen" </dev/null || { echo "generated-fresh: the generator failed: $gen"; exit 1; }
after=$(hash_paths "$@")
if [ "$before" != "$after" ]; then
  echo "Generated files were stale; regenerated:"
  git status --short -- "$@"
  exit 1
fi
echo "generated files fresh"
