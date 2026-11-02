# Distributed correctness

## Contents
- [CAP and PACELC](#cap-and-pacelc)
- [Consistency models, in user terms](#consistency-models-in-user-terms)
- [Consensus and leader election](#consensus-and-leader-election)
- [Quorums](#quorums)
- [Idempotency and exactly-once](#idempotency-and-exactly-once)
- [Ordering](#ordering)
- [Time and clocks](#time-and-clocks)
- [Failure models](#failure-models)
- [End-to-end correctness](#end-to-end-correctness)

## CAP and PACELC
- **CAP**: during a network **P**artition, choose **C**onsistency (refuse some requests) or
  **A**vailability (answer, possibly stale or conflicting). Partitions are rare, so CAP alone says
  little about everyday behaviour.
- **PACELC**: if Partitioned, A or C; **E**lse (normal operation), **L**atency or **C**onsistency.
  - PA/EL: leaderless Dynamo-style stores (Cassandra, DynamoDB by default) - available and fast,
    eventually consistent; tunable per request.
  - PC/EC: consensus-based stores (Spanner, CockroachDB, etcd) - consistent always; pay a
    consensus round trip on writes (cross-region: 50-150 ms).
  - Single-leader relational with async replicas: consistent on the primary, stale on replicas;
    failover may lose recent writes.
- Decide **per data type**, not per system: balances and inventory PC/EC; likes, view counts,
  presence PA/EL.

## Consistency models, in user terms
| Model | What the user sees |
|---|---|
| Linearizable | everyone sees the latest write once it is acknowledged |
| Sequential / causal | effects never appear before their causes (a reply never before the post) |
| Read-your-writes | I see my own change immediately; others may lag |
| Monotonic reads | I never see data go backwards between requests |
| Bounded staleness | at most N seconds / versions behind |
| Eventual | converges if writes stop; say how long and what anomalies appear meanwhile |
For every "eventual" in a design, state: the window (e.g. p99 replica lag 2 s), who sees stale
data, and what a decision made on stale data costs (oversold item, duplicate email).

## Consensus and leader election
- Raft / Paxos: a majority (quorum) of nodes agrees on a log; tolerates `f` failures with `2f+1`
  nodes. Use via etcd, ZooKeeper, Consul, or a database that embeds it - do not implement it.
- Uses: leader election, configuration, locks with fencing, metadata.
- Cost: every write needs a majority round trip; a 5-node cluster across 3 regions pays WAN
  latency per write.
- Split brain is prevented by quorums plus fencing tokens; a "leader" without a quorum lease must
  stop.

## Quorums
- N replicas, write to W, read from R: `R + W > N` makes reads see the latest acknowledged write
  (barring sloppy quorums and concurrent writes). N=3, W=2, R=2 is the common choice.
- Sloppy quorums and hinted handoff raise availability but break that guarantee during failures.

## Idempotency and exactly-once
- Retries are certain (clients, LBs, brokers). So every mutating operation must be safe to repeat.
- Techniques: client-supplied idempotency key stored with the result; natural idempotency
  (`SET status = 'paid'` rather than `balance = balance - x`); dedup table of processed message
  IDs in the same transaction as the effect; conditional writes on a version.
- Exactly-once processing = at-least-once delivery + idempotent effect (or a transaction that
  covers both offset commit and effect, as in Kafka transactions within Kafka).
- Retain dedup keys at least as long as the longest retry window.

## Ordering
- Total order is expensive (single partition / single leader). Most systems need order only per
  entity: per user, per chat, per account - use that as the partition key.
- Per-entity sequence numbers let consumers detect gaps and reorder.
- Consumers that must handle out-of-order events: compare versions/timestamps, ignore older.

## Time and clocks
- Wall clocks drift and jump (NTP corrections); never order events across machines by wall clock
  alone, and never use it for locks without bounds.
- Logical clocks (Lamport) give a consistent order; vector clocks detect concurrency.
- Hybrid logical clocks combine both; Spanner-style TrueTime waits out a known uncertainty.
- Last-write-wins by timestamp silently drops concurrent writes - say whether that is acceptable.

## Failure models
- Crash-stop vs crash-recover; omission (lost messages); timing (slow, not dead - the hardest);
  Byzantine (only for adversarial settings like blockchains).
- A timeout cannot tell slow from dead. Design for the case where the "failed" call actually
  succeeded (hence idempotency).
- Gray failures: a node passes health checks but serves errors or is slow; detect from the
  client's view (error rates, latency outliers).

## End-to-end correctness
- The only reliable checks are end to end: reconciliation jobs that compare the ledger with the
  bank, the order DB with the warehouse, counts in source vs sink.
- Build repair paths (replay from the log, compensating entries) and audit logs that explain
  every state change.
