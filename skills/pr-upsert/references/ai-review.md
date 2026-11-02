# Step 11c — requesting an AI review

Only reached when CI is green (11a) and no bot feedback is unaddressed this cycle (11b).
Below, `TRIGGER` is the facts' `AI review trigger` (e.g. `@claude review`) and `MARKER` is the
sticky comment's HTML marker (e.g. `<!-- claude-review -->`); substitute both. `NUMBER` is the
PR number, and `BASE_REPO` the PR's repository (`owner/name`, from Step 0).

This step assumes a repo workflow (e.g. a Claude review GitHub Action) that works two ways:
- A fresh trigger comment (the facts' `AI review trigger`, e.g. `@claude review`) starts the **first** review.
- The workflow then maintains a **single sticky comment** (author `github-actions[bot]`, marked
  with an HTML comment such as `<!-- claude-review -->`) carrying the review output plus a
  `- [ ] Re-run review` checkbox. A re-run is triggered by **ticking that checkbox** (editing
  `- [ ]` → `- [x]`), which fires the workflow's `issue_comment: edited` path — **not** by posting
  another trigger comment (a second trigger piles up and re-runs against the same state anyway).

If the facts say `AI review trigger: none`, or the repo has no such workflow, skip 11c and say so. Otherwise branch on whether the sticky
comment already exists. **First, find it:**

```bash
sticky_id=$(gh api --paginate "repos/BASE_REPO/issues/NUMBER/comments" \
  --jq '.[] | select(.user.login=="github-actions[bot]" and (.body|contains("MARKER"))) | .id' | head -1)
echo "sticky_id=${sticky_id:-none}"
```

**Case 1 — sticky comment exists (reviewed before): re-run by ticking the checkbox.** Only tick
when the box is currently unticked; an already-`[x]` box means a re-run is already queued, so
skip and say so. (The `grep` pattern starts with `-`, so pass `--` to stop option parsing.)

```bash
if [ -z "$sticky_id" ] || [ "$sticky_id" = "none" ]; then
  echo "no sticky comment — use Case 2"
else
  body=$(gh api "repos/BASE_REPO/issues/comments/$sticky_id" --jq '.body')
  if printf '%s' "$body" | grep -qF -- '- [ ] Re-run review'; then
    new_body=$(printf '%s' "$body" | sed 's/- \[ \] Re-run review/- [x] Re-run review/')
    if gh api "repos/BASE_REPO/issues/comments/$sticky_id" -X PATCH -f body="$new_body" >/dev/null; then
      echo "re-run requested"
    else
      echo "re-run NOT requested: editing the sticky comment failed (no write access?)"
    fi
  else
    echo "re-run already pending"
  fi
fi
```

The workflow acknowledges the re-run with a 👀 reaction and, when the new review finishes,
rewrites the sticky comment with a fresh **unticked** box.

**Case 2 — no sticky comment (`sticky_id=none`): post the first request.** Guard against
double-triggering a first review that's already in flight for the current commit — don't re-post
the trigger if a trigger comment exists newer than the latest commit. The body match is anchored
(`^@claude review`) so a bot summary that merely quotes the phrase doesn't trip it, explicitly
sorted because `gh` doesn't guarantee comment order, and the commit time is forced to UTC `Z` so
both sides of the lexical compare are UTC (plain `git log --format=%cI` emits the committer's
*local* offset, which would compare wrong against `gh`'s UTC `createdAt`):

```bash
last_commit_iso=$(TZ=UTC git log -1 --date=format-local:'%Y-%m-%dT%H:%M:%SZ' --format=%cd HEAD)
latest_request=$(gh pr view NUMBER --repo BASE_REPO --json comments \
  -q '[.comments[] | select(.body | test("^TRIGGER"; "i")) | .createdAt] | sort | last')
if [ "$latest_request" = "null" ] || [ -z "$latest_request" ] || [[ "$latest_request" < "$last_commit_iso" ]]; then
  gh pr comment NUMBER --repo BASE_REPO --body "TRIGGER"
  echo "requested"
else
  echo "already-requested"
fi
```

The lexical `<` compare is valid only because both operands are same-format UTC ISO-8601. A
request created in the *same second* as the commit compares `<`-false → `already-requested`,
which is the safe direction (favor not duplicating).

Then tell the user what happened (review requested / re-run ticked / already pending); the review
posts asynchronously and they can address it on the next cycle (re-invoke this skill or Step 11).
**Do not** poll for the review here — one watch cycle per invocation.
