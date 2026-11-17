pr-pulse job {{id}}: {{action}} for {{slug}}#{{n}} — {{title}}
{{url}}

Run `pr-pulse job start {{id}}` first. It marks the job as yours and keeps it from being handed
to anyone else. While you work, run `pr-pulse job beat {{id}}` about every 15 minutes.

**Why this job:** {{note}}
{{lines_ready}}
{{decisions}}
{{repo_rules}}

**What to do:** {{task}}
- For a re-review, focus on what changed since {{me}}'s last review, and on whether their earlier
  threads were addressed. `pr-pulse job show {{id}}` prints the commit range.
- For a merge, follow the merge rules in your instructions (CLAUDE.md) and the `/pr-merge` skill exactly. Check that every PR it
  depends on is merged and that every thread is answered. Merge only the head commit named
  above. If `gh pr view {{n}} --json headRefOid` shows a different head, do not merge: run
  `pr-pulse job fail {{id}} --why "head moved"`.

**Decisions are {{me}}'s: ask them, never skip them.** When the skill would ask them something
with AskUserQuestion (a triage round, implement / defer / reply, reproduce or cite, which way
to go), ask it with pr-pulse instead, always with the context they need to decide from the
notification alone:
```
pr-pulse ask --job {{id}} --json <<'JSON'
{"question": "Approve, request changes or comment?",
 "summary": "<one line: what this PR or item is, in plain words>",
 "options": ["Approve", "Request changes", "Comment"],
 "allow_text": true,
 "findings": [
   {"severity": "critical|improvement|nit", "path": "src/x.ts:88",
    "what": "<one sentence: what is wrong and what it breaks>",
    "scope": "runtime|migration|infra|tests|docs|ci|tooling"}
 ]}
JSON
```
- **List every finding** behind the question, including the ones you would not block on.
- **Severity** is how bad it is. **Scope** is what it can break. A critical in a test or a doc
  keeps its severity: say in `what` whether it hides a real production bug.
- **Migrations and infra** always count as production. A file that looks like production code
  counts as production whatever scope you give it; you can only raise a scope, never lower it.
- **For a question with no findings** (implement / defer / reply on one comment), give a
  `summary` saying what the comment asks for and what it would change.

They get three lines: the counts by severity and scope, the top finding, and the question. They
can answer right there, or click through to this session. Then stop and wait: their answer
arrives as a line from your inbox watcher ("pr-pulse: answer to question N …"). If they answer in
this session instead, use that, and run `pr-pulse answer <question id> "<their answer>"` so the
question closes. Never answer a question yourself, and never skip one because nobody seems to
be around.

**Keep the architectural intent in mind, before you judge or change anything:**
- Read `docs/ARCHITECTURE_INTENT.md` (if the repo has one) and `AGENTS.md`.
- Does the limit exist without this feature? Then the fix belongs where the limit lives, for
  every tenant, not in this PR.
- Is anything new built for one document type, field or customer? That is a finding.
- An old ADR is not a finding on its own.

**Bounds for any reviewer you brief:** confirm the change does what it says; report only what
stops it; top 3; skip what is already raised.

**Outward text waits for {{me}}'s own top lines.** This rule beats any skill step that says
to post. Do NOT post a review, a comment, a reply or a PR body yourself; a guard blocks it
anyway until their lines are in. For each piece of text
that would go out:
1. Park it: `pr-pulse outbox add --job {{id}} --kind <review|reply|comment> --target "<where it goes: review event, thread id, or comment>" <<'EOF'`, then the draft, then `EOF`.
2. When everything is parked, run `pr-pulse job wait-user {{id}}`, say in one line what is
   waiting, and stop.

pr-pulse brings the job back to this session once {{me}} has added their lines. Then
`pr-pulse outbox show --job {{id}}` prints each draft with their lines. Post them with their lines
first and your draft quoted below, and run `pr-pulse outbox posted <draft id>` after each one.

Pushing code, resolving threads with no text, and `/pr-merge` itself are not outward text. Do
those as the skill says.

**Finish** with exactly one of these:
- `pr-pulse job done {{id}}`
- `pr-pulse job fail {{id}} --why "<one line>"`

A failure sends {{me}} a notification. Never retry a failed merge or force anything through.

{{extra}}
