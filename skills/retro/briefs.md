# Analyst briefs (step 4)

Fill the `{…}` slots and dispatch all three in **one message**, `subagent_type: Plan` (read-only
tools; it cannot edit). Each returns JSON cards only. Never more than these three at once.
Config slots: `{instructions_file}` = `<config.instructions_file>`; `{base_branch}` = `<config.base_branch>`; `{budget_note}` = if `instructions_cap_bytes` is set,
"`{instructions_file}` is capped at <N> B by CI, and any rule-size budget the repo documents applies", else
"`{instructions_file}` has no size cap, but every card still merges or deletes as much as it adds".

Shared preamble for every brief:

```
You are one of three analysts in a fortnightly retrospective of a repository's AI-agent harness
(Claude Code skills, rules, hooks, subagent definitions, CLAUDE.md/AGENTS.md, memory files).
Goal: find what keeps recurring and propose the fix that stops it. You are read-only: do not
edit, create or delete any file. Query large files with jq/grep; never read one whole.

Window: {since} → {today}. Run dir: {run_dir}.
Do NOT propose anything whose key is in this list (already rejected, or a fix still in an open PR):
{do_not_propose}

Return ONLY a JSON array of at most 8 cards, strongest first:
{"kind": "edit|new-subagent|delete", "slug": "kebab-case-topic", "target": "path or skill/step the fix lands in",
 "recurs": "problem|habit", "lives_in": "harness|agents",
 "current_rung": "none|memory|rule|skill-step|hook", "proposed_rung": "...",
 "change": "the edit in one line", "why": "the recurring cost in one line",
 "evidence": {"count": N, "sessions": N, "refs": ["PR #…", "<issue id>", "session <id8> <date>"]},
 "signature": {"user_regex": [], "pr_regex": [], "agent_regex": []},  // at least one non-empty; no "" patterns
 "draft": "the exact new text or diff, short"}
A card needs evidence from at least 2 independent places (sessions, PRs, issues). Name
patterns, never people. Do not quote transcript text in "draft".
```

## A — sessions (the user's own corrections)

```
Input: {run_dir}/turns.jsonl — one row per turn the user typed: text, prev_action {tool,
target} (the agent's last tool call before the user spoke), prev_text (its last words).
Find corrections the user repeats: reminders ("don't forget…", "remember…"), reversals
("no", "instead", "why did you…", "[interrupted]"), and instructions that should have been
the default (e.g. "use the PR skill", "check CI", "ask me first"). Cluster them; for each
cluster, use prev_action to name the exact skill step, rule or file that should have caught it.
Known existing coverage to check before proposing (a correction that recurs DESPITE coverage
moves one rung up): memory index {memory_index}, personal ~/.claude/CLAUDE.md, repo {instructions_file}.
```

## B — team PRs, reviews, CI

```
Inputs: {run_dir}/prs.jsonl (merged PRs; `drift` holds: body added/removed lines between the
first and final description, title renames, force-push count, commit headlines after the first
review, revert/rework-like commits; plus review thread openers with bot flag and review states),
{run_dir}/ci.json (failed runs by workflow), {run_dir}/linear.jsonl (completed issues; absent when no issue tracker is configured).
Find: (1) intent drift caught late — the PR ended up doing something other than what it first
said. There is no fixed wording for this: judge it from what changed — scope or approach
rewritten in the description, a renamed title, rework commits after review that change direction
(not just fix nits), reverts, review threads that question the premise. Force-pushes alone are
weak (rebases); count them only beside another signal. Read the before/after lines and say what
the misunderstanding was; group PRs by that kind of misunderstanding; (2) review findings that repeat
across ≥3 PRs (same kind of finding from humans or bots) — a check that should run before
review; (3) CI workflows failing repeatedly on PR branches for the same reason; (4) bugs whose
fix PRs show the same root-cause class. For each, name the skill step or rule that should
have prevented it (e.g. a PR skill's self-review step, a reviewer agent's checklist, a rule file).
```

## C — harness inventory, memory and subagents

```
Read: {run_dir}/agents.jsonl (every subagent dispatch: subagent_type, description, prompt_head,
prompt_chars), {instructions_file}, .claude/rules/*.md (headers + sizes), .claude/agents/*.md, ~/.claude/agents/*.md, .claude/skills/*/SKILL.md
(headers + step titles), ~/.claude/CLAUDE.md, ~/.claude/settings.json hooks, ~/.claude/skills/*/SKILL.md
frontmatter, the memory dir {memory_dir}. Repo tree: {repo_tree} (origin/{base_branch}).
Find: (1) the same rule stated in several places (merge candidates); (2) memory files of
type feedback that describe a recurring behaviour and belong one rung up (rule, skill step
or hook); (3) stale or contradicted guidance; (4) subagent fit — recurring dispatch jobs with no fitting agent (similar prompt_heads sent to
general-purpose/claude, long briefs retyped), agents that are never dispatched, and two agents
whose jobs overlap; propose `new-subagent`, a merge, or a delete, with the dispatch counts as
evidence and the full agent .md as the draft. Never propose deleting or merging an agent on
dispatch counts alone: agents.jsonl is one person's sessions, and the team may use it. That needs a second
source (PR history, review threads). A prompt_head like "Read and follow /path" points to the real
brief; read that file if it still exists; (5) budget pressure — {budget_note}. For every card, the
"one in, one out" line: what text it merges or deletes.
```
