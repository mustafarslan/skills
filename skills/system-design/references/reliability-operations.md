# Reliability and operations

## Contents
- [How systems actually fail: cascades](#how-systems-actually-fail-cascades)
- [Resilience patterns](#resilience-patterns)
- [Degradation modes](#degradation-modes)
- [Health checks and probes](#health-checks-and-probes)
- [Disaster recovery](#disaster-recovery)
- [Multi-AZ, multi-region, cells](#multi-az-multi-region-cells)
- [Observability](#observability)
- [Capacity and load testing](#capacity-and-load-testing)
- [Sources](#sources)

## How systems actually fail: cascades
Walk at least one cascade end to end in every design, with the defence at each step:

1. A trigger: cache flush or cold start, a deploy, a slow dependency (payment provider at 10 s),
   an AZ loss, a traffic spike, a bad config push.
2. Load moves: cache misses hit the DB; slow calls hold threads and connections.
3. Pools exhaust: DB connections, thread pools, file descriptors.
4. Timeouts fire upstream; **retries multiply load** (3 retries at 3 layers = up to 27x).
5. Queues back up; memory grows; health checks fail; instances restart and come back cold.
6. Recovery is blocked by the retry storm and cold caches (metastable failure).

Also check: thundering herd on reconnect, a single hot shard taking the whole cluster's pool,
synchronous logging or tracing to a slow backend adding latency to every request.

## Resilience patterns
| Pattern | Use | Watch |
|---|---|---|
| Timeouts | on every network call, shorter than the caller's | too long = held resources; too short = false failures |
| Retries with exponential backoff + full jitter | transient errors on idempotent calls | retry only at one layer; cap attempts; retry budgets (e.g. retries ≤ 10% of requests) |
| Circuit breaker | stop calling a failing dependency, fail fast | needs a fallback; half-open probing |
| Bulkhead | separate pools per dependency/tenant | sizing |
| Load shedding / admission control | reject early under overload, by priority | return 429/503 with Retry-After |
| Back-pressure | bounded queues, slow producers | lag alerts |
| Dead-letter queue | park poison messages | alert and replay tooling |
| Request hedging | tail latency on idempotent reads | adds load; cap it |
| Static stability | keep working on last-known config if the control plane dies | stale config window |

## Degradation modes
Decide in advance what turns off first: recommendations, personalisation, search freshness,
non-critical writes (queue them), images at lower quality. Serve stale cache (`stale-if-error`).
Feature flags as kill switches. State which user journeys must survive.

## Health checks and probes
- **Liveness**: is the process wedged? Cheap, no dependency checks; failure → restart. If it
  checks the DB, a DB blip restarts the whole fleet.
- **Readiness**: can it serve now (warm, dependencies reachable)? Failure → removed from the load
  balancer, not restarted.
- **Startup**: slow boot without being killed.
- Load-balancer checks: shallow; see network-edge-api.md.

## Disaster recovery
| Strategy | RPO | RTO | Cost |
|---|---|---|---|
| Backup and restore | hours | up to ~24 h | lowest |
| Pilot light (data replicated, minimal infra off) | minutes | tens of minutes | low |
| Warm standby (scaled-down copy running) | seconds | minutes | medium |
| Multi-site active/active | near zero | near zero | highest |
(AWS Well-Architected REL13-BP02 characterisation.)
- Set RPO/RTO **per data tier** (ledger vs analytics vs logs).
- Restore time grows with data size: compute it; test restores on a schedule.
- DR that is never exercised does not work: game days, region evacuation drills.
- Protect against logical disasters (bad migration, ransomware, operator error): point-in-time
  recovery, immutable/offsite backups, delayed replicas.

## Multi-AZ, multi-region, cells
- Multi-AZ is the baseline for production (AZ loss is a normal event).
- Multi-region: for latency to global users, regional failure tolerance, or residency. Costs:
  data replication and consistency choices, 2x infra, much harder testing. Active/passive first;
  active/active only with a conflict strategy per data type.
- **Cells**: independent copies of the stack, each serving a slice of users/tenants, with a thin
  routing layer. Limits blast radius of bad deploys and poison requests; adds a router and
  cross-cell operations.
- Avoid cross-region synchronous calls in the request path.

## Observability
- **Metrics**: cheap, aggregated time series - RED (rate, errors, duration) per endpoint, USE
  (utilisation, saturation, errors) per resource, plus business metrics (orders/min). Watch label
  cardinality (no user IDs in metric labels).
- **Logs**: structured (JSON), with request/trace IDs; sampled at high volume; shipped
  asynchronously so a slow log pipeline never slows requests; PII scrubbed.
- **Traces**: distributed tracing (OpenTelemetry, W3C Trace Context) across services and
  queues; head sampling for volume, tail sampling to keep errors and slow traces.
- **Alerting**: page on SLO burn rate (user-facing symptoms), not on every cause; runbook per
  alert.
- Dashboards: the first one an on-call engineer opens should answer "is it us, a dependency, or
  a deploy?".
- Telemetry must never amplify an outage: bounded buffers, drop rather than block.

## Capacity and load testing
- Plan headroom (run at ≤ 50-70% of tested capacity at peak); autoscale on the right signal
  (queue lag, concurrency) with warm-up time and maximums.
- Load-test at the calculated peak and at 2-3x, including cache-cold scenarios and dependency
  slowness.

## Proving correctness before launch
State how the risky parts get tested, not just built:
- property-based tests over random interleavings of state machines (reservation, payment,
  sync) - the invariant ("never oversell", "no lost edit") is the property;
- simulators for external dependencies that inject duplicate, late, reordered and missing
  callbacks;
- fault injection and game days: kill the cache, fail over the DB, drop webhooks, partition a
  zone - in staging first, then production with a blast-radius limit;
- canaries that test the invariant in production (e.g. a revoked test user must not see a
  test document).

## Sources
- AWS Well-Architected, Reliability pillar, REL13-BP02 (DR strategies): docs.aws.amazon.com/wellarchitected/latest/reliability-pillar/rel_planning_for_recovery_disaster_recovery.html
- AWS Builders' Library, "Timeouts, retries, and backoff with jitter": aws.amazon.com/builders-library/
- Google SRE book, "Addressing Cascading Failures": sre.google/sre-book/addressing-cascading-failures/
