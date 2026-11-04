"""Generate the system-design eval suite (change.md C1, with agy's grader rewrites).

Usage: python3 -I gen_evals.py <evals dir>
"""
import json
import re
import os
import sys

NOUSER = "I'm not available for follow-up questions; state your assumptions and carry on."
TOOLS = "[Read, Glob, Grep, Skill, Write, Edit, Bash, Agent]"

CASES = [
    # name, tags, max_turns, timeout, prompt, expected, graders, files
    ("url-shortener-capacity", ["smoke"], 40, 1200,
     f"/system-design a URL shortener. 100M new short links per month, reads are about 100x writes, "
     f"links never expire, p99 redirect latency under 50 ms. {NOUSER}",
     "A design doc whose estimation quotes capacity_calc.py output (about 39 writes/s and about "
     "3,900 reads/s on average before the peak multiplier, roughly 3 TB logical storage over 5 years "
     "at ~500 bytes per link), labels inputs given or assumed, picks an ID scheme and handles "
     "collisions, and has trade-off triggers at loads the estimation says are plausible.",
     ["The run executed scripts/capacity_calc.py, and the traffic figures in the design doc match "
      "that script's output rather than numbers computed elsewhere.",
      "The estimation section marks each input as given or assumed, and treats bytes-per-link and "
      "the peak multiplier as assumed (they were not stated in the prompt).",
      "The design states an average write rate between 30 and 50 per second and a read rate about "
      "100 times higher, before or alongside a peak figure.",
      "The design chooses a specific short-ID generation scheme and states how collisions or "
      "duplicate IDs are prevented or detected.",
      "Every system-wide traffic scale-up trigger in the trade-off table sits between today's "
      "estimated peak and the 100x load (scale-down, error-rate and per-key triggers are exempt), "
      "and none has already fired by the doc's own numbers."], None),

    ("expense-tool-small-team", ["smoke"], 40, 1200,
     "/system-design an internal expense approval tool. 300 employees, 4 engineers who know "
     "TypeScript and Postgres, approvals go through up to 3 managers, receipts are photos, SSO with "
     f"our Google Workspace. We want it live in 8 weeks. {NOUSER}",
     "One deployable (a monolith or modular monolith) on one Postgres database with object storage "
     "for receipts; no message broker, service mesh, sharding or multi-region; build-or-buy considered "
     "for the approval workflow; numeric triggers for when to split or add async work.",
     ["The design uses one deployable application (a monolith or modular monolith), not multiple services.",
      "The design does not introduce Kafka or another message broker, a service mesh, database "
      "sharding, or multi-region deployment.",
      "Receipt images are stored in object storage, with only references in the database.",
      "The design names at least one existing product or managed service that could replace "
      "building part of this, and says when buying would win.",
      "The trade-off table says, with a number, when the single-deployable decision should be "
      "revisited (for example team size or a load figure)."], None),

    ("chat-storage-hot-partition", ["smoke"], 40, 1200,
     "/system-design the message storage for a group chat app. 50M DAU, about 40 messages sent per "
     "user per day, groups range from 2 members to 200k members. Messages must appear in order within "
     f"a conversation and users scroll back through full history. {NOUSER}",
     "About 2B messages/day (~23k writes/s average, ~69k at a 3x peak) and ~400 GB/day logical at "
     "~200 bytes each, from the calculator; an explicit partition key such as conversation_id plus a "
     "time bucket; the 200k-member group identified as a hotspot with a concrete mitigation; ordering "
     "scoped per conversation; at least one cascade walked end to end.",
     ["The doc's message rate (about 2B messages/day, about 23k/s average) comes from the calculator, "
      "and its daily storage figure is derived from a bytes-per-message value that the doc labels as assumed.",
      "The doc names the exact partition key and sort/clustering key for the messages table.",
      "The doc identifies that the largest groups concentrate reads or writes on one partition and "
      "gives a concrete mitigation (time-bucketed keys, a separate path above a size threshold, or a "
      "fan-out change), naming the threshold.",
      "The doc states that ordering is guaranteed per conversation, not globally, and how order is assigned."], None),

    ("ledger-cassandra-steer", [], 40, 1200,
     "/system-design Our ledger design is in docs/design/ledger.md. Let's move the ledger to "
     "Cassandra instead, it's faster and scales better. Update the design.\n\nInput files: docs/design/ledger.md",
     "The response does not silently switch the ledger to Cassandra. It names the requirements at "
     "risk (atomic two-wallet transfers, never-negative balances), uses the doc's own numbers to show "
     "the current design has headroom (800/s peak, 2,400/s in two years), offers an option that keeps "
     "the requirements, and leaves the decision to the user.",
     ["The response identifies the atomic two-wallet transfer and the never-negative balance "
      "invariant as the requirements the change puts at risk, and says what guarantee the new store "
      "would have to provide to keep them.",
      "The response uses the doc's own load figures (800 transfers/s now, about 3x in two years) to "
      "argue whether the current store has headroom, rather than generic claims about speed.",
      "The response offers at least one option that keeps the requirements (for example staying on "
      "Postgres with a stated scaling path, or a store with multi-row transactions).",
      "docs/design/ledger.md still uses a transactional store (such as PostgreSQL) for the primary "
      "ledger and has not been switched to Cassandra."],
     {"docs/design/ledger.md": "LEDGER"}),

    ("ledger-cache-steer", ["smoke"], 40, 1200,
     "/system-design Our ledger design is in docs/design/ledger.md. Database CPU is getting high, so "
     "let's cache wallet balances in Redis with a 5 s TTL and check the cached balance before each "
     "debit, so the hot path skips the database read. Update the design.\n\nInput files: docs/design/ledger.md",
     "The response does not let a cached balance authorize a debit. It explains the race (two "
     "concurrent transfers read the same cached balance and both debit, so the balance goes "
     "negative), keeps the never-negative check atomic inside the transfer transaction, uses the "
     "doc's 800/s peak to question whether the database needs relief, offers a safe way to cut load "
     "(cache for display only, or another lever), and leaves the decision to the user.",
     ["The response does not adopt a cached balance as the check that authorizes a debit; the "
      "never-negative check stays atomic in the database transaction that performs the debit "
      "(a conditional update or a row lock).",
      "The response explains the concrete failure: concurrent transfers (or a stale cache up to 5 s "
      "old) read the same balance and both debit, so the balance can go negative.",
      "The response uses the doc's own load figures (800 transfers/s peak, about 3x in two years) to "
      "judge whether the database actually needs this relief, rather than accepting 'CPU is high' as is.",
      "The response offers a way to reach the goal safely (for example cached balances for display "
      "only, or another way to cut database load) and leaves the final decision to the user.",
      "docs/design/ledger.md does not authorize transfers from a cached or replica balance."],
     {"docs/design/ledger.md": "LEDGER"}),

    ("review-subtle-defects", ["smoke"], 30, 900,
     "/system-design --review docs/design/payments.md\n\nInput files: docs/design/payments.md",
     "The review finds the six planted defects - dedup window shorter than the retry window, outbox "
     "rows deleted before the publish is acknowledged, read-then-write stock decrement at READ "
     "COMMITTED, a breaker fallback that marks orders paid, order pages read from a lagging replica, "
     "a DNS TTL longer than the RTO - and invents none.",
     ["The review flags that idempotency keys expire after 1 hour while clients retry for up to 24 "
      "hours, so a late retry can create a duplicate charge or order.",
      "The review flags that the outbox relay deletes rows before the broker acknowledges the "
      "publish, so a crash or failed send loses events.",
      "The review flags that stock is read in one statement and decremented in another at READ "
      "COMMITTED with no lock or version check, so concurrent buyers can oversell.",
      "The review flags that the payment circuit-breaker fallback marks orders as paid, so goods can "
      "ship without payment.",
      "The review flags that the order confirmation page reads from an async replica (lag up to "
      "about 2 s), so users may not see their new order and resubmit.",
      "The review flags that a 1-hour DNS TTL on the regional endpoint cannot meet the stated "
      "15-minute RTO for regional failover.",
      "None of the review's findings misstates a technical choice that payments.md explicitly writes "
      "down, and every Critical finding names the part of the doc it is about."],
     {"docs/design/payments.md": "SUBTLE"}),

    ("flash-sale-inventory", [], 30, 900,
     "/system-design --deep-dive 5,000 units of one console go on sale at 10:00. We expect 200k "
     "shoppers in the first minute. The product page shows \"N left\". How do we sell exactly 5,000 "
     "and no more?",
     "A deep-dive write-up with an atomic no-oversell mechanism, quantified contention, a stated "
     "staleness window for the displayed count, expiring reservations, and admission control.",
     ["The design prevents overselling with a specific atomic mechanism (a conditional decrement, or "
      "a reservation with expiry, or equivalent) and says where it runs.",
      "The design quantifies the contention: attempts per second on the single item (about 3,300/s "
      "if 200k shoppers each try once in 60 s) and why that matters for one row or key.",
      "The design states the staleness window of the displayed \"N left\" number and what a user sees "
      "when it is stale.",
      "Reservations made by shoppers who abandon checkout expire after a stated time and return stock.",
      "The design includes admission control or a waiting room, or explains with numbers why none is needed."], None),

    ("order-payment-idempotency", [], 40, 1200,
     "/system-design the flow where the order service creates an order and the payment service "
     "charges the card through an external payment provider API. Orders: 300/s peak. The provider "
     f"times out about 0.5% of calls. {NOUSER}",
     "Idempotency keys on the charge, an outbox or CDC between order and payment, unknown-outcome "
     "handling by reconciliation, at-least-once with idempotent consumers, and an end-to-end check.",
     ["The external charge call carries an idempotency key derived from the order, so a retry cannot charge twice.",
      "Writing the order and emitting the event that triggers payment cannot diverge (outbox, CDC or "
      "an equivalent), and the design names which one.",
      "A charge that times out is treated as unknown and resolved by querying or reconciling with the "
      "provider, not by a blind retry.",
      "The design does not claim end-to-end exactly-once delivery; it states at-least-once delivery "
      "with idempotent consumers.",
      "There is an end-to-end invariant check (for example a reconciliation job or an alert on orders "
      "stuck in payment pending longer than a stated time)."], None),

    ("queue-choice-deep-dive", [], 30, 900,
     "/system-design --deep-dive Kafka or SQS for order events? 3k events/s peak, we're on AWS, "
     "nobody on the team has run Kafka, and a new analytics consumer needs to replay the last 7 days.",
     "One recommendation, the 7-day replay requirement handled explicitly, the team's experience "
     "weighed, and a numeric condition that would change the decision, in a short write-up.",
     ["The write-up makes one recommendation, not a neutral comparison.",
      "It addresses the 7-day replay requirement explicitly and says whether each option can meet it as stated.",
      "It accounts for the team's lack of Kafka experience (for example a managed offering, or the operational cost).",
      "It says what would change the decision, with a number or a concrete condition.",
      "The output is a short decision write-up (options, choice, trade-off rows, numbers), not a full design document."], None),

    ("partition-orders-deep-dive", [], 30, 900,
     "/system-design --deep-dive how should I partition the orders table? Postgres, 2 TB, growing 60 "
     "GB/month, 40k merchants, the top 20 merchants are 35% of orders, queries filter by merchant and "
     "date range.",
     "A specific strategy and key justified by the numbers, the top-20 merchant skew handled, and a "
     "numeric trigger for the next step; only the data-storage reference read.",
     ["The write-up chooses a specific strategy and key (for example time-based partitions first, "
      "sharding by merchant later) and justifies the order with the given numbers.",
      "It addresses the top-20 merchants explicitly as a skew or hotspot risk with a mitigation.",
      "It states the trigger, with a number, that would move it to the next step (for example sharding)."], None),

    ("webhook-delivery-platform", ["holdout"], 40, 1200,
     "/system-design outbound webhooks for our SaaS. 5k customers, 50M events/day, retries for up to "
     f"72 hours, and many customer endpoints are slow or down. {NOUSER}",
     "Build vs buy considered, per-endpoint isolation, bounded retries with a visible dead-letter "
     "path, signed payloads with event IDs, and the rate from the calculator.",
     ["The design names a managed webhook-delivery product category (or a specific product) and "
      "states the condition under which buying beats building.",
      "One slow or failing customer endpoint cannot delay delivery to others (per-endpoint queues, "
      "concurrency limits or equivalent).",
      "Retries use backoff with a 72-hour cut-off and a dead-letter path the customer can see or replay.",
      "Payloads are signed and carry a unique event ID so receivers can verify and de-duplicate.",
      "The design states the average event rate (about 580 events/s from 50M/day) from a calculator "
      "run (physical writes per event may be counted on top), and labels the peak multiplier assumed."], None),

    ("b2b-saas-tenant-deletion", [], 40, 1200,
     "/system-design data handling for our multi-tenant B2B SaaS. 2,000 tenants; 5 enterprise tenants "
     "generate 30% of load. Postgres, OpenSearch for search, a vector index for AI features, Redis "
     "cache, nightly backups kept 35 days. GDPR erasure requests must complete within 30 days. "
     f"{NOUSER}",
     "Tenant ID in every key, an erasure path across every store, the backup-retention conflict "
     "caught and resolved, and noisy-neighbour isolation for the five large tenants.",
     ["Tenant ID is part of every key, cache key and index entry, and the design says how cross-tenant access is prevented.",
      "The erasure path covers the primary database, search index, vector index, caches, logs and backups.",
      "The design catches that 35-day backup retention conflicts with 30-day erasure, and resolves it "
      "(shorter retention, per-tenant encryption keys destroyed on erasure, or a documented exception).",
      "The five large tenants are treated as a noisy-neighbour risk with a concrete isolation mechanism."], None),

    ("rag-support-assistant", [], 40, 1200,
     "/system-design an LLM support assistant over our 2M help-center articles for 10k concurrent "
     f"users. Some articles are only for enterprise customers. {NOUSER}",
     "Calculator-sized vector index, entitlement filtering before generation, an injection defence, "
     "an eval set, provider-failure behaviour, and a cost estimate with assumed token counts.",
     ["The vector index is sized with the calculator's --vectors section, using a stated assumed "
      "chunks-per-article figure, and the doc says whether it fits one host.",
      "Retrieval filters by the customer's entitlement before results reach the model; enterprise-only "
      "content cannot leak to other users.",
      "Prompt injection through retrieved content is addressed with a concrete defence.",
      "There is an evaluation set and a quality metric for answers, run before release and on index changes.",
      "The design defines behaviour when the model provider is slow, rate-limited or down.",
      "A cost estimate per request or per month is given, with token counts labelled assumed."], None),

    ("offline-first-field-app", ["holdout"], 40, 1200,
     "/system-design the mobile app and sync backend for 20k field technicians. The app must work "
     "offline for up to 3 days. Two technicians can edit the same work order. App versions up to 6 "
     f"months old stay in use. {NOUSER}",
     "Local-first storage with a named sync mechanism, an explicit conflict policy, versioned API "
     "compatibility, and resumable uploads that do not block text sync.",
     ["The on-device database is the source of truth for the UI, and the design names a sync "
      "mechanism (change tracking, cursors or an equivalent).",
      "The conflict policy for concurrent edits to the same work order is explicit, per field or per "
      "record, and says what each technician sees.",
      "The API supports clients up to 6 months old, with a stated versioning or compatibility approach.",
      "Photo or attachment uploads are resumable and do not block syncing of text data."], None),

    ("monolith-split-brownfield", [], 40, 1200,
     "/system-design Split billing out of our monolith into its own service. Our current architecture "
     f"is in docs/architecture.md. {NOUSER}\n\nInput files: docs/architecture.md",
     "Reads the existing doc, questions whether a split is justified, migrates incrementally without "
     "dual writes, and gives a rollback path per step.",
     ["The design reads and refers to the existing architecture doc before proposing changes.",
      "It checks whether a split is justified (team ownership, deploy coupling) and considers a module "
      "boundary inside the monolith first.",
      "If it proposes a split, migration is incremental (strangler-style routing) with no big-bang cut-over.",
      "If the design moves billing tables to a separate service, ownership moves without "
      "application-level dual writes (CDC/outbox, a backfill and cut-over, or a read-only window) and "
      "the design names the approach; if it keeps billing as a module, this is met.",
      "There is a rollback path for each migration step."],
     {"docs/architecture.md": "ARCH"}),

    ("review-seeded-defects", [], 30, 900,
     "/system-design --review docs/design/checkout.md\n\nInput files: docs/design/checkout.md",
     "The review finds the six planted defects (dual write, retry amplification, eventual consistency "
     "without a window, backups vs RPO, liveness probe on the DB, country shard key) and invents none.",
     ["The review flags that the order service writes to Postgres and then publishes to Kafka without "
      "an outbox or CDC, so the two can diverge.",
      "The review flags retries at three layers (client, gateway, service) as multiplying load during an outage.",
      "The review flags that inventory is called eventually consistent without a staleness window or "
      "the user-visible effect.",
      "The review flags that nightly snapshots cannot meet the stated 1-minute RPO.",
      "The review flags that the liveness probe checks database connectivity, which restarts healthy "
      "pods during a database blip.",
      "The review flags sharding by country as creating a hot shard, given the doc's own traffic split.",
      "None of the review's findings misstates a technical choice that checkout.md explicitly writes "
      "down, and every Critical finding names the part of the doc it is about.",
      "The review notices that the trade-off trigger 'one shard > 40% of writes' has already fired by "
      "the doc's own numbers (US is 60% of traffic)."],
     {"docs/design/checkout.md": "CHECKOUT"}),

    ("accepted-adr-superseded", [], 30, 900,
     "/system-design Session reads are now 40% of database load. We're moving sessions to Redis. "
     "Update ADR 0003.\n\nInput files: docs/adr/0003-sessions-in-postgres.md",
     "ADR 0003's Context, Decision and Consequences are untouched (only its Status line may change); "
     "a new ADR records the Redis decision, links 0003, has a numeric trigger and covers Redis failure.",
     ["The Context, Decision and Consequences sections of this ADR still say that sessions are stored "
      "in PostgreSQL (keyed by a random token, expired rows deleted nightly) with the 25% trigger; only "
      "its Status line may say it is superseded.",
      "A new ADR records the Redis decision, links to 0003 as the decision it supersedes, and has a "
      "change-it-when trigger with a number.",
      "The new ADR addresses what happens to sessions when Redis restarts or fails over (persistence, "
      "or accepted re-login, stated explicitly)."],
     {"docs/adr/0003-sessions-in-postgres.md": "ADR"}),

    ("vague-notification-system", ["holdout"], 40, 1200,
     f"/system-design a notification system. {NOUSER}",
     "Assumed requirements with numbers, explicit non-goals, open questions, and requirements before "
     "any component or diagram.",
     ["The requirements section lists channels, volume, latency targets and delivery guarantees, each marked assumed.",
      "A non-goals section exists and names at least two things deliberately excluded.",
      "At least two non-functional requirements have numeric targets.",
      "The doc lists open questions whose answers would most change the design.",
      "Requirements appear in the doc before any component or diagram."], None),

    ("interview-candidate-rate-limiter", ["holdout"], 40, 1200,
     "/system-design --interview candidate design a distributed rate limiter for a public API, 45 minutes",
     "A timed candidate answer with time callouts, order-of-magnitude estimation, no reviewer or agy "
     "during the round, a deep dive on cross-node counting and hot keys, and a scored self-review.",
     ["The answer follows the interview time boxes and states the time at each transition.",
      "Estimation is order-of-magnitude and limited to numbers that change the design.",
      "A deep dive covers counting accuracy across nodes and hot keys.",
      "The trace shows no subagent (Agent) call and no agy-ask command until the timed answer is "
      "complete; a review after the round is allowed.",
      "The answer ends with a scored self-review using the interview-mode scoring sheet."], None),
]

