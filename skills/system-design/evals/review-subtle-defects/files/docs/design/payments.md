# Payments and orders - design
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
