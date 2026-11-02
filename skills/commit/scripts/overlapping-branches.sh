#!/usr/bin/env bash
# List other branches that change the same files as HEAD.
#
# Usage: overlapping-branches.sh [base]   (default base: <remote>/<its default branch>)
# Env:   OVERLAP_REMOTE — the remote holding teammates' branches and PRs (default: upstream
#                         in a fork checkout, else origin, else the only remote).
#        OVERLAP_DAYS — skip branches with no commit in this many days (default 14).
#        OVERLAP_IGNORE — extended regex of paths to ignore (default: common lockfiles).
# Needs: bash 3.2+ (macOS /bin/bash is fine), git 2.38+ (`merge-tree --write-tree`), and gh,
#        logged in. Without gh it exits 1 with a message: the check did not run.
#
# Candidates: open PRs, remote branches without a merged/closed PR, and local
# branches not on the remote. Output is TSV, one row per overlapping branch:
#   kind  branch  pr  login  author  draft  conflict  files  conflict_files
# kind: pr | branch | local. login: GitHub login; `-` for bots, local
# branches, and commits with no linked account. author: git author of the
# branch tip. conflict: yes when a trial merge with HEAD conflicts in one of
# HEAD's own files (`git merge-tree`; nothing is written to the tree);
# unknown when the trial merge itself failed. files: comma-separated shared
# files, conflicting or not. conflict_files: the subset that conflicts (the
# paths behind conflict=yes); `-` when none or unknown. Regenerated files are
# ignored: their clashes are fixed by rerunning the generator. Fork PRs have no
# ref on the remote, so they are not scanned, and are dropped from PR lookups so a
# same-named remote branch isn't matched to one.
# A remote branch whose local tip is ahead is scanned at the local tip.
# Branches stacked on HEAD (an open PR based on it, or a branch containing HEAD)
# are skipped: they hold HEAD's files by design.
# Errors go to stderr.
set -euo pipefail
export LC_ALL=C # `comm` needs `sort`'s collation

die() { echo "overlapping-branches: $*" >&2; exit 1; }
command -v gh >/dev/null 2>&1 || die "gh is not installed; the overlap check did not run"
gh auth status >/dev/null 2>&1 || die "gh is not logged in; the overlap check did not run"
git merge-tree --write-tree HEAD HEAD >/dev/null 2>&1 || die "git $(git --version | awk '{print $3}') has no 'merge-tree --write-tree' (needs 2.38+)"

if [ -n "${OVERLAP_REMOTE:-}" ]; then REMOTE=$OVERLAP_REMOTE
elif git remote | grep -qx upstream; then REMOTE=upstream
elif git remote | grep -qx origin; then REMOTE=origin
elif [ "$(git remote | grep -c .)" -eq 1 ]; then REMOTE=$(git remote)
else die "several remotes and none is named origin; set OVERLAP_REMOTE"; fi
DEFAULT=$(git symbolic-ref --quiet --short "refs/remotes/$REMOTE/HEAD" 2>/dev/null || true)
DEFAULT=${DEFAULT#"$REMOTE"/}
[ -n "$DEFAULT" ] || DEFAULT=$(gh repo view --json defaultBranchRef -q .defaultBranchRef.name 2>/dev/null || true)
[ -n "$DEFAULT" ] || die "cannot tell the default branch of $REMOTE; pass the base as an argument"
BASE=${1:-$REMOTE/$DEFAULT}
DAYS=${OVERLAP_DAYS:-14}
ME=$(git branch --show-current)
# Files whose clashes are fixed by rerunning a generator, so they are not blamed on anyone.
# Override with OVERLAP_IGNORE (an extended regex); the default covers common lockfiles.
GENERATED=${OVERLAP_IGNORE:-'(^|/)(package-lock\.json|yarn\.lock|pnpm-lock\.yaml|uv\.lock|poetry\.lock|Cargo\.lock|go\.sum)$'}
SINCE=$(( $(date +%s) - DAYS * 86400 ))
LIMIT=1000
REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null) || die "gh cannot resolve this checkout to a GitHub repository; the overlap check did not run"

# --prune drops branches deleted on merge, so they don't pass as unmerged work.
git fetch -q --prune "$REMOTE"

# --no-renames lists both paths of a rename, so a rename meets an edit of the old path.
changed() {
  local files
  files=$(git diff --name-only --no-renames "$BASE...$1") || return 1
  grep -Ev "$GENERATED" <<<"$files" | sort -u || true
}

MINE=$(changed HEAD) || { echo "overlapping-branches: git diff failed for HEAD" >&2; exit 1; }
[ -z "$MINE" ] && exit 0

# Conflicted paths from a trial merge, or exit 1 when the merge itself failed
# (exit 1 means conflicts; output is the tree OID, then conflicted paths).
conflicts() {
  local out rc=0
  out=$(git merge-tree --write-tree --name-only --no-messages HEAD "$1" 2>/dev/null) || rc=$?
  [[ $(head -1 <<<"$out") =~ ^[0-9a-f]{40,64}$ ]] || return 1
  [ "$rc" -ne 0 ] && tail -n +2 <<<"$out" | sort -u
  return 0
}

# HEAD's conflicts with the base itself come from main moving, not from
# another branch; a rebase surfaces them, so they are not blamed on anyone.
BASE_CONFLICTS=$(conflicts "$BASE") || {
  echo "overlapping-branches: trial merge with $BASE failed" >&2
  BASE_CONFLICTS=
}

