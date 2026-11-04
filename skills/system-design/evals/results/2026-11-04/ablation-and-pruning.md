# Rule ablation and reference pruning, 2026-11-04

Same setup as the smoke baseline (run 2 graders), skill arm only, **1 run each**. With n=1 a
single grader flip is within noise; nothing was deleted on a result that was not clean.

## Rule ablation (one standing rule deleted, its mapped case run once)

| Rule removed | Case | Full skill | Without the rule | Change | Decision |
|---|---|---|---|---|---|
| R2 numbers from the script | url-shortener-capacity | 7/7 | 7/7 | none | **kept**: phase 2 still instructs the calculator, so the behaviour was not unprompted; the rule also covers phases 6-8 |
| R3 boring by default | expense-tool-small-team | 6/6 | 5/6 | introduced infrastructure the 4-person tool does not need | **kept** - the rule changes behaviour |
| R4 trade-off rows with triggers | chat-storage-hot-partition | 6/7 | 5/7 | lost the calculator-derived, labelled figures | **kept** |
| R6 push back with numbers | ledger-cassandra-steer | 4/4 | 4/4 | none - and the no-skill baseline also passed 4/4 | **kept, case too easy**: the steer breaks two invariants the doc states as given; write a subtler steer before judging this rule |
| R8 name what breaks first | chat-storage-hot-partition | 6/7 | 7/7 | one grader flipped to pass | **kept** - noise at n=1 |

Cost: $11.92 for the five runs.

## Reference pruning (batch: textbook "K" sections removed from the four references the smoke cases load)

Removed: the store comparison table and B-tree/LSM primer and IDs (data-storage), time and clocks
and failure models (distributed-correctness), transport choices (network-edge-api), DDD
definitions and named patterns (services-architecture) - each replaced by its one trap/default
line. 60 of 426 lines.

| | Graders passed |
|---|---|
| Full skill | 31/32 |
| Pruned | 29/32 (chat: exact partition key; review: precision) |

**Decision: not pruned.** Two graders dropped; at n=1 that is ambiguous, and the rule was to
keep any deletion only when no grader drops. Cost $10.17.

## Next step

Re-run both with the full protocol (3 runs per arm) before deleting anything: rules first
(R2, R6, R8), then pruning one file at a time.
