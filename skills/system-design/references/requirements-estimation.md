# Requirements and estimation

## Contents
- [Functional requirements and non-goals](#functional-requirements-and-non-goals)
- [Non-functional requirements](#non-functional-requirements)
- [SLI, SLO, SLA and error budgets](#sli-slo-sla-and-error-budgets)
- [Contradictions to catch](#contradictions-to-catch)
- [Estimation method](#estimation-method)
- [Reference numbers](#reference-numbers)
- [Sources](#sources)

## Functional requirements and non-goals
- Write 3-6 core use cases as verbs on nouns ("a buyer reserves stock for 10 minutes"). Rank
  them; design for the top ones and say which are out of scope.
- Non-goals are decisions: "no cross-region writes in v1", "no real-time analytics". They stop
  the design from growing to cover everything.

## Non-functional requirements
Every NFR gets a number and the condition it holds under:

| Quality | Write it as |
|---|---|
| Latency | p50/p99 per operation, server-side, at peak load ("checkout p99 < 300 ms at 3x average") |
| Availability | per user journey, with the measurement window ("search 99.9% monthly") |
| Durability | data loss tolerated (usually none for writes acknowledged to the user) |
| Consistency | per data type: read-your-writes, monotonic reads, linearizable, bounded staleness (and the bound) |
| Throughput | peak sustained and burst, reads and writes separately |
| RPO / RTO | data loss and downtime tolerated in a disaster, per tier of data |
| Scale horizon | users, data and traffic in 1 and 3 years |
| Cost | budget per month or per request/user |
| Compliance | residency, retention, deletion, audit, certifications |
| Operability | team size, on-call model, skills |

## SLI, SLO, SLA and error budgets
- **SLI**: what is measured (fraction of requests under 300 ms, fraction of 2xx).
- **SLO**: the internal target for the SLI over a window (99.9% over 30 days). The gap to 100% is
  the **error budget** (43 min/month at 99.9%) - spend it on releases and experiments; when it is
  gone, slow down.
- **SLA**: the contract with customers, with penalties; set it looser than the SLO.
- Nines: 99% ≈ 7.3 h/month, 99.9% ≈ 43.8 min, 99.95% ≈ 21.9 min, 99.99% ≈ 4.4 min. Components in
  series multiply (0.999 × 0.999 = 0.998); redundant replicas combine as 1 − Π(1 − a), but only
  if their failures are independent (they share region, DNS, deploys and config, so they are
  not fully). The calculator's `--serial/--parallel` does this math.

## Contradictions to catch
- Global low-latency writes + strong consistency (cross-region consensus costs a WAN round trip,
  50-150 ms).
- 99.99% availability + a single region or a single-writer database.
- Tiny team + many services, multiple datastores, self-run Kafka/Cassandra.
- Immutable event log + "delete my data" (GDPR): needs crypto-shredding or compaction.
- Low cost + very low latency for large models.
Name the conflict, quantify it, and ask the user which side wins.

## Estimation method
1. Start from users and actions: DAU × actions/user/day → per-day counts → ÷ 86,400 for average
   per second → × peak factor (3x is a common starting assumption; measure the real ratio).
   Count **physical** writes, not logical ones: one delivery that is enqueued, claimed, attempted
   1.3 times and marked done is ~4 row-writes. Pass `--writes-per-user` as the physical count.
2. Storage: writes/day × bytes/write × (1 + index overhead) × retention, then × replication.
3. Bandwidth: peak QPS × payload.
4. Cache: a share of the daily read volume (80/20 is a starting heuristic), and check it fits.
5. Concurrency (Little's law): in-flight = rate × time in system. Busy DB connections =
   DB queries/s × seconds per query.
6. Then ask what each number rules out. A number that rules nothing in or out was not worth
   computing.
Use the calculator for all of it; mark guessed inputs with `--assumed` to get a sensitivity band.

## Reference numbers
Orders of magnitude, not benchmarks; measure your own hardware.

| Operation | Roughly |
|---|---|
| Main-memory reference | 100 ns |
| SSD random read | ~16-100 µs |
| Round trip within a datacenter / AZ | ~0.5 ms or less |
| Round trip across AZs in a region | 1-2 ms |
| Round trip across regions / continents | 50-150 ms |
| Indexed read on a well-tuned relational DB node | tens of thousands/s per node |
| Writes on one relational primary | ~10k/s comfortable; tens of thousands is the sharding zone (depends on fsync, indexes, row size) |
| Redis, one instance, small keys, no pipelining | 100k+ ops/s (its own benchmark shows ~180k SET/s) |
| PostgreSQL default `max_connections` | typically 100; pool (PgBouncer) beyond that |

The calculator encodes the throughput figures as soft **triggers**, each with its basis.

## Sources
- Hello Interview, "Core concepts" (throughput heuristics, latency ranges): hellointerview.com/learn/system-design/in-a-hurry/core-concepts
- Colin Scott, interactive latency numbers: colin-scott.github.io/personal_website/research/interactive_latency.html
- Redis benchmarks: redis.io/docs/latest/operate/oss_and_stack/management/optimization/benchmarks/
- PostgreSQL connection settings: postgresql.org/docs/current/runtime-config-connection.html
- Google SRE book, "Service Level Objectives": sre.google/sre-book/service-level-objectives/