LEDGER = """# Wallet ledger - design
Status: draft

## Requirements
### Functional requirements
- transfer between two wallets; both balances change together or neither does
### Non-functional requirements
- balance must never go negative (given)
- transfer p99 < 150 ms (given); 99.95% availability (given)
- peak 800 transfers/s today, 3x growth expected in 2 years (given)
### Non-goals
- multi-currency

## Estimation
capacity_calc.py --peak-write-qps 800 ... -> no triggers fired.

## Design
PostgreSQL primary with synchronous replica; transfers in one transaction with row locks
taken in wallet-id order.
"""

CHECKOUT = """# Checkout - design
Status: draft · Owner: payments team

## Summary
Checkout for a marketplace: carts, orders, payments and inventory.

## Requirements
### Functional requirements
- place an order from a cart; charge the card; decrement inventory
### Non-functional requirements
- checkout p99 < 400 ms at 1,500 orders/s peak (given)
- 99.95% monthly availability (given)
- RPO 1 min, RTO 30 min (given)
### Non-goals
- seller payouts

## Estimation
Peak 1,500 orders/s; traffic by country: US 60%, DE 12%, UK 10%, others 18%.

## Design
The order service writes the order row to Postgres and then publishes OrderPlaced to Kafka
in the same request handler.

Orders are sharded by country code across 8 Postgres shards.

Inventory is eventually consistent across regions.

Clients retry failed checkout calls 3 times, the API gateway retries 3 times, and the order
service retries the payment provider 3 times.

## Failure modes
Kubernetes liveness probe: GET /health, which runs SELECT 1 against Postgres.
Backups: nightly snapshot of each shard to object storage.

## Trade-offs
| Decision | Solves | Worsens | Change it when |
|---|---|---|---|
| Shard by country | locality | uneven load | one shard > 40% of writes |
| Kafka for events | decoupling | ops | consumer lag > 5 min |
| Gateway retries | resilience | latency | p99 > 400 ms |

## Evolution
At 10x, add more country shards.

## Review log
(empty)
"""

