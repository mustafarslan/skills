#!/usr/bin/env bash
# git-context.sh — the repo facts every git skill (rebase, commit, pr-merge, pr-upsert)
# needs before it runs a command, printed as key=value lines.
#
#   branch=<current branch, empty when HEAD is detached>
#   push_remote=<remote the current branch is pushed to>
#   base_remote=<remote that holds the base branches: upstream in a fork checkout, else push_remote>
#   default_branch=<the base remote's default branch, e.g. main or master>
#   base_repo=<owner/name of the base remote on GitHub, or empty when it is not a GitHub URL>
#   gh=<yes|no — gh is installed, logged in, and this checkout is a GitHub repository>
#   facts=<path of .claude/project-facts.md, or "missing">
#
# Remotes: push_remote is `origin` when it exists, else the only remote. base_remote is
# `upstream` when it exists (the usual fork layout: origin = your fork, upstream = the
# project), else push_remote. A repo with several remotes and neither name prints
# CONTEXT_FAILED and stops; the caller asks the user.
#
# Exit 0 on success; 1 with CONTEXT_FAILED: <reason> on stdout when a fact cannot be found.
# Read-only: it fetches nothing (the callers fetch). Without a local remote HEAD it asks gh, then
# `git remote show`, which contacts the remote but changes no ref.
set -uo pipefail
export LC_ALL=C   # `git remote show` output is parsed below

fail() { echo "CONTEXT_FAILED: $*"; exit 1; }

top=$(git rev-parse --show-toplevel 2>/dev/null) || fail "not inside a git work tree"
cd "$top" || fail "cannot cd to $top"

branch=$(git branch --show-current 2>/dev/null || true)

remotes=$(git remote)
[ -n "$remotes" ] || fail "this repository has no git remote"
if printf '%s\n' "$remotes" | grep -qx origin; then
  push_remote=origin
elif [ "$(printf '%s\n' "$remotes" | grep -c .)" -eq 1 ]; then
  push_remote=$remotes
else
  fail "several remotes and none is named origin: $(printf '%s ' $remotes)— ask which one to push to"
fi
if printf '%s\n' "$remotes" | grep -qx upstream; then base_remote=upstream; else base_remote=$push_remote; fi

# Default branch: the local symbolic ref first (no network), then gh, then ask the remote.
default_branch=$(git symbolic-ref --quiet --short "refs/remotes/$base_remote/HEAD" 2>/dev/null || true)
default_branch=${default_branch#"$base_remote"/}
gh_ok=no
# yes only when gh is logged in AND resolves this checkout to a GitHub repository.
if command -v gh >/dev/null 2>&1 && gh repo view --json name >/dev/null 2>&1; then gh_ok=yes; fi
if [ -z "$default_branch" ] && [ "$gh_ok" = yes ]; then
  default_branch=$(gh repo view --json defaultBranchRef -q .defaultBranchRef.name 2>/dev/null || true)
fi
if [ -z "$default_branch" ]; then
  default_branch=$(git remote show "$base_remote" 2>/dev/null | sed -n 's/^ *HEAD branch: //p' | head -1)
  [ "$default_branch" = "(unknown)" ] && default_branch=
fi
[ -n "$default_branch" ] || fail "cannot tell the default branch of $base_remote (no remote HEAD, gh unavailable, remote unreachable)"

# owner/name from git@github.com:o/r(.git), ssh://git@github.com/o/r, https://github.com/o/r(.git)
base_url=$(git remote get-url "$base_remote" 2>/dev/null || true)
base_repo=$(printf '%s\n' "$base_url" | sed -nE 's#^(git@|ssh://git@|https://([^@/]+@)?)github\.com[:/]([^/]+/[^/]+)$#\3#p' | sed 's/\.git$//')

facts="$top/.claude/project-facts.md"
[ -f "$facts" ] || facts=missing

printf 'branch=%s\npush_remote=%s\nbase_remote=%s\ndefault_branch=%s\nbase_repo=%s\ngh=%s\nfacts=%s\n' \
  "$branch" "$push_remote" "$base_remote" "$default_branch" "$base_repo" "$gh_ok" "$facts"
