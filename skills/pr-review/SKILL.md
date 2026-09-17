---
name: pr-review
description: Use when asked to review a PR, check or look over a PR, give a second opinion on someone's changes, or review the current branch before pushing.
argument-hint: "[PR number or URL, or nothing to review the current branch]"
allowed-tools: Bash, Read, Grep, Glob, Agent, ToolSearch, AskUserQuestion, mcp__linear-server__get_issue
---

# PR Review

Review as a senior engineer who maintains this codebase. Find what the author
missed — do not summarize the change.

This is the counterpart to `/pr-feedback`, which works the reviews on *your own*
PR. Same discipline from the other side of the table: there you verify the
reviewers' claims, here you verify the PR's. Same evidence bar, same
print-then-ask-then-post gate, and for the same reason — what gets posted lands
on someone else's PR under the user's name.

**Target:** `$ARGUMENTS` — a PR number or URL. If empty, review the current
branch against its base and skip the fetch in §1; ask first if that isn't
obviously what was meant.

**Adapt to the repo.** This skill is a method, not a toolchain. Wherever it
says "the repo's test command", "the migration command", "the config file",
find the real one before you need it: `CLAUDE.md`, `CONTRIBUTING.md`, the
README, `package.json` scripts, `Makefile` / `justfile`, `pyproject.toml`, and
the CI workflows (`.github/workflows/`). CI is the most reliable source — it is
what actually runs. If a step has no equivalent in this repo, skip it and say
so in the report.

---

## 1. Isolate

Never review in the user's checkout — they may have uncommitted work, and
`gh pr checkout` would switch their branch. Pull the PR into its own worktree on
a temp branch.

Resolve the **main** checkout first: this may be run from inside one of the
repo's existing worktrees, where `--show-toplevel` returns the worktree, not the
repo.

```bash
N=<PR number>
MAIN="$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")"
BASE=$(gh pr view $N --json baseRefName -q .baseRefName)
WT="$MAIN/.claude/worktrees/pr-$N"

# A stale worktree from an earlier review holds the branch, blocks both commands
# below, and would review stale code. Tear it down first (§9).
[ -e "$WT" ] && echo "pr-$N worktree exists — run §9 cleanup before continuing"

git -C "$MAIN" fetch origin "$BASE" "+pull/$N/head:pr-$N"   # '+' so a force-push fast-forwards
git -C "$MAIN" worktree add "$WT" "pr-$N"
```

A fresh worktree holds only tracked files. Copy the gitignored local config the
tests need (typically `.env` files) from `$MAIN` to the same relative paths
under `$WT`. To see what is ignored without listing every dependency file:

```bash
git -C "$MAIN" ls-files --others --ignored --exclude-standard --directory | grep -i env
```

Those files often carry real credentials, and the steps below run the PR's own
test suite with them loaded. That is acceptable for a colleague's branch on
this repo. **Do not do it for a PR from a fork** — you would be handing
untrusted code your live secrets. Review a fork PR by reading it, with no env
files and no test run, and say so in the report.

**Every path passed to a file tool must start with `$WT`.** A path beginning at
the repo root silently reads the main checkout instead of the PR — including
`CLAUDE.md` or `.claude/rules/*.md` if this PR edits one. Run commands as
`cd "$WT" && …` or `git -C "$WT" …`.

**Never `gh pr checkout`**, and never invoke another skill to do the reviewing
for you. The checkout switches the user's branch, which is the whole reason §1
exists; and a Skill overlays the *current* conversation, so it cannot give you
the fresh context a review needs. Delegate breadth to the §4a subagents
instead — a subagent gets its own context, a skill does not.

You are **read-only on the PR's content**: never edit its files, commit, or
push. The worktree, the temp branch, any scratch database or service, and any
throwaway test you write are yours to create and delete.

### Give shared services an instance of their own

A worktree isolates files, not services. If the test suite talks to a local
database, queue, or cache, every worktree hits the same instance, and the
user's config points it at their dev data. Two consequences:

- Running the PR's migrations against that instance would apply an **unmerged
  migration to the user's dev database**. Never do it.
- Any test asserting a table or queue is empty is correct only against a clean
  instance; leftover dev data makes it fail for reasons unrelated to this PR.

So whenever you intend to run such tests, and always when the PR changes the
schema or adds a migration:

1. Create a scratch instance named for the PR (e.g. a `<app>_review_pr$N`
   database on the same server). If the repo runs its services through docker
   compose, create it through the compose service, and run compose from
   `$MAIN` — compose derives its project name from the directory, so running
   it in `$WT` targets a project with no containers. Host CLI clients often
   prompt for a password and hang the shell.
2. Repoint the connection setting (e.g. `DATABASE_URL`) in the **worktree's
   copy** of the config only. With `sed`, use `-i.bak` and delete the `.bak`
   afterwards — that form works on both BSD and GNU sed.
3. Confirm which setting the app, the test runner, and the migration tool each
   read. They are not always the same one, and one you missed still points at
   dev data.

**Sanity gate — run before every test or migration invocation**, and quote the
result under Evidence: grep the connection setting out of the worktree's config
(e.g. `grep '^DATABASE_URL' "$WT/.env"`).

If it still names the dev instance, or the config file is missing, stop. A
missing env file usually fails open: the loader proceeds silently and you test
against the wrong database.

Bring up a fully separate stack only when a claim needs the **running app**, not
just tests. If the repo's stack-setup script copies config from the main
checkout, run it **before** repointing the connection setting — otherwise it
silently reverts your edit — and re-run the sanity gate afterwards.

### Run tests and migrations the right way

Use the repo's own entry points (the scripts CI runs), not bare tool
invocations. A wrapper script often loads env files or sets config that a bare
`pytest` / `jest` / `go test` skips — and the skipped config is usually the
connection setting you just repointed, so a bare run silently falls back to the
shared instance. Read how the wrapper loads config before trusting it.

