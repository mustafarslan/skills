# Trigger evals, 2026-11-04

Method: a fresh agent (Sonnet) routes each query in `trigger-evals.json` using only skill
descriptions: system-design plus the skills it competes with (engineering:system-design,
engineering:architecture, design-doc, spm, pr-review, data:sql-queries). One run per version.

| Description | Should load (9) | Shouldn't load (9) | Total | Misses |
|---|---|---|---|---|
| Old (972 chars) | 9 | 8 | 17/18 | #15 "write interview questions" loaded it (low confidence) |
| change.md proposal (753 chars) | 8 | 8 | 16/18 | #8 "write an ADR" went to engineering:architecture; #15 loaded it |
| Shipped (revised, see SKILL.md) | 9 | 9 | 18/18 | none; #8 at medium confidence |

The shipped text adds "write or review an ADR" and two exclusions ("explaining a single concept",
"writing interview question lists") to the change.md proposal. n=1 per version: re-run with
skill-creator's description optimizer (3 runs, train/test split) before trusting small gaps.
