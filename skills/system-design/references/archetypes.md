# Archetypes

Read only the section for the system's primary archetype (and a secondary one if it clearly has
one). Each section: what dominates the design, the questions to force in phase 1, and the traps.

## Contents
- [B2B multi-tenant SaaS](#b2b-multi-tenant-saas)
- [E-commerce and marketplaces](#e-commerce-and-marketplaces)
- [Fintech, payments and ledgers](#fintech-payments-and-ledgers)
- [Social, feeds and real-time](#social-feeds-and-real-time)
- [Media and content delivery](#media-and-content-delivery)
- [Geospatial and location](#geospatial-and-location)
- [Data-intensive and analytics](#data-intensive-and-analytics)
- [Platform, infrastructure and internal tooling](#platform-infrastructure-and-internal-tooling)
- [Mobile apps and offline-first clients](#mobile-apps-and-offline-first-clients)
- [Embedded and IoT](#embedded-and-iot)
- [AI, ML and GenAI systems](#ai-ml-and-genai-systems)

## B2B multi-tenant SaaS
**Dominated by:** tenant isolation, noisy neighbours, per-tenant configuration and permissions,
and the distribution of tenant size (one whale can be 30% of load).
**Force:** How many tenants, and how skewed (largest tenant's share of data and QPS)? Isolation
required by contract or regulation (dedicated DB, region, keys)? Per-tenant SLAs or tiers?
Customer-managed keys? SSO/SCIM? Data residency?
**Shape options:** pooled (shared tables, `tenant_id` on every row and every index, row-level
security) → bridge (schema or DB per tenant on shared infra) → silo (stack per tenant). Usually
pooled for the long tail with a path to move whales to dedicated cells.
**Traps:** forgetting `tenant_id` in a unique index or cache key (cross-tenant leaks); global rate
limits that let one tenant starve others; per-tenant schema migrations that take days at 10k
tenants; RBAC that cannot express "manager of this project" (consider ReBAC).

## E-commerce and marketplaces
**Dominated by:** inventory correctness under contention, checkout latency, burst traffic (flash
sales are 10-100x normal), and search/catalogue reads that dwarf writes.
**Force:** Peak vs normal traffic and how predictable the peak is? Can we oversell (and then
cancel/backorder) or never? Reservation hold time? Multi-warehouse? Price/stock staleness the
business accepts on product pages vs at checkout?
**Shape:** catalogue and search on read-optimised stores and caches (stale-tolerant); cart cheap
and loss-tolerant; checkout and inventory on a strongly consistent store with idempotent orders;
a queue/waiting room in front of flash sales.
**Traps:** one hot SKU row serialising every buyer (split stock into sub-counters or reserve in
batches); treating "eventual consistency" as acceptable for stock without saying how many
oversells per hour that means; payment callbacks without idempotency; charging immediately
when **authorize-then-capture** would let a payment that succeeds after its hold expired be
voided instead of refunded; a waiting room whose per-user polling is uncacheable (serve one
shared, CDN-cached watermark and let clients compute their own position).

## Fintech, payments and ledgers
**Dominated by:** correctness and auditability over latency - no lost or duplicated money,
reconciliation with external systems, regulatory retention.
**Force:** Double-entry ledger or balance updates? External PSP/bank semantics (async callbacks,
retries, partial failures)? Reconciliation frequency? Retention and audit requirements (often
5-10 years, immutable)? Multi-currency?
**Shape:** append-only double-entry ledger as the source of truth; balances derived; idempotency
keys end to end; outbox for events; state machines for payment lifecycles; daily reconciliation
that can find and repair drift.
**Traps:** updating balances in place without an entry log; trusting a PSP "success" without
reconciliation; floating-point money; exactly-once claims without dedup tables.

## Social, feeds and real-time
**Dominated by:** fan-out (write vs read), celebrity/hot keys, connection counts for push, and
ordering within a conversation.
**Force:** Follower distribution (max followers)? Feed freshness target? Ranked or chronological?
Message delivery guarantees and ordering scope (per chat)? Online presence? Message retention?
**Shape:** hybrid fan-out (push for normal users, pull for celebrities); per-conversation
sequence numbers; WebSocket gateways with a connection registry; LSM-style stores for message
history.
**Traps:** push fan-out to 50M followers per post; global ordering when per-chat ordering is
enough; gateway servers holding state with no reconnect/resume protocol.

## Media and content delivery
**Dominated by:** egress bandwidth and cost, transcoding pipelines, upload resumability, CDN hit
ratio.
**Force:** Upload size and rate, read amplification, codec/resolution ladder, geographic spread,
DRM, live vs on-demand?
**Shape:** direct-to-object-storage uploads (pre-signed, multipart, resumable); async
transcoding DAG; CDN with origin shield; metadata in a DB.
**Traps:** proxying uploads through app servers; cache keys that include tracking parameters;
egress cost left out of the estimate.

## Geospatial and location
**Dominated by:** proximity queries, update rate of moving objects, and hot cells (stadiums,
city centres).
**Force:** Static (places) or moving (drivers) objects? Update frequency? Query radius and
result count? Accuracy needs?
**Shape:** geohash/S2/H3 cells or quadtrees; moving objects in memory (sharded by cell) with
periodic persistence; static places in a DB with a spatial index.
**Traps:** writing every GPS ping to a durable DB; fixed cell sizes that overload dense areas.

## Data-intensive and analytics
**Dominated by:** ingest throughput, late and out-of-order data, storage format and partitioning,
and the batch vs stream boundary.
**Force:** Event volume and size? Freshness needed (seconds, minutes, daily)? Query patterns
(dashboards, ad-hoc, ML features)? Exactly-once counts needed (billing) or approximate OK?
Retention and backfill needs?
**Shape:** log (Kafka-style) as the ingest buffer; stream processing for fresh aggregates with
watermarks; columnar storage (Parquet/lakehouse, or an OLAP store) partitioned by time;
batch reprocessing from the log for corrections.
**Traps:** OLTP database used for analytics scans; no plan for late data or reprocessing;
high-cardinality partition keys creating millions of tiny files.

## Platform, infrastructure and internal tooling
**Dominated by:** blast radius, multi-tenancy across internal teams, API stability, and the
control plane vs data plane split.
**Force:** Who are the users (teams, services)? What happens to the data plane if the control
plane is down? Change rate and rollout safety? Quotas?
**Shape:** a control plane that can be down without breaking the data plane (cached config,
static stability); cells; versioned, declarative APIs.
**Traps:** data-plane requests that call the control plane synchronously; global config pushes
with no staged rollout.

## Mobile apps and offline-first clients
**Dominated by:** unreliable networks, battery and data budgets, local persistence and sync,
and old app versions that never update. Details: `clients-mobile-embedded.md`.
**Force:** Must it work offline, and which features? Conflict policy when two devices edit?
Oldest app version still supported? Push notifications? Payload budgets on cellular?
**Traps:** server APIs that assume the newest client; sync that sends whole objects; no plan
for a forced upgrade.

## Embedded and IoT
**Dominated by:** constrained memory/CPU/power, intermittent links, device fleets of millions,
and safe firmware updates. Details: `clients-mobile-embedded.md`.
**Force:** Device class and resources? Connectivity (cellular, LoRa, BLE via gateway)? Message
rate per device and fleet size? Command-and-control latency? OTA update policy and rollback?
Device identity and provisioning?
**Traps:** a broker sized for average rather than the reconnect storm after an outage; OTA
without A/B partitions and staged rollout; shared credentials across a fleet.

## AI, ML and GenAI systems
**Dominated by:** model quality and evaluation, inference latency and cost per request, data
freshness, and safety. Details: `ai-ml-systems.md`.
**Force:** What is predicted or generated, and how is "good" measured offline and online?
Latency budget (time to first token)? Cost ceiling per request? Data sensitivity and
permissions? Human in the loop?
**Traps:** no evaluation set; RAG without permission filtering; one large model for every
request when routing would do; no plan for model or index upgrades.
