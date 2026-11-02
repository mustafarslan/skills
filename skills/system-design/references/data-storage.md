# Data storage

## Contents
- [Choosing a store by access pattern](#choosing-a-store-by-access-pattern)
- [Storage engines: B-tree vs LSM](#storage-engines-b-tree-vs-lsm)
- [Schema, keys and indexes](#schema-keys-and-indexes)
- [Transactions, isolation and locks](#transactions-isolation-and-locks)
- [Replication](#replication)
- [Partitioning and sharding](#partitioning-and-sharding)
- [Hot keys and contention](#hot-keys-and-contention)
- [Caching](#caching)
- [IDs](#ids)
- [Deploying and operating the database](#deploying-and-operating-the-database)

## Choosing a store by access pattern
Write the queries first; pick the store that serves them. Default to a relational database
unless an access pattern rules it out.

| Store | Strong at | Weak at | Examples |
|---|---|---|---|
| Relational (OLTP) | transactions, joins, constraints, ad-hoc queries, mature tooling | horizontal write scaling (needs sharding), very high write rates | PostgreSQL, MySQL |
| Distributed SQL | relational + horizontal scale + strong consistency | higher write latency (consensus), cost, operational novelty | Spanner, CockroachDB, YugabyteDB |
| Key-value / wide-column | huge write rates, predictable key lookups, multi-DC | joins, ad-hoc queries, secondary indexes; model per query | DynamoDB, Cassandra, ScyllaDB |
| Document | flexible nested records read as a unit | cross-document transactions and joins (limited) | MongoDB |
| In-memory | sub-ms reads, counters, rate limits, leaderboards | durability and size (RAM-bound) | Redis, Memcached |
| Search | full-text, faceting, relevance | being the source of truth; write-heavy updates | Elasticsearch/OpenSearch |
| Time-series | append-heavy metrics, downsampling, time-range queries | random updates | TimescaleDB, Prometheus, InfluxDB |
| Columnar / OLAP | scans and aggregates over billions of rows | point updates, high-QPS lookups | ClickHouse, BigQuery, Snowflake, Parquet + engine |
| Graph | multi-hop relationship queries | bulk scans, sharding | Neo4j |
| Object storage | cheap, durable blobs at any size | low-latency small reads, in-place updates | S3, GCS |
| Vector | similarity search over embeddings | exact filtering at scale (check filtered-search support) | pgvector, dedicated vector DBs |
- Polyglot persistence multiplies operations work: each extra store needs backups, upgrades,
  monitoring and someone who knows it. Justify each with an access pattern the default fails.

## Storage engines: B-tree vs LSM
- **B-tree** (most relational DBs): in-place updates of pages; fast reads and range scans; random
  writes cost write amplification and I/O. Good for read-heavy, mixed OLTP.
- **LSM tree** (Cassandra, RocksDB, ScyllaDB): writes go to a log and an in-memory table, flushed
  to sorted files, merged by **compaction**. Very high sequential write throughput; reads may
  check several files (bloom filters help); compaction needs I/O and disk headroom or writes stall.
- Read-heavy (100:1) → B-tree + replicas + cache. Write-heavy (telemetry, chat, location) → LSM, or
  batch/queue writes into a B-tree store.

## Schema, keys and indexes
- Normalise for the write model; denormalise deliberately for hot reads (and say how the copies
  stay in sync).
- Every index speeds a read and slows every write; list the index each query uses.
- Wide-column/KV: design the **partition key** for even spread and the **sort key** for the query
  (e.g. `PK = chat_id, SK = message_seq`). One table per access pattern is normal.
- Schema evolution: additive changes, expand/contract migrations (add column → backfill → switch
  reads → drop old), online DDL tools for big tables.

## Transactions, isolation and locks
| Isolation | Prevents | Still allows |
|---|---|---|
| Read committed | dirty reads | non-repeatable reads, lost updates, write skew |
| Repeatable read / snapshot | the above + non-repeatable reads | write skew (in snapshot isolation) |
| Serializable | all of the above | - (costs throughput / aborts) |
- **Pessimistic locking** (`SELECT ... FOR UPDATE`): blocks competitors; simple for short
  transactions; risks lock waits, deadlocks (lock in a consistent order), and pool exhaustion if
  locks are held across slow calls. Never hold a DB lock across a network call or user think time.
- **Optimistic concurrency** (version column, compare-and-set; MVCC underneath): no locks held;
  conflicts fail and retry. Good when conflicts are rare; under heavy contention retries thrash.
- **Atomic conditional updates** often beat both: `UPDATE stock SET qty = qty - 1 WHERE sku = ? AND qty > 0`.
- **Distributed locks** (Redis, ZooKeeper, etcd) need leases and **fencing tokens** (monotonic
  numbers the storage checks), or a paused process can act after its lease expired.
- Long transactions block vacuum/compaction and replication; keep them short.

## Replication
- **Single-leader**: writes to one primary, replicas serve reads. Async replicas lag (read-your-
  writes needs routing the user to the primary or waiting for a position); sync replicas cost
  write latency. Failover can lose the last async writes.
- **Multi-leader**: writes in several regions; needs conflict resolution (last-write-wins loses
  data; CRDTs or app-level merge). Use only when multi-region writes are required.
- **Leaderless** (Dynamo-style): quorum reads/writes (`R + W > N` for overlap); hinted handoff and
  read repair; tunable per request.
- Replicas are not backups: a bad `DELETE` replicates. Keep point-in-time recovery.

## Partitioning and sharding
- Vertical: split tables/columns or move a domain to its own DB (federation). Do this before
  sharding.
- Horizontal (sharding) strategies:
  - **Range** (by time or key range): efficient range scans; hot spots on the newest range.
  - **Hash / consistent hashing** (with virtual nodes): even spread, cheap rebalancing; no range
    queries across keys.
  - **Directory / lookup**: a mapping service decides; flexible (move a whale tenant), but the
    directory is a dependency to cache and replicate.
  - **Geo** (geohash/S2/H3): proximity queries; dense cells get hot.
- Pick the **shard key** from the dominant query (tenant_id, user_id, chat_id). Queries that span
  shards become scatter-gather; cross-shard transactions need sagas or a distributed SQL DB.
- Plan resharding from day one (more logical shards than nodes, so you move shards, not rows).
- Size it: data per shard, QPS per shard, and the rebuild/restore time of one shard.

## Hot keys and contention
- Celebrity user, viral post, flash-sale SKU, a giant tenant.
- Remedies: **sharded counters** (split one counter into N sub-keys, sum on read); request
  coalescing; local in-process cache for the hottest keys; write batching; salting the key;
  moving a whale to dedicated capacity.

## Caching
| Pattern | How | Risk |
|---|---|---|
| Cache-aside | app reads cache, on miss reads DB and fills | stale until TTL/invalidation; cold-start misses |
| Read-through / write-through | cache layer loads and writes the DB synchronously | write latency; cache is in the write path |
| Write-behind / write-back | write to cache, flush to DB later | data loss if the cache dies before flushing |
- Invalidation: TTL + explicit delete on write (delete, don't update, to avoid races); or CDC-driven
  invalidation.
- Stampede on a hot key's expiry: request coalescing (single flight), early probabilistic refresh,
  TTL jitter.
- **Cache penetration** (queries for keys that do not exist): negative caching or a bloom filter.
- Eviction: LRU default; LFU or TinyLFU-style for skewed popularity.
- Big values or big collections in Redis block its single thread and hurt persistence; cap value
  size, split collections.
- Size it from the hot set (calculator `cache` section) and decide what happens when the cache
  is empty (can the DB take the full read load? If not, warm before cut-over).

## IDs
- Auto-increment: simple, single-node, leaks volume, hard to shard.
- UUIDv4: random, no coordination, poor index locality. UUIDv7 / ULID: time-ordered, index-friendly.
- Snowflake-style (time + worker + sequence): 64-bit, sortable, needs worker-ID assignment and
  clock care.

## Deploying and operating the database
- Managed vs self-run: managed unless the team has the skills and a reason.
- Read replicas per region for local reads; one write region unless multi-region writes are a
  requirement.
- Connection pooling (PgBouncer or equivalent) - app instances × pool size must stay under the
  DB's connection limit.
- Backups with point-in-time recovery, restore tested on a schedule, and restore time measured
  against RTO (bigger nodes take longer to restore).
- Online schema changes and backfills throttled to protect production traffic.
