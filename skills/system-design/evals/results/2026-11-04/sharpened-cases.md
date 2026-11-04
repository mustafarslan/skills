# Sharpened cases, 2026-11-04 (3 runs per arm)

The smoke baseline showed the model without the skill already passing `ledger-cassandra-steer`
and `review-seeded-defects`. Two harder cases replaced them in the smoke set:

- `ledger-cache-steer`: a plausible performance steer - "cache wallet balances in Redis (5 s TTL)
  and check the cached balance before each debit" - that silently breaks the never-negative
  invariant (two concurrent transfers read the same cached balance).
- `review-subtle-defects`: six defects that each look fine on a first read (dedup window shorter
  than the retry window, outbox rows deleted before the publish is acknowledged, read-then-write
  stock decrement at READ COMMITTED, a breaker fallback that marks orders paid, order pages read
  from a lagging replica, a DNS TTL longer than the RTO).

`claude plugin eval`, Claude Code 2.1.318, claude-opus-5-5, judge haiku. Cost $6.88.

| Case | With skill | Without | Difference |
|---|---|---|---|
| ledger-cache-steer | 15/15 | 14/15 | without the skill, one run did not use the doc's load numbers |
| review-subtle-defects | 21/21 | 21/21 | none |

## Reading

At this model level, pushing back on a requirement-breaking steer (R6) and finding defects in a
review happen without the skill, even when the problems are subtle. The skill's measured value
is elsewhere: calculator-backed numbers, triggers at plausible loads, labelled assumptions and
the doc discipline (smoke baseline: 31/32 vs 25/32).

R6 and review mode are **kept**: both cost a few lines, and a weaker or future model may not
behave this way unprompted. Re-run these two cases after each model change; if the plain
model ever fails them, the gap is what R6 and review mode are there to close.
