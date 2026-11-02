# Services, boundaries and communication

## Contents
- [Monolith, modular monolith, microservices](#monolith-modular-monolith-microservices)
- [Finding boundaries (DDD)](#finding-boundaries-ddd)
- [Inside a service: hexagonal, onion, clean](#inside-a-service-hexagonal-onion-clean)
- [Synchronous vs asynchronous](#synchronous-vs-asynchronous)
- [Queues vs logs](#queues-vs-logs)
- [Delivery semantics and back-pressure](#delivery-semantics-and-back-pressure)
- [Distributed transactions: sagas](#distributed-transactions-sagas)
- [Outbox and change data capture](#outbox-and-change-data-capture)
- [CQRS and event sourcing](#cqrs-and-event-sourcing)
- [Microservice patterns worth naming](#microservice-patterns-worth-naming)
- [Anti-patterns](#anti-patterns)

## Monolith, modular monolith, microservices
- **Default: modular monolith.** One deployable, modules with enforced boundaries (separate
  packages, no reaching into another module's tables, calls through module APIs). Cheap
  transactions, simple debugging, one pipeline.
- **Split a service out when one of these holds** (say which):
  - independent deploy cadence is blocked by other teams (team count > ~3-4 on one deployable);
  - very different scaling or hardware (GPU inference vs CRUD; a hot path at 100x the rest);
  - different reliability or security tier (payments, PII vault);
  - a different tech stack is genuinely needed.
- Costs of each split: network calls (latency, partial failure), no cross-service transactions,
  distributed tracing, versioned contracts, a pipeline and on-call per service.
- Conway's law: the architecture will mirror team communication. Align service ownership with
  teams; one team per service, never one service per developer.

## Finding boundaries (DDD)
- **Bounded context**: a part of the domain with its own model and language ("order" in sales vs
  in fulfilment). Boundaries go where the language changes.
- **Aggregate**: a cluster of entities changed together under one invariant, the unit of
  transactional consistency (an order with its lines). Keep them small; reference other
  aggregates by ID; consistency between aggregates is eventual.
- **Entities** have identity; **value objects** are defined by their values (money, address).
- **Context map**: how contexts relate - customer/supplier, conformist, anti-corruption layer
  (translate a legacy or external model at the edge), shared kernel (use sparingly).
- **Domain events** ("OrderPlaced") are how contexts learn about each other without coupling.

## Inside a service: hexagonal, onion, clean
- All three keep the **domain core** free of frameworks and infrastructure; dependencies point
  inward.
- **Hexagonal (ports and adapters)**: the core defines ports (interfaces) - driving ports (use
  cases called by HTTP/gRPC/CLI adapters) and driven ports (repositories, message publishers,
  external APIs) implemented by adapters.
- **Onion / clean**: the same idea as concentric layers - domain model, domain services,
  application services/use cases, infrastructure and UI outermost.
- Worth it when the domain logic is rich or the infrastructure will change (swap DB, broker,
  provider); overkill for thin CRUD - say so.
- In a design doc: one or two sentences per service ("hexagonal: order domain core; ports for
  Postgres repository, Kafka publisher, payment provider") unless a deep dive asks for more.

## Synchronous vs asynchronous
| | Synchronous (REST/gRPC) | Asynchronous (queue/stream) |
|---|---|---|
| When | caller needs the answer now | work can finish later; fan-out to many consumers; load levelling |
| Coupling | temporal: both must be up | caller unaffected by consumer downtime |
| Failure | cascades along the call chain | backlog grows; needs DLQ and replay |
| Latency | sum of the chain | end-to-end delay, but fast acknowledgement |
- A synchronous chain of 4+ services is a distributed monolith: availability multiplies down and
  latency adds up. Collapse it, cache, or go async.

## Queues vs logs
| | Message queue (SQS, RabbitMQ) | Log / stream (Kafka, Kinesis, Pulsar) |
|---|---|---|
| Model | message consumed and deleted; competing consumers | append-only, retained; each consumer group tracks its offset |
| Good for | task distribution, load levelling, per-message retries | many independent consumers, replay, event sourcing, stream processing |
| Ordering | usually none, or FIFO groups at lower throughput | per partition |
| Watch | poison messages (DLQ), visibility timeouts | partition count limits consumer parallelism; hot partition keys |

## Delivery semantics and back-pressure
- Networks and brokers give **at-most-once** or **at-least-once**. "Exactly once" in practice is
  at-least-once delivery + **idempotent consumers** (dedup table keyed by message ID, or naturally
  idempotent writes). See distributed-correctness.md.
- Back-pressure: bounded queues, consumer lag alerts, producers that slow down or shed load,
  autoscaling consumers on lag, not CPU.
- Poison messages go to a **dead-letter queue** after N attempts, with alerting and a replay tool.

## Distributed transactions: sagas
- A saga is a sequence of local transactions, each with a **compensating action** to undo it
  (reserve stock → charge card → if charge fails, release stock).
- **Orchestration**: a coordinator (often a workflow engine such as Temporal or Step Functions)
  drives the steps. Clear state, easy to observe, central point to scale.
- **Choreography**: services react to each other's events. Loose coupling; the flow is implicit and
  hard to trace; risk of event loops. Fine for 2-3 steps, orchestration beyond.
- Compensations must be idempotent and may themselves fail; design the stuck state and the
  manual repair path.
- Avoid two-phase commit across services: it blocks on coordinator failure and couples
  availability.

## Outbox and change data capture
- The **dual-write problem**: writing to the DB and publishing to a broker are two operations; a
  crash between them loses or invents an event.
- **Transactional outbox**: write the event to an outbox table in the same DB transaction; a relay
  (poller or CDC) publishes it. At-least-once, so consumers dedup.
- **CDC** (e.g. Debezium on the write-ahead log) streams committed changes; good for feeding
  search indexes, caches, analytics without touching application code.

## CQRS and event sourcing
- **CQRS**: separate write model (commands, invariants) from read models (denormalised views per
  query). Read models are updated asynchronously - say how stale they may be.
- **Event sourcing**: store the events as the source of truth; state is a fold over them. Full
  audit and time travel; costs: schema evolution of events, snapshots, rebuild time, GDPR
  deletion (crypto-shredding). Use where audit/history is the product (ledgers), not by default.

## Microservice patterns worth naming
API gateway; BFF; service discovery; service mesh (mTLS, retries, telemetry in a sidecar or
node proxy - cost: latency and operational complexity); circuit breaker; bulkhead; sidecar;
strangler fig (evolution-migration.md); database per service; anti-corruption layer.

## Anti-patterns
- Shared database between services (hidden coupling; schema changes need every team).
- Entity services ("CustomerService", "OrderService") with no behaviour - chatty, distributed
  monolith.
- Microservices for a team of five.
- Events that carry only IDs, forcing every consumer to call back (fan-in storm) - include the
  data consumers need, versioned.