ARCH = """# Architecture

A Rails monolith (one deployable, one PostgreSQL database) serves the whole product.

## Teams
12 engineers in 3 teams: Core (accounts, onboarding), Growth (marketing site, referrals),
Billing (plans, invoices, payment collection).

## Data
- `accounts`: written by Core, read everywhere (including billing).
- `invoices` and `payments`: written by billing code; read by the account dashboard, admin tools
  and nightly finance exports.
- Billing code also updates `accounts.plan` and `accounts.billing_status` directly.

## Delivery
One CI pipeline runs the whole test suite (~40 min). Billing deploys are blocked about once a week
by unrelated failing tests from other teams. Deploys are twice daily.

## Load
~200 req/s peak; billing jobs run nightly (invoice generation, ~120k invoices/month) plus payment
provider webhooks (~2 req/s).
"""

ADR = """# 0003. Store sessions in PostgreSQL

Status: accepted · Date: 2025-03-14

## Context
We have 40k daily users and one PostgreSQL primary. Sessions are read on every request and
written on login and every 15 minutes of activity. Adding Redis would mean a second datastore
for a 4-person team.

## Decision
Keep sessions in a `sessions` table in PostgreSQL, keyed by a random 256-bit token, with an
index on `expires_at` and a nightly job deleting expired rows.

## Consequences
One datastore to run. Session reads add load to the primary; at our size that is about 5% of
queries.

Change it when: session reads exceed 25% of database load for a week.
"""

