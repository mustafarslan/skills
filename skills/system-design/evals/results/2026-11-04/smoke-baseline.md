# Smoke baseline, 2026-11-04

`claude plugin eval` (Claude Code 2.1.318, model claude-opus-5-5, judge haiku), the 5 smoke cases,
**1 run per arm** (with the skill / no plugin). n=1: read these as a direction, not a measurement.

## Run 2 (graders fixed: doc graders read the doc file) - the baseline to compare against

Cost $10.93. Graders passed: **with skill 31/32, without 25/32.**

| Case | With skill | Without | Graders the skill alone passed |
|---|---|---|---|
| url-shortener-capacity | 7/7 | 4/7 | ran the calculator; numbers match it; triggers sit between today's peak and 100x |
| expense-tool-small-team | 6/6 | 5/6 | trade-off table says, with a number, when to revisit the single deployable |
| chat-storage-hot-partition | 6/7 | 5/7 | ran the calculator |
| ledger-cassandra-steer | 4/4 | 4/4 | - (both pushed back on the Cassandra steer) |
| review-seeded-defects | 8/8 | 7/8 | no finding misstates what the doc says |

Both arms failed chat's "cascade walked step by step" grader. The skill's doc did walk one; the
judge voted 1/3 on a 42k-character file (the tool warns that LLM judges are noisy on long files).
That grader is now a `regex` grader over the doc.

## Run 1 (first grader version) - superseded

Cost $11.37. With skill 27/32, without 20/32. Three of the skill's five failures were grader
faults, confirmed by re-running chat with `--keep-temp` and reading the doc:
- doc-content graders used `focus: trace`, which shows the judge only the first and last 12
  messages, so a doc written mid-run was invisible;
- chat 01 demanded ~400 GB/day from a 200-byte message the prompt never stated (the skill
  assumed 500 bytes and labelled it);
- review 07 capped findings at 9; the skill's 11 findings were real.

Note: the plugin copy's description was updated mid-run (all prompts invoke `/system-design`
explicitly, so it could not change which skill loaded).

## What the baseline did not show

The no-skill model also handled the ledger steer and the seeded review well. Those two cases
measure little at this model level; sharpen them (a subtler steer, a subtler defect) before
relying on them.

## Grader check after the fixes

One run of `chat-storage-hot-partition` with the final skill and the regex cascade grader:
**7/7** (the regex grader matched the doc's cascade section). Cost $2.39.

Total eval spend on 2026-11-04: about $50 (smoke runs 1-2, one keep-temp re-run, pruning,
five ablations, this check, and $0.13 of a run stopped by mistake).