Migrations have the same trap: find where the migration tool gets its connection
(shell environment, config file, env file) and use the documented invocation —
sourcing the worktree's env file first if that is what the tool needs.

A fresh worktree has no installed dependencies (`node_modules`, virtualenvs,
build output). Run the repo's install command first. If you skip this, say so
and run no tests rather than reporting install errors.

## 2. Baseline before you blame

Before trusting any failure at PR head, run the same suite at the merge base —
**migrating at each checkout** if the repo has migrations, so each side's tests
meet their own schema. A migration that renames or drops something otherwise
produces spurious base failures and the delta reads backwards.

```bash
MB=$(git -C "$WT" merge-base "origin/$BASE" "pr-$N")

git -C "$WT" checkout --detach "$MB"
# migrate the scratch instance, then run the suite — record failures

git -C "$WT" checkout "pr-$N"
# migrate again, then run the same suite — compare
```

If the lockfile differs between the two, reinstall dependencies at each
checkout. Migrating at both checkouts also makes the PR's migration forward-path
a tested step rather than an assumed one.

**Only the head-minus-base delta is a finding.** Failures present in both runs
are pre-existing — dev-data pollution, schema drift, or a known flake. Same rule
for flakes generally: fails once, passes on rerun, and the test file is absent
from the diff → note it under Evidence, do not report it.

## 3. Load the context that governs this diff

Do all five of these **before** forming an opinion on the diff.

### The linked issue — the acceptance criteria

Find the issue the PR addresses: a closing keyword in the PR body (`Fixes #123`,
`Closes #123`), or a tracker key (`PROJ-123`) in the body, title, or branch
name. Then read it:

- Tracker key (`PROJ-123`) → `ToolSearch("select:mcp__linear-server__get_issue")`,
  then `get_issue`. For a tracker other than Linear, `ToolSearch` for its MCP
  server's issue-fetch tool and add that tool to `allowed-tools` in this file's
  frontmatter.
- GitHub issue → `gh issue view <number>`.
- Tracker not connected → work from `gh pr view $N --json body`, and say so in
  the report.

**No issue and no stated criteria — ask before spending the run.** When there
is no linked issue *and* the PR body names no acceptance criteria, what you are
judging the diff against is undefined, and that choice governs every lens
below. Ask (`AskUserQuestion`): review against the description as written, or
against a requirement the user states now? One question, before §4.

**"Does it do what was asked" outranks every other lens.** Judge the diff against
the issue's stated requirement, not against what the code appears to intend. A
requirement in the issue that the diff doesn't meet is Critical even when every
line is correct. Conversely, scope in the diff that the issue never asked for is
a finding too — name it, don't assume it's wanted.

### Prior review comments — don't repeat them

Review bots, a previous Claude review, and human reviewers have often been here
already. **A finding someone already raised is noise** — drop it, whether or not
the author acted on it. If an earlier finding was raised and explicitly dismissed
by the author, that is settled: do not relitigate it. Only re-raise a prior
finding if you have new evidence (a reproduction, a failing test) that the
earlier comment lacked, and say what's new.

That rule is only as good as this fetch. **`gh pr view $N --comments` is not
good enough**: it misses inline threads and their resolution state, and on a
bot-heavy repo it drags in kilobytes of boilerplate. Read all three sources:

```bash
read -r OWNER REPO < <(gh repo view --json owner,name -q '"\(.owner.login) \(.name)"')

# 1. inline threads — with resolution state and the author's replies
gh api graphql -f query='query($o:String!,$r:String!,$n:Int!){
  repository(owner:$o,name:$r){ pullRequest(number:$n){
    reviewThreads(first:100){ nodes{ isResolved isOutdated
      comments(first:50){ nodes{ author{login} path line body } } } } } }
}' -f o="$OWNER" -f r="$REPO" -F n=$N

# 2. review bodies (skip the empty containers)
gh api repos/$OWNER/$REPO/pulls/$N/reviews \
  --jq '.[] | select(.body != "") | "\(.user.login) [\(.state)]: \(.body)"'

# 3. plain PR comments — where sticky bot reviews live
gh api repos/$OWNER/$REPO/issues/$N/comments \
  --jq '.[] | "\(.user.login): \(.body)"'
```

**Learn this repo's review bots before trusting the fetch.** Each bot has a
fixed shape, and the findings are often not where a thread-only fetch looks:

- **Findings hidden in review bodies.** CodeRabbit, for example, posts
  `**Actionable comments posted: N**` — which counts inline threads only, so it
  is a floor, not a total — and buries further findings in collapsed
  `<details>` sections (`🧹 Nitpick comments`, `⚠️ Outside diff range
  comments`) that never become threads. Grep them out:

  ```bash
  gh api repos/$OWNER/$REPO/pulls/$N/reviews \
    --jq '.[] | select(.user.login=="coderabbitai[bot]" and (.body|length)>0) | .body' \
    | grep -nE '<summary>(🧹 Nitpick comments|⚠️ Outside diff range comments)'
  ```

- **Sticky review comments.** A bot run from a GitHub Action often edits one
  issue comment in place instead of opening threads. Find its marker (usually
  an HTML comment such as `<!-- …-review -->`) and its finding line shape, and
  grep for those. If the repo keeps the bot's prompt or output parser under
  `.github/`, read it — it tells you whether every entry is a finding or
  whether pass rows need filtering out.
- **Noise.** Walkthrough / summary comments that restate the diff, issue-tracker
  mirror comments, and bare trigger comments (e.g. `@claude review`) are not
  findings. Skip them.