# headRefName → "state<TAB>number<TAB>login<TAB>isDraft<TAB>baseRefName"; open PRs load last, so
# they win over an older closed PR from the same branch.
# No field may be empty: `read` merges consecutive tabs and would shift columns.
pr_rows() {
  gh pr list --repo "$REPO" --state "$1" --limit "$LIMIT" \
    --json headRefName,state,number,author,isDraft,isCrossRepository,baseRefName \
    -q '.[] | select(.isCrossRepository | not) | [.headRefName, .state, (.number|tostring),
               (if .author.is_bot then "-" else (.author.login // "-") end),
               (.isDraft|tostring), .baseRefName] | @tsv'
}
# Without the PR list every merged branch would read as live work.
OPEN_PRS=$(pr_rows open) || { echo "overlapping-branches: gh pr list failed" >&2; exit 1; }
[ "$(grep -c . <<<"$OPEN_PRS")" -ge "$LIMIT" ] &&
  echo "overlapping-branches: over $LIMIT open PRs; the rest are not scanned" >&2
# Holds only the newest $LIMIT closed PRs; closed_pr looks up the rest by name.
# `gh pr list --search "closed:>=…"` would be smaller but drops PRs.
DONE_PRS=$(pr_rows closed) || { echo "overlapping-branches: gh pr list failed" >&2; exit 1; }

# Exit 0 when the branch has a merged or closed PR, 1 when not, 2 when gh failed.
closed_pr() {
  local n
  n=$(gh pr list --repo "$REPO" --head "$1" --state closed --limit 100 \
    --json isCrossRepository -q 'map(select(.isCrossRepository | not)) | length') || return 2
  [ "$n" -gt 0 ]
}
# headRefName → its row, without bash 4's associative arrays: the last matching row wins, and
# open PRs come last.
ALL_PRS="$DONE_PRS"$'\n'"$OPEN_PRS"
pr_info() {
  awk -F'\t' -v h="$1" '$1 == h {row = $2 "\t" $3 "\t" $4 "\t" $5 "\t" $6} END {if (row != "") print row}' <<<"$ALL_PRS"
}

candidates() {
  git for-each-ref "refs/remotes/$REMOTE" --format='remote %(refname:lstrip=3) %(committerdate:unix)'
  git for-each-ref refs/heads --format='local %(refname:lstrip=2) %(committerdate:unix)'
}

while read -r where name ts; do
  [ "$name" = HEAD ] || [ "$name" = "$DEFAULT" ] || [ "$name" = "$ME" ] && continue
  info=$(pr_info "$name")
  state=${info%%$'\t'*}
  if [ "$where" = local ]; then
    # Pushed branches are covered by their remote ref.
    git show-ref -q --verify "refs/remotes/$REMOTE/$name" && continue
    ref="refs/heads/$name"
  else
    ref="refs/remotes/$REMOTE/$name"
  fi
  # A local tip ahead of the remote holds unpushed edits; scan it, keep $ref for identity.
  scan=$ref
  [ "$where" = remote ] && git show-ref -q --verify "refs/heads/$name" &&
    git merge-base --is-ancestor "$ref" "refs/heads/$name" && scan="refs/heads/$name"
  [ "$scan" = "$ref" ] || ts=$(git log -1 --format=%ct "$scan")
  # Merged or closed work no longer lands; open PRs count however old.
  [ -n "$info" ] && [ "$state" != OPEN ] && continue
  [ "$state" != OPEN ] && [ "$ts" -lt "$SINCE" ] && continue
  # A diff against $BASE would count every HEAD file as shared, and a rewritten
  # HEAD would read as a conflict.
  [ "$state" = OPEN ] && [ "${info##*$'\t'}" = "$ME" ] && continue
  git merge-base --is-ancestor HEAD "$scan" && continue

  theirs=$(changed "$scan") || { echo "overlapping-branches: git diff failed for $name" >&2; continue; }
  shared=$(comm -12 <(printf '%s\n' "$MINE") <(printf '%s\n' "$theirs"))
  [ -z "$shared" ] && continue
  if [ -z "$info" ]; then
    rc=0
    closed_pr "$name" || rc=$?
    [ "$rc" -eq 0 ] && continue
    [ "$rc" -eq 2 ] && echo "overlapping-branches: PR lookup failed for $name; listed as live" >&2
  fi

  cfiles=
  if ! hits=$(conflicts "$scan"); then
    conflict=unknown
    echo "overlapping-branches: trial merge failed for $name" >&2
  else
    cfiles=$(comm -23 <(comm -12 <(printf '%s\n' "$MINE") <(printf '%s\n' "$hits")) \
      <(printf '%s\n' "$BASE_CONFLICTS"))
    if [ -n "$cfiles" ]; then conflict=yes; else conflict=no; fi
  fi

  author=$(git log -1 --format=%an "$ref")
  if [ "$state" = OPEN ]; then
    IFS=$'\t' read -r _ num login draft _ <<<"$info"
    kind=pr
  elif [ "$where" = remote ]; then
    num=- draft=- kind=branch
    # A failed `gh api` prints its error JSON to stdout; accept only a login.
    if login=$(gh api "repos/$REPO/commits/$(git rev-parse "$ref")" \
      -q 'if .author.type == "Bot" then "-" else (.author.login // "-") end' 2>/dev/null); then
      [[ $login =~ ^[A-Za-z0-9-]+$ ]] || login=-
    else
      echo "overlapping-branches: login lookup failed for $name" >&2
      login=-
    fi
  else
    num=- draft=- login=- kind=local
  fi
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$kind" "$name" "$num" "$login" "$author" "$draft" "$conflict" \
    "$(echo "$shared" | paste -sd, -)" "$(echo "${cfiles:--}" | paste -sd, -)"
done < <(candidates)
