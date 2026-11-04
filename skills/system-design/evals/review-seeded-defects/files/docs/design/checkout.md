# Checkout - design
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