**Keep grep patterns POSIX ERE** — `[[:space:]]`, not `\s`, and a plain `(…)`
group, not `(?:…)`. GNU grep rejects both extensions outright
(`Repetition not preceded by valid expression`, exit 2); BSD grep and `ugrep`
accept them, so a pattern that works on a macOS shell can still fail for
everyone else.

**And distinguish a grep error from a clean review.** `grep` exits 1 for "no
match" and 2 for "bad pattern", and both print nothing — so a broken pattern
looks exactly like a review with no findings. Check the status:

```bash
case $? in
  0) : ;;                                    # findings printed above
  1) echo "no findings matched — confirm the bot comment exists" ;;
  *) echo "GREP FAILED — do not read this as a clean review"; exit 1 ;;
esac
```

**Empty output means one of two very different things**, so check which before
concluding anything: the bot ran and found nothing, or **the bot never ran** (or
posted in a format your pattern doesn't match — long-lived PRs may carry an
older format). Confirm the comment exists and eyeball its body first — treating
"the bot has not reviewed" as "the bot found nothing" is the fail-open shape §5
calls Critical.

**Weight bot findings for what they are.** A bot that is not allowed to run
tests produces reasoning, never a reproduction — a finding of its you *can*
reproduce is one you get to upgrade with evidence. **A bot finding never
retires one of your lenses** — read it, don't lean on it. Letting someone
else's pass suppress your [arch] pass is the same fail-open shape §5 calls
Critical in reviewed code.

**Dedup the prior comments before you apply the already-raised rule.** Bots
often re-post near-identical findings on every push, and the same defect often
appears as an inline thread *and* a collapsed nitpick row *and* a human echoing
it. Collapse by `path:line` + claim first. Otherwise one prior finding looks
like four, and the volume alone makes you drop something nobody actually raised.

Read the author's replies too — they are the cheapest source of intent (§4.4).

### Related PRs — keep the scope to this one

```bash
MINE="$(mktemp -t pr-files)"                 # not a predictable /tmp path: shared dir
git -C "$WT" diff --name-only "origin/$BASE...pr-$N" | sort > "$MINE"
# one API call for every open PR's file list, rather than one `gh pr view` per PR
gh pr list --state open --limit 30 --json number,files \
  --jq '.[] | "\(.number) \(.files[].path)"' \
 | awk -v me="$N" '$1 != me' | sort -k2 \
 | while read -r M P; do grep -qxF "$P" "$MINE" && printf 'PR #%s also touches: %s\n' "$M" "$P"; done
rm -f "$MINE"
```

An open PR touching the same files can mean a merge-order dependency or a
conflict — surface it as an Improvement with both PR numbers, and check whether
the finding you're about to file actually belongs to the *other* PR. **Findings
must be scoped to this PR's diff.** Work the sibling PR leaves undone is not this
PR's defect.

### The PR description — read it as a filled-in template

If the repo has a `.github/pull_request_template.md`, every PR carries the same
rows, so you know where the checkable claims live before you open the body.
Common rows change how you spend the run:

- **"Where to look hardest" / "Risk"** — read this **first**, before the diff.
  The author is pointing at the risk they know about; weight the review toward
  it. If it is blank or says "trivial, low risk" on a diff that isn't, that is
  itself a finding.
- **"How this was verified" / "Testing"** — treat every pasted command and
  result as a lens-C claim: re-run the command at head and compare. A pasted
  test count that doesn't reproduce is **Contradicted**, and Critical. Pasted
  verification is what a reviewer trusts most and what an agent most easily
  fabricates.
- **Checklist boxes** — each one that is mechanically checkable (docs updated,
  migration added, changelog filled, no secrets) is a claim: a ticked box with
  no supporting diff is Contradicted, not a formality. Boxes that can't be
  falsified ("I read my own diff") — ignore.
- **Rollback** — a migration or backfill that can't be reverted by reverting
  the commit, described as if it can, is Critical.
- **Screenshots** — for a UI change, their absence when the template asks for
  them is an Improvement, not a Nit.

### The rules

Read `CLAUDE.md` if it isn't already in context, plus any nested `CLAUDE.md` in
directories the diff touches. Path-scoped rules are a separate matter:
`.claude/rules/*.md` files load when a matching file is *opened*, and a diff
opens nothing. **For every area the diff touches, open the matching rule files
yourself** (under `$WT`) — match each rule's `paths` frontmatter, or the mapping
in `CLAUDE.md` if the repo keeps one. A finding that contradicts a rule you
never read is the most common miss.

Read `CONTRIBUTING.md` too, and the feature's design doc or spec when the repo
keeps them — it is the source of truth for how the feature should work.

Apply the rules; don't restate them in the report.

## 4. Method — in order

1. Record every factual claim the PR description makes (lens C).
2. **Dispatch the breadth reviewers now** (§4a) — they sweep the diff in their
   own contexts while you read it in yours. Dispatching after you've read wastes
   the parallelism.
3. Read the diff in full before judging anything. Skim-flagging is worse than
   silence. Their reports are breadth; **this pass is the depth**, and it is
   still yours. Do not skip it because other agents are also reading.
4. For each candidate finding, try to disprove it first: is it actually
   reachable, or am I inferring from a name? Is it already handled elsewhere in
   the diff, or by a caller? Is it pre-existing rather than introduced here?
   **Did the author do this on purpose?** A code comment, the PR description, the
   linked issue, a design doc, or a reply to an earlier review saying so makes it
   a deliberate choice, not a defect — drop it. Question a deliberate choice only
   when it breaks a stated invariant or a requirement, and then argue against
   the stated reason rather than pretending it wasn't given.
   Has a previous reviewer already raised it (§3)? Then drop it.
5. If you cannot cite the `file:line` that makes it true, drop it. Never report a
   finding whose evidence is "this looks like it might".
