# 0003. Store sessions in PostgreSQL

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