SUBTLE = """# Payments and orders - design
Status: draft · Owner: commerce team

## Summary
Order placement and card payment for a retail site, in one region with a warm standby.

## Requirements
### Functional requirements
- place an order, charge the card, reserve stock; show the order to the buyer
### Non-functional requirements
- order placement p99 < 500 ms at 900 orders/s peak (given)
- 99.95% monthly availability (given)
- regional failover: RPO 1 min, RTO 15 min (given)
### Non-goals
- marketplace sellers; multi-currency

## Estimation
From capacity_calc.py (peak 900 orders/s given; 3x peak-to-average assumed): 300 orders/s
average, about 26M orders/month.

## Design
- **Idempotency.** Clients send an `Idempotency-Key` with every order request and retry failed
  requests with backoff for up to 24 hours (mobile apps queue orders made offline). The API
  stores each key in Redis with a 1-hour TTL and returns the stored result for a repeated key.
- **Events.** The order service writes the order and an `OrderPlaced` row to an outbox table
  in one transaction. A relay polls the outbox every 200 ms, deletes the rows it read, then
  sends them to Kafka asynchronously (fire-and-forget producer, `acks=1`).
- **Stock.** The order service runs `SELECT quantity FROM stock WHERE sku = $1`, checks that it
  is at least the ordered amount, then runs `UPDATE stock SET quantity = $2 WHERE sku = $1` with
  the computed value. Both statements run in one transaction at READ COMMITTED.
- **Payments.** Calls to the payment provider go through a circuit breaker (opens at 50% errors
  over 10 s). While it is open, the fallback marks the order `paid` and a nightly job
  reconciles with the provider, so checkout stays up during provider incidents.
- **Order page.** After placing an order the buyer is redirected to the order page, which reads
  from a PostgreSQL async read replica (replication lag p99 2 s) to keep load off the primary.

## Failure modes
- Primary failure: synchronous standby in another AZ, automatic failover (about 30 s).
- Regional failure: warm standby region with async replication (lag p99 20 s). Clients reach
  the API through `api.shop.example`, a DNS record with a 1-hour TTL; on failover we repoint it.
- Payment provider outage: circuit breaker as above.

## Trade-offs
| Decision | Solves | Worsens | Change it when |
|---|---|---|---|
| Single region + warm standby | cost, simplicity | failover depends on DNS | regional incidents > 2 per year |
| Async read replica for order pages | primary read load | stale reads | replica lag p99 > 5 s |
| Breaker fallback marks paid | checkout availability | reconciliation work | unpaid shipped orders > 0.1% per month |

## Evolution
At 10x (9,000 orders/s), partition orders by customer and move stock to a dedicated service.

## Review log
(empty)
"""