6. Run what the user marked `reproduce` at §4b — §1 gave you a safe place to.
   A reproduced failure outranks an argument. This step has no input until §4b
   has an answer.
7. Run the mechanical checks the diff triggers, then the docs-drift pass.
8. Rank what survives. Clean up (§9). Print the full report to the terminal
   (§11) — that is free and always happens, and it is the evidence the user
   triages from. Then §13: ask what goes out, and post it.

## 4a. Fan out for breadth, keep the depth yourself

A diff sweep is exactly the work worth delegating: it is broad, it eats
context, and it parallelizes. Dispatch both agents **in one message** so they
run concurrently, then read the diff yourself while they work.

**Which agent types.** If the repo defines its own review agents under
`.claude/agents/` (a correctness reviewer, an architect), use them — they
already carry the repo's lens. Otherwise use `general-purpose`. The prompts
below spell out the lens either way; a repo agent just applies it with more
local knowledge.

They do not see this conversation, so each prompt must be self-contained — and
each must be told the tree is at `$WT`, **not** the current working directory.

**Agent A — correctness reviewer.**

> Review the PR branch checked out at `<$WT>`. Read it with
> `git -C "<$WT>" diff "origin/<BASE>...pr-<N>"`, and open each file you need
> under that path — every path you touch must start with `<$WT>`.
> Do not fetch remote PRs, do not switch branches, and do not modify the tree.
> Cover **Correctness, Edge Cases and Error Handling, Testability, Efficiency**.
> Treat any path that swallows a failure, or any check or test that can never
> fail, as Critical. Name any test that should exist and does not; do not
> write it.
> Report in this exact format, which overrides any output format in your
> instructions — **Critical** / **Improvement** / **Nit**, each as
> `` `file:line` `` + a one-line summary and brief why; write "none" for an
> empty group. Under 500 words. End with "Approve" or "Request changes".

**Agent B — architect.**

> Review the PR branch checked out at `<$WT>`. Read it with
> `git -C "<$WT>" diff "origin/<BASE>...pr-<N>"`, and open each file you need
> under that path — every path you touch must start with `<$WT>`.
> Do not fetch remote PRs, do not switch branches, and do not modify the tree.
> This is a diff review, not a pre-code design review, so apply your lens to
> what the diff actually does.
> **Read `<$WT>/CLAUDE.md` and every `<$WT>/.claude/rules/*.md` whose paths
> match a file the diff touches** — a diff opens no file, so nothing
> auto-loads. Check the diff against those invariants, against the codebase's
> module and layer boundaries, against tenancy and authorization, against
> changed contracts whose consumers were not updated, and against whether a
> load-bearing choice is missing a recorded decision. Also cover performance
> and security.
> Report in this exact format, which overrides any output format in your
> instructions — **Critical** / **Improvement** / **Nit**, each as
> `` `file:line` `` + a one-line summary; write "none" for an empty group.
> Under 500 words. End with "Approve" or "Request changes".

**Append this block verbatim to both prompts above.** It is the report shape;
without it "under 500 words" is a cap with no form, and you get 500 words of
preamble.

> **Report shape.** Lead with the verdict line — no preamble, no "I reviewed
> the diff", no restatement of what the change does, no closing summary. One
> finding is: `` `file:line` `` + one sentence for the defect + one clause for
> the trigger. One idea per sentence, active voice, ~20 words.
> **Verbatim, always:** `file:line`, commands, exact error strings, test counts,
> numbers and units. Never paraphrase a traceback — it is the only thing the
> finding rests on.
> **Never drop a negation** (`not` / `never` / `no` / `only` / `except`).
> "does **not** scope to the tenant" compressed to "scopes to the tenant"
> inverts a Critical into an all-clear. Brevity never costs a negation.
> If a shorter phrasing isn't actually shorter, use the plain one.

**Reviewer C — Codex adversarial, conditional.** It challenges the *approach*,
not the implementation, and needs the `openai-codex` Claude Code plugin. Probe
readiness as its **own** Bash call first — the result isn't available until it
returns, so it cannot share a message with the dispatch:

```bash
CODEX_COMPANION=$(ls -d ~/.claude/plugins/cache/openai-codex/codex/*/scripts/codex-companion.mjs 2>/dev/null | sort -V | tail -1)
if [ -n "$CODEX_COMPANION" ]; then
  node "$CODEX_COMPANION" setup --json 2>/dev/null | jq -r '.ready // false'
else
  echo "no-codex"
fi
```

Write it as `if/then/else`, not `A && B || C`. In the one-liner form a broken
companion makes `jq` swallow node's exit code and print **nothing** — neither
`false` nor `no-codex` — so the check below matches no branch at all.

`no-codex` or `false` → **skip it silently**; never prompt the user to install or
log in. `true` → run it in the foreground in the same message as the Agent calls
(it blocks via `--wait` while they run concurrently), scoped to the PR branch
rather than Codex's default:

```bash
CODEX_COMPANION=$(ls -d ~/.claude/plugins/cache/openai-codex/codex/*/scripts/codex-companion.mjs 2>/dev/null | sort -V | tail -1)
cd "$WT" && node "$CODEX_COMPANION" adversarial-review --base "origin/$BASE" --wait
```

It is re-derived here on purpose: shell state does not persist between Bash
calls, so the variable set in the probe above is empty by now.

Pinning `--base "origin/$BASE"` matters: the default scope diffs against the
*local* base ref, which is stale in a worktree, so Codex would review dozens of
already-merged files.

**After they return — two rules.**

*Verify they left the tree alone.* Nothing enforces read-only at the tool layer
for an agent that holds `Bash`. You are read-only on the PR's content, so
anything changed here is a bug in the review:

```bash
git -C "$WT" status --porcelain
```

Anything unexpected → stop and surface it.

