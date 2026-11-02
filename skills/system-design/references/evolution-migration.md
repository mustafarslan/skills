# Evolution and migration

## Contents
- [The 10x / 100x path](#the-10x--100x-path)
- [Brownfield: designing from what exists](#brownfield-designing-from-what-exists)
- [Zero-downtime migrations](#zero-downtime-migrations)
- [Backfills](#backfills)
- [Strangler fig and splitting a monolith](#strangler-fig-and-splitting-a-monolith)
- [Cells and blast radius](#cells-and-blast-radius)
- [Teams and ownership](#teams-and-ownership)
- [Simplify](#simplify)

## The 10x / 100x path
For each step, write: the trigger (a number from the trade-off table), what changes, what it
costs, and how to get there without downtime. A typical shape:

| Scale | Typical change | Trigger example |
|---|---|---|
| Today | modular monolith, one primary DB + replica, cache, CDN | - |
| 10x | read replicas and cache tiers, async work on queues, split the hottest module out, partition the largest table | peak reads > 20k/s; p99 > target at peak; one module's deploy blocks others |
| 100x | shard the write path, multi-region reads, cells, dedicated stores for specialised access patterns | peak writes > ~10k/s on the primary; data per node past restore-time budget; regional latency targets |
Do not build the 100x design today; show that today's design does not block it (keys that can
become shard keys, IDs that don't need a central sequence, APIs that are idempotent).

## Brownfield: designing from what exists
- Inventory: current components, data sizes and growth, traffic, pain points with numbers,
  incidents, team ownership.
- Name the constraint that hurts now; design the smallest change that removes it, then the path
  beyond.
- Every target state needs a migration plan with a rollback at each step. A design without one
  is a wish.

## Zero-downtime migrations
- **Expand / contract** for schemas: add new (nullable/defaulted) → write both → backfill → read
  new → stop writing old → drop old. Each step deployable and reversible on its own.
- **Moving a datastore**: dual-write (or CDC from old to new) → backfill history → **shadow
  reads** (read both, compare, log mismatches) → switch reads by percentage → switch writes →
  keep the old store as a fallback for a while → decommission.
- Prefer CDC to application dual-writes when possible (dual-writes drift on partial failure).
- Define the verification: row counts, checksums per range, mismatch rate threshold to proceed.

## Backfills
- Throttled, resumable (checkpoint by key range), idempotent; run against replicas or snapshots
  where possible; monitor primary load and replication lag; ability to pause.
- Estimate duration: rows ÷ safe rows/s; days-long backfills are normal at scale - plan for code
  changes during them.

## Strangler fig and splitting a monolith
- Put a routing layer in front; move one capability at a time to the new system; route its
  traffic over gradually; delete the old code path.
- Extract by bounded context, starting with the one that has the clearest boundary and the
  strongest reason (scaling, team, reliability) - not the easiest.
- Data first: give the extracted module its own tables inside the monolith before moving them
  out; replace cross-module joins with API calls or replicated read models.

## Cells and blast radius
- A cell is a full, independent copy of the stack serving a partition of users/tenants; a thin
  router maps keys to cells.
- Use when one bad deploy, poison request or hot tenant must not take everyone down, or when a
  single stack hits its scaling ceiling.
- Costs: the router (a critical dependency), cross-cell queries and migrations of tenants
  between cells, more fleet to operate.

## Teams and ownership
- Each service or module has one owning team with the skills to run it on call.
- Team size bounds architecture: rough rule, one team (5-8 people) can own a handful of services
  well; beyond that, operational load wins.
- Platform investments (paved road: templates, CI/CD, observability defaults) pay off when there
  are many teams.
- Sequence the work: what ships first, what can run in parallel, where the risky
  decision gets validated early (spike, prototype, load test), and a phased launch (pilot
  group → waves) with the metric that gates each wave.

## Simplify
Before adding, ask what can be removed: a datastore that one table would cover, a queue that a
cron job would do, a service that could be a module. Staff-level designs are often notable for
what they leave out.