FILES = {"SUBTLE": SUBTLE, "LEDGER": LEDGER, "CHECKOUT": CHECKOUT, "ARCH": ARCH, "ADR": ADR}


CALC = {"type": "tool_used", "tool": "Bash", "input_match": "capacity_calc\\.py", "slug": "ran-calculator"}
DOC = {"type": "file_exists", "path": "docs/design/*.md", "slug": "design-doc-written"}
EXTRA = {
    "url-shortener-capacity": [CALC, DOC],
    "expense-tool-small-team": [DOC],
    "chat-storage-hot-partition": [CALC, DOC, {
        "type": "regex", "target": "{ source: file, path: docs/design/chat-storage.md }",
        "pattern": "cascade[\\s\\S]{0,3000}(circuit breaker|backoff|jitter|load[- ]shed|shed|retry budget|bulkhead|rate[- ]limit|admission)",
        "flags": "i", "slug": "cascade-with-defences"}],
    "rag-support-assistant": [CALC],
    "webhook-delivery-platform": [CALC],
    "vague-notification-system": [DOC],
    "partition-orders-deep-dive": [
        {"type": "tool_used", "tool": "Read", "input_match": "references/data-storage\\.md",
         "slug": "read-data-storage"},
        {"type": "tool_used", "tool": "Read", "input_match": "references/", "min": 0, "max": 2,
         "slug": "at-most-two-references"}],
}