*Do not stall — but the run does not continue past §4b.* Their reports arrive
as ordinary tool outputs, not as prompts, so a long report is not a stopping
point: merge the findings and go straight to §4b in the same turn. **§4b is
where the run pauses.** This rule says "don't end your turn on an agent
report"; it does not say "skip the gate", and reading it that way is the one
way to get §4b wrong.

**Merge, tagged by source** (`A` / `B` / `Codex`, or the combination). Two
agents flagging the same `file:line` is a stronger signal — rank it first.
Codex's design challenges often map to no single line; keep them as their own
entries. **Their findings are candidates, not findings.** Every one still has
to clear §4.4: disprovable, cited, not already raised, not deliberate. An
agent's confidence is not evidence.

**When they disagree, do not average them.** A says Approve and B says Request
changes; one agent calls a line correct and another calls it a bug; a prior
human comment says the opposite of what you found. A contradiction is a signal,
not noise — it usually means the two are reading different constraints, and the
resolution is evidence:

- Try to settle it by running something. A reproduction ends the argument.
- If it stays open, it goes into the §4b table as its own row, **with both
  sides stated**, and the user picks. Never silently side with one.
- Contradicting a *prior human reviewer* is a special case: §3 already says
  re-raising needs new evidence the earlier comment lacked. Disagreement is not
  new evidence — a reproduction is. Without one, drop it.

## 4b. Gate: which candidates are worth verifying

Verification is the expensive half of this skill — reproductions, throwaway
tests, base-vs-head runs. Once you have the merged candidate list and have read
the diff, **stop. Print the table, ask, and wait for the answer.**

This is a pause, not a note to self. The only condition that skips it is
observable and narrow: **every** candidate is free to check (a grep, a file
read, something already run). One candidate that costs a container, a test run,
or a base checkout means the gate fires. "It'll be quick" is not that condition
— estimate the cost in the table and let the user decide.

**§6 and §7 execute this list.** What you reproduce is what the user marked
`reproduce`; there is no separate verification plan. Skip the gate and you have
nothing to execute from, which is how an unasked-for 40-minute run happens.

```text
#  source    file:line               candidate                  cost to verify
1  A+B       src/billing/invoice.py:44  guard misses None       ~2 min, throwaway test
2  Codex     (design)                retry loop can double-ack  ~10 min, needs a base run
3  me        web/components/list.tsx:12 missing empty state     free, read-only
```

Then one `AskUserQuestion` round: **reproduce** / **cite only** / **drop**,
batched four per call, with your own read picking the recommended option. Mark
anything free to check as already done rather than asking about it.

This gate spends your time, **it does not lower the bar.** What "cite only"
skips is the *reproduction*, never the citation — §4.5 still holds, so a
candidate you cannot pin to a `file:line` is dropped whether or not the user
would have kept it. A "cite only" finding ships as **Supported** in lens-C
terms, marked *not reproduced*, with the command that would settle it. It never
ships as Tested, and an edge case that was only reasoned about still cannot be
reported at all (§6D).

**Where to ask, and where not to.** Four questions, each on an observable
predicate — not a running commentary:

| Ask | When | §  |
|---|---|---|
| What are we reviewing against? | No linked issue **and** the PR body states no acceptance criteria | §3 |
| Which candidates to verify | Always, once the reviewers have returned and you've read the diff | §4b |
| The one open question | A real ambiguity would change the verdict — ask it live, while you can still act on the answer | §11 |
| What goes out, and as what event? | Always, before posting | §13 |

Do **not** ask per finding while reviewing. Step 4 above is the mechanism for
a doubtful finding — disprove it or drop it. Triage happens once, in §13,
against the printed report.

## 5. Two findings that are always Critical

Do not file either as an Improvement until you have traced the call stack and the
user-visible effect.

- **Fail-open.** Any new path that swallows a failure, treats an error as
  success, or falls back to a default with no log and no error. The safe
  direction is fail-closed.
- **A guard that does not guard.** A check or a test that can never fail. A test
  passing for the wrong reason is worse than no test.

## 6. Lenses

Apply all five. Use the tag in brackets when reporting.

**A. [arch] Architecture & design**
- Does the change hold the invariants in the rules you loaded? Name the rule when
  it doesn't.
- Data-model and migration rules: a model or schema change with no migration, or
  an edit to a migration that has already shipped, is Critical.
- Boundaries the codebase defines — layers, pipeline stages, modules, services:
  logic belonging to one leaking into another.
- A second, parallel way to do something the codebase already solves. An
  abstraction that is indirection with one caller.
- **Integration points.** For every contract the diff changes — a function
  signature, a return shape, an API response, a message or event type, an enum,
  a config key, a DB column — grep the tree under `$WT` for its consumers and
  check each one still holds. Name the ones you checked in Evidence. A caller
  the diff forgot is Critical; changed backend types with stale generated client
  types is the frontend case of the same defect (§7).
- **Changed flows, read end to end.** When the diff alters a multi-step flow —
  a pipeline stage sequence, a state machine transition, a request path, a
  retry/ack loop — stop reviewing lines and read the flow as it now stands, from
  entry to terminal state. Ask what the new shape does on each branch, not what
  each hunk does. Defects here (an unreachable state, a step that can now run
  twice, an ordering that only holds by accident) are invisible at line level and
  are the reason this pass exists. Say in Evidence which flow you traced.
- Failure behavior under timeout, partial failure, retry, concurrency.
- Scale: the query/loop/allocation that is fine at today's N and not at 100×.
- A load-bearing choice between real alternatives with no recorded decision
  (ADR, design doc) in a repo that keeps them — Improvement, but say it.

