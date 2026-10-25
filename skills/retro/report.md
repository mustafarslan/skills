# Report template (step 6)

Concise. No greeting, no recap, no adjectives. Tables first. Same content for an artifact
or a Google Doc; a copy always goes to `{run_dir}/report.md`.

```
# Retro {run_id} · {since} → {today} ({A} active days of {C}; idle skipped: {skipped}) · {flag}

<!-- {E} = PRs analyst B judged as drifted, not PRs with any signal. -->
Evidence: {S} sessions / {T} typed turns · {P} merged PRs ({E} drifted, {H} human review threads) · {F} failed CI runs · {L} completed issues

## Proposals

| # | Kind | Change | Why | Evidence | Rung | In |
|---|------|--------|-----|----------|------|----|
| 1 | edit / new-subagent / delete | `target` — the edit in one line | the recurring cost | 7 sessions, PR #118, #131 | memory → hook | harness |
…5 rows

### 1 · {slug}
What changes: exact diff or new text (collapsed in an artifact).
One in, one out: what it merges or deletes.
Lands via: personal file (direct, backed up) | repo PR.

…one block per proposal

## Also found
- {slug} — one line, evidence count  (pull in on request)

## Last cycle's fixes
| Key | Applied | Before | Now | Verdict |
| … | 2026-10-06 | 9 turns / 14 d | 1 turn / 14 d | worked |
```