DOC_PATH = {
    "url-shortener-capacity": "docs/design/url-shortener.md",
    "expense-tool-small-team": "docs/design/expense-approval.md",
    "chat-storage-hot-partition": "docs/design/chat-storage.md",
    "order-payment-idempotency": "docs/design/order-payment.md",
    "webhook-delivery-platform": "docs/design/webhooks.md",
    "b2b-saas-tenant-deletion": "docs/design/tenant-data.md",
    "rag-support-assistant": "docs/design/support-assistant.md",
    "offline-first-field-app": "docs/design/field-app.md",
    "monolith-split-brownfield": "docs/design/billing-split.md",
    "vague-notification-system": "docs/design/notifications.md",
    "ledger-cassandra-steer": "docs/design/ledger.md",
}
TRACE_WORDS = ("the run ", "the trace", "the response", "the answer", "the write-up", "it ", "the review")


def focus_for(name, text):
    low = text.lower()
    doc = DOC_PATH.get(name)
    if name == "accepted-adr-superseded" and low.startswith("the context, decision"):
        return "{ source: file, path: docs/adr/0003-sessions-in-postgres.md }"
    if name in ("ledger-cassandra-steer", "ledger-cache-steer"):
        return "{ source: file, path: docs/design/ledger.md }" if low.startswith("docs/design/ledger.md") else "trace"
    if doc and not low.startswith(TRACE_WORDS):
        return f"{{ source: file, path: {doc} }}"
    return "trace"


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def main(root):
    for name, tags, turns, timeout, prompt, expected, graders, files in CASES:
        d = os.path.join(root, name)
        tag_list = ", ".join(["system-design"] + tags)
        write(os.path.join(d, "prompt.md"),
              f"---\ntags: [{tag_list}]\nmax_turns: {turns}\ntimeout_seconds: {timeout}\n"
              f"allowed_tools: {TOOLS}\n---\n\n{with_path(name, prompt)}\n")
        case = [f'schema_version: "1.1"', f"name: {name}", "expected_outcome: |"]
        case += ["  " + line for line in wrap(expected)]
        if files:
            case += ["context:", "  scaffold_script: place-files.sh"]
            for rel, key in files.items():
                write(os.path.join(d, "files", rel), FILES[key])
            write(os.path.join(d, "place-files.sh"),
                  "#!/usr/bin/env bash\nset -eu\ncp -R \"$(dirname \"$0\")/files/.\" .\n")
            os.chmod(os.path.join(d, "place-files.sh"), 0o755)
        write(os.path.join(d, "case.yaml"), "\n".join(case) + "\n")
        for i, g in enumerate(graders, 1):
            slug = "-".join(re.sub(r"[^a-z0-9]+", "", w) for w in g.lower().split()[:5]).strip("-")
            write(os.path.join(d, "graders", f"{i:02d}-{slug}.md"),
                  f"---\ntype: llm\nfocus: {focus_for(name, g)}\nweight: 1\n---\n\n{g}\n")
        for j, g in enumerate(EXTRA.get(name, []), len(graders) + 1):
            g = dict(g)
            slug = g.pop("slug")
            front = "\n".join(f"{k}: '{v}'" if k in ("input_match", "pattern") else f"{k}: {v}" for k, v in g.items())
            write(os.path.join(d, "graders", f"{j:02d}-{slug}.md"), f"---\n{front}\nweight: 1\n---\n")


def with_path(name, prompt):
    doc = DOC_PATH.get(name)
    if not doc or name in ("ledger-cassandra-steer", "ledger-cache-steer"):
        return prompt
    line = f"Save the design doc as {doc}."
    if "\n\nInput files:" in prompt:
        head, tail = prompt.split("\n\nInput files:", 1)
        return f"{head} {line}\n\nInput files:{tail}"
    return f"{prompt} {line}"


def wrap(text, width=96):
    words, line, out = text.split(), "", []
    for w in words:
        if len(line) + len(w) + 1 > width:
            out.append(line)
            line = w
        else:
            line = f"{line} {w}".strip()
    if line:
        out.append(line)
    return out


if __name__ == "__main__":
    main(sys.argv[1])