**B. [sec] Security**
- **Tenancy** — in a multi-tenant system, cross-tenant leakage is Critical,
  always. Every new query scopes to the tenant. If the codebase has a standard
  way to resolve the tenant (a dependency, middleware, a base query), new entry
  points use it rather than hand-rolling it; admin or internal routes may be
  deliberate exceptions. Read the repo's auth rules before calling any of this a
  finding.
- Authz on every new entry point — object-level ownership, not just "is logged in".
- Untrusted input: injection, path traversal, deserialization, SSRF, unbounded sizes.
- Secrets and PII in logs, error messages, or client-visible payloads.
- Over-broad API responses, missing field filtering, IDOR, missing rate limits.
- New dependencies: what do they pull in, maintained, pinned?
- Code that calls an LLM or runs an agent: prompt injection via untrusted content
  (user data, documents, emails, web pages), tool-call blast radius, model output
  trusted where it shouldn't be.

**C. [claim] Verifiable claims**
Extract every checkable assertion from the description, commit messages, and code
comments — "reduces latency ~40%", "backward compatible", "no schema change
needed", "covered by tests", "no behavior change". Mark each:
- **Tested** — you ran something that settles it. Show the command and output.
- **Supported** — the diff shows it. Cite `file:line`.
- **Unsupported** — the diff neither shows nor contradicts it. State exactly what
  would settle it.
- **Contradicted** — the diff or a run shows otherwise. Cite `file:line`. Critical.

You have a worktree and a scratch instance, so prefer **Tested** over Supported
wherever the claim admits it:
- *Performance* → time the same operation at `$MB` and at head. An untimed perf
  claim is Unsupported, never Supported.
- *"Backward compatible"* → restore the base's tests onto head's code and run
  them: `git -C "$WT" checkout "$MB" -- <test paths>`, run, then
  `git -C "$WT" checkout "pr-$N" -- <test paths>` to restore.
- *"No schema change needed"* → run the ORM or migration tool's autogenerate /
  check command against the scratch instance; a non-empty diff contradicts it.
- *"Covered by tests"* → name the test, then revert the fix hunk
  (`git -C "$WT" checkout "$MB" -- <source path>`), confirm the test now fails,
  and restore. A test that still passes with the fix reverted covers nothing.

Mechanical rows for the conventions the repo requires, if it has any (check
`CONTRIBUTING.md` and the PR template) — e.g. a linked issue in the description,
a changelog entry for user-facing changes, the template's checklist.

**D. [edge] Edge cases**
Hunt these specifically, then add the ones this codebase's domain implies (read
the data model — money, units, quotas, state machines):
- `None` / `null`, empty collection, single element, boundary values.
- Numbers: zero, negative, overflow, float precision, rounding, unit or currency
  mismatch.
- Dates: timezone and DST boundaries, month/year ends, leap days.
- Duplicates: the same row inserted twice; re-importing the same file or
  replaying the same event.
- Idempotency: does re-running the operation change the result?
- Concurrency: two workers or requests on the same row; lock, lease, and retry
  paths.
- Cross-tenant: the same id in another tenant.
- Strings: unicode, empty, length limits, injection-shaped content.
- Today's N vs 100×.

**Do not report an edge case you only reasoned about.** Write a throwaway test
for it in the worktree and run it. Passes → drop the finding. Fails → that is a
finding with evidence. Delete the test afterwards and never commit it.

**Report every edge case you generated, passing ones included**, as a table in
Evidence — concrete values, never prose:

| Case | Input | Expected | Actual |
|---|---|---|---|
| empty batch | `items=[]` | returns `0`, no write | `IndexError` |

The passing rows are what lets the author trust the failing ones, and they are
the test cases they should add. Give literal values: the author must be able to
paste them into a test without asking you what you meant.

**E. [ux] UI/UX** — only if the diff touches frontend code, CLI output, API
error shapes, emails, or copy.
- Read the repo's frontend rules if it has them and check the contracts they
  name — typing rules, the API client wrapper, data-fetching conventions,
  design-system and token usage, shared table and form components.
- Missing states: loading, empty, error, zero-results, partial data.
- Does a failure surface as something actionable, or as an endless spinner / raw
  exception string?
- Destructive or irreversible actions without confirmation or undo.
- Accessibility: keyboard reachability, focus after navigation or modal close,
  labels on controls, contrast, touch targets.
- Copy: jargon, blame-the-user phrasing, inconsistency with existing wording.
- Overflow for long strings, large numbers, small viewports.

## 7. Mechanical checks

Run the ones this diff triggers, from `$WT`, and **report the real output, not
the claim that it passed**:
- Inputs to code generation changed (API schema, models, config definitions) →
  run the repo's codegen or staleness check; a diff in generated output is a CI
  failure.
- Models or schema changed → the migration exists, and no shipped migration was
  edited.
- Lint, format check, type check → run the ones CI runs over the changed files,
  including docs/markdown lint if CI has a job for it.
- Behavior changed in a tested area → the relevant tests, at base and at head (§2).

If you run nothing, say "No checks run" — don't imply coverage you don't have.

## 8. Docs drift

One line each; Improvement unless the code contradicts a doc that is the source
of truth:
- Implementation diverges from the feature's design doc or spec with no update.
- New env var, script, command, or endpoint missing from the README, runbook, or
  setup docs.
- A new invariant that belongs in `CLAUDE.md` or a `.claude/rules/*.md` file,
  left only in prose or in the author's head.

## 9. Clean up

```bash
git -C "$MAIN" worktree remove "$WT" --force
git -C "$MAIN" branch -D "pr-$N"
```

Drop the scratch database or service if you created one. Confirm in the report
that the user's checkout was never touched.

## 10. Do not report

- Formatting, import order, naming style — anything the repo's formatter,
  linter, or type checker already enforces.
