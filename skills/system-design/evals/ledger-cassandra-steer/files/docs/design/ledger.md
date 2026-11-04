# Wallet ledger - design
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
