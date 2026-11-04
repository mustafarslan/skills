# Architecture

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