- Generated files as *content*: never review generated clients, generated docs,
  or similar output line by line. Do flag them stale or missing — that belongs
  under §7. Same for lockfiles, vendored code, snapshots.
- `except A, B:` as a syntax error. It is valid PEP 758 on Python 3.14 and a
  recurring false positive. The only finding it warrants is a Nit: add an `as _`
  clause so `ruff format` keeps the parentheses.
- A prior reviewer's claim about a table, column, or module that doesn't exist
  in this codebase — review bots working from a stale model of the repo repeat
  these. Don't repeat it, and don't "fix" it. **But verify before dismissing:**
  check the models or schema for each name in the claim. A wrongly-assumed
  false positive buries a real finding.
- Test failures that also fail at the merge base, or that pass on rerun (§2).
- Anything a previous reviewer already raised, or the author explicitly justified
  as deliberate (§3, §4.4). Both are settled unless you have new evidence.
- Defects that belong to a sibling PR rather than this diff (§3).
- Pre-existing issues the PR merely moves or touches — unless this change makes
  them materially worse, in which case say so and file it as an Improvement.
- Restatement of what the PR does, or "consider adding tests" with no specific
  case in mind. Name the untested case or skip it.
- Speculative refactors with no defect behind them.

## 11. Output format

Match this exactly. If a section is empty, write `None.` on one line. Do not pad.

**Verdict:** Approve / Request changes — <one clause why>
**Tally:** N critical · M improvements · K nits · J claims unverified · tags used: <list>
**Environment:** worktree `<path>` · scratch DB `<name>` or none · baseline `<sha>` · cleaned up: yes/no
**Verification gate (§4b):** N candidates · K reproduced · M cite-only · J dropped
**Rules read:** <rule files opened, or "none — diff touches no covered area">
**Context:** issue `<key>` <one clause: requirement met / not met> · prior reviews: N comments read, M findings skipped as already-raised (incl. collapsed bot rows and sticky bot reviews) · reviewers: <A/B/Codex, or which were skipped> · related PRs: <numbers, or none>

**Every finding opens with a tag, and the tag is one of exactly five** — the
§6 lenses, spelled as written here. Not an abbreviation of your own, not a new
one, not omitted:

`[arch]` · `[sec]` · `[claim]` · `[edge]` · `[ux]`

If a finding seems to need a sixth tag, it belongs under whichever of the five
owns the defect — pick one and move on. A finding with no tag is an incomplete
finding: the `Tally` line names every tag used, so a missing one is visible in
your own header before you post.

### Critical
Bugs, security, breaking changes, broken invariants. Max 7, most severe first.

1. **[tag] `path/file.ext:LINE`** — <one sentence: what is wrong>
   *Breaks when:* <concrete trigger → concrete wrong outcome>
   *Fix:* <one line, or ≤5 lines of code>

**When the fix is a design choice, the *Fix* line names the alternatives, not
one answer.** If resolving the finding would change a subsystem's shape, add a
pipeline stage, swap a data model or library, or move a tenancy or concurrency
boundary, then prescribing a single fix is deciding for the author — that class
of decision belongs in a design record (an ADR, if the repo keeps them), which
is theirs to write. Write *Options:* A / B with the tradeoff in a clause each,
and say which artifact should record the choice. Same rule inside this run: if
**your own** choice of what to report hinges on such a decision, ask with
`AskUserQuestion` rather than assuming — you do not get to settle the author's
architecture in a comment.

### Improvement
Worth fixing, not a merge stopper. Max 5. **An Improvement is exactly one
bullet: tag, location, what is wrong, and the fix — in a single sentence.**
If more than 5, append "plus N similar".

- **[tag] `path/file.ext:LINE`** — <one sentence that contains both the defect and the fix>

Filled, so the shape is unambiguous:

- **[claim] `.env.example:42`** — the setup note still says "set both vars" and never mentions `CACHE_URL`; add the sentence you already added to `docs/setup.md:118`.

**The one-line cap is a severity test, not a word budget.** If a finding only
makes sense once you write a *Breaks when:* line, then its trigger is
load-bearing and it is **Critical** — promote it rather than expanding it here.
If the trigger is not load-bearing, the sentence above is enough. Every finding
therefore lands in one of two shapes: three lines under `Critical`, or one line
under `Improvement`. There is no third shape.

### Nit
Max 3, and each must clear the bar: **would you actually implement this?** If the
fix costs more than the defect, or you'd wave it through on a re-review, it isn't
a Nit — it's noise. Omit the section entirely if nothing clears the bar; that is
the normal case.

- **[tag] `path/file.ext:LINE`** — <one line, same shape as an Improvement>

### Claims
Only if the PR made checkable claims. One row each, no prose.

| Claim | Verdict | Evidence / what would settle it |
|---|---|---|

### Evidence
Commands run and their actual output, trimmed to the decisive lines — base vs
head where you compared. Include the config sanity gate. Name any throwaway test
you wrote and deleted. Or `No checks run.`

### Open question
At most one, only if a real ambiguity changes the verdict. Otherwise omit.
**Ask it live rather than filing it** — if it would change the verdict, you
need the answer before you have a verdict, so put it to the user with
`AskUserQuestion` when you hit it, and record the answer here.

## 12. Tone and style

**Three output channels, three different rules.** Each names the section that
governs it:

| Channel | Shape |
|---|---|
| Subagent → you (§4a) | Compressed. The report-shape block in §4a is the contract. |
| You → terminal (§4b gate, §11 report) | Concise: this section's rules. Keep the structure — tables, three-sentences-per-finding — and cut the prose around it. |
| You → GitHub (§13b) | **Human-facing.** §13b's budgets and the "friendly is a shape" moves below govern it. Terse-register compression reads as rude on someone else's PR. |

Whatever the channel, four things never compress:

- **Verbatim:** `file:line`, commands, exact error strings, test counts, numbers
  and units. Evidence paraphrased is evidence destroyed.
- **Negations:** `not` / `never` / `no` / `only` / `except`. Dropping one
  inverts the finding.
- **One word, one meaning.** `Tested` / `Supported` / `Unsupported` /
  `Contradicted` are the claim vocabulary and `Critical` / `Improvement` / `Nit`
  the severity vocabulary — no synonym rotation, in any channel.
- **Full sentences resume** for a `[sec]` finding, at the §4b and §13a gates,
  and inside any `AskUserQuestion`. Those are where ambiguity costs a wrong
  decision or an irreversible post; compression resumes after.

Constructive and professional. **Explain why** a change is requested — the
*Breaks when* line is that explanation, not a courtesy. On an Approve, name the
specific thing the change gets right in one clause in the verdict; don't pad it
into a paragraph.

- Every finding: one sentence for the problem, one for the trigger, one for the
  fix. No paragraphs.
- Assert plainly. No "it might be worth considering possibly".
- If the change is clean, say so in the verdict and report nothing. A short
  review is a valid result; never manufacture findings to look thorough.
- Keep the whole report under 400 words unless Critical findings genuinely
  require more. Length lives in Evidence, not in prose.

Friendly is a shape, not an adjective — four concrete moves, all of which fit
inside the word cap:

- **Second person for the author's code.** "your `parser.py` guard", not "the
  author's guard" and not the passive "the guard was not wired".
- **The Approve verdict names what the change gets right**, specifically — the
  thing you checked, not "looks good".
- **An Arguable claim ends with one clause handing the call back** — "your
  call; flagging it so it's a decision rather than an oversight."
- **No sign-off, no thanks-for-the-patch, no apology.** One sentence naming the
  worktree and baseline is all the process narration the author needs.

## 13. Triage with the user, then post

**Only when the target was a PR.** Reviewing the current branch produces no
review to post — say that in the terminal and stop here.

### 13a. Ask, once

The §11 report is already printed. Number every finding across `Critical` /
`Improvement` / `Nit` in that printout (1, 2, 3 … continuing across the
sections) so the user can answer by number, then ask with `AskUserQuestion`:

- **One question per finding**, options **Keep** / **Drop**, batched four per
  call. Your severity picks the recommended option and it goes **first** in the
  list with `(Recommended)` in its label. Keep going until every finding has an
  answer.
- **Then one question for the event**: **approve** / **request-changes** /
  **comment** / **don't post**. Recommend one — the verdict already is one —
  but never assume it.

**More than 8 findings** → ask one framing question first, so this isn't four
rounds of prompts:

> Triage all 12 one by one, or post the 3 Critical and drop the rest?

An unverified finding (§4b "cite only") must be labelled as such **in the
question**, not just in the report — the user is deciding whether to put it on
someone else's PR under their name, and "we didn't check this one" changes that
call.

**Post nothing until the user answers.** This is the only irreversible step in
the whole review, it lands on someone else's PR under the user's name, and
they are the one who has to live with the thread. A finding the user drops is
dropped: don't re-raise it in a softened form, don't append it as a PS.
"Don't post" is a complete answer — the terminal report already did the work.

Waiting is not optional and not conditional on how clean the result looks. An
Approve with zero findings still asks, because posting an approval is itself
the outward act.

### 13b. Post what they approved

The posted body is the kept findings plus the §11 report **minus** the
reviewer's own bookkeeping.
Drop `Environment`, `Verification gate`, `Rules read`, `Context`, the config
sanity gate, and raw command output. Keep, in this order:

1. The verdict line, with its one-clause reason.
2. `Critical` / `Improvement` / `Nit`, unchanged — with any finding the user
   waved through unverified at §4b marked `(unverified)` and carrying the
   command that would settle it. Never present reasoning as a reproduction.
3. The `Claims` table.
4. The edge-case table from §6D — the passing rows are the tests the author
   should add, so they are the most useful thing in the comment.
5. One line of base-vs-head numbers, and any command whose result a finding
   rests on.
6. Anything cross-PR: merge-order conflicts, a sibling PR that owns the work.

**The posted body is a subset of the terminal report, never an expansion.** If
the comment is longer than what you printed, you added padding — cut back to
the subset.

Two budgets, because the tables are the useful part and a single cap squeezes
the wrong half:

- **Prose: 250 words.** Verdict line, findings, the closing numbers, the
  cross-PR note. A finding is three sentences — problem, trigger, fix — and a
  `file:line`; over that, you are re-explaining the diff to its author.
- **Tables: 12 rows total** across Claims and edge cases. Past that, keep the
  rows a finding rests on and the failing edge cases, and drop the rest.

Write it with a Bash heredoc into a temp file (this skill has no `Write`
tool), then post and confirm:

```bash
BODY="$(mktemp -t pr-review-body)"
cat > "$BODY" <<'EOF'
<review body>
EOF
gh pr review $N --approve --body-file "$BODY"          # or --request-changes
gh pr view $N --json reviewDecision --jq .reviewDecision
```

The event is the user's answer from 13a, not the verdict: approve →
`--approve`, request-changes → `--request-changes`, comment → `--comment`.
**GitHub refuses the first two on your own PR** — check
`gh api user --jq .login` against `gh pr view $N --json author --jq
.author.login` and fall back to `--comment` when they match.

Quote the confirmation when you hand back, so the user sees the event landed:
`reviewDecision` for `--approve` / `--request-changes`. **Not for
`--comment`** — a COMMENTED review leaves `reviewDecision` at whatever it
already was, so quoting it there reports someone else's decision as yours;
quote the review URL `gh pr review` prints instead.

`gh pr review` posts a review event, not a PR description — it carries no
generated-with footer.
