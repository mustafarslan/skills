# Security, data lifecycle, delivery and cost

## Contents
- [Identity and access](#identity-and-access)
- [Service-to-service trust](#service-to-service-trust)
- [Data protection](#data-protection)
- [Multi-tenant isolation](#multi-tenant-isolation)
- [Data lifecycle and compliance](#data-lifecycle-and-compliance)
- [Edge protection](#edge-protection)
- [Threat modelling in a design](#threat-modelling-in-a-design)
- [Delivery: CI/CD and rollouts](#delivery-cicd-and-rollouts)
- [Infrastructure as code and environments](#infrastructure-as-code-and-environments)
- [Cost](#cost)

## Identity and access
- Users: OIDC/OAuth 2.0 with an identity provider; passkeys (WebAuthn) for phishing resistance;
  SSO (SAML/OIDC) and SCIM provisioning for B2B.
- Tokens: short-lived access tokens (minutes) + rotating refresh tokens; revocation strategy
  (short TTL, or a denylist checked at the gateway).
- Authorization models: RBAC (roles), ABAC (attributes and policies), ReBAC (relationships, e.g.
  Zanzibar-style for "editor of this folder"). Enforce in the service that owns the data, not only
  at the gateway.

## Service-to-service trust
- Zero trust: authenticate every call. mTLS with workload identity (SPIFFE-style, or the cloud's
  IAM), often via a service mesh.
- Least privilege per service: its own DB credentials and IAM role.

## Data protection
- In transit: TLS everywhere, including internal.
- At rest: storage encryption by default; **envelope encryption** with a KMS/HSM for sensitive
  fields; per-tenant keys when customers require them (and the key-rotation story).
- Encoding ≠ encryption ≠ hashing ≠ tokenization: tokenize card numbers (vault service) to keep
  most systems out of PCI scope; hash passwords with a slow KDF (Argon2, bcrypt).
- Secrets in a secrets manager, never in code, images or env files in repos; rotate.

## Multi-tenant isolation
- Pooled: `tenant_id` in every table, index, cache key, log line and queue message; row-level
  security or a mandatory query filter; tests that try cross-tenant access.
- Noisy neighbours: per-tenant rate limits, quotas, fair queueing, and the option to move a large
  tenant to its own cell.
- Per-tenant encryption keys enable crypto-shredding on offboarding.

## Data lifecycle and compliance
- Classify data (public, internal, confidential, PII, payment, health).
- Retention per class; automatic expiry (TTLs, partition drops).
- **Deletion is a design problem**: a "delete my data" request must reach the primary DB,
  replicas, caches, search indexes, vector indexes, analytics copies, logs, event streams and
  backups. Immutable logs and backups need **crypto-shredding** (delete the per-user/tenant key)
  or expiry within a stated window.
- Residency: keep data (and its backups and logs) in the required region; watch cross-region
  replication and third-party processors.
- Audit logs: append-only, tamper-evident, retained per regulation.
- Name the regimes that apply (GDPR, HIPAA, PCI DSS, SOC 2) and what each forces in the design.

## Edge protection
- WAF for common attacks; DDoS absorption at the CDN/edge; bot management where abuse matters.
- Rate limits per identity (network-edge-api.md).
- Input validation at the edge and in the service; output encoding.

## Threat modelling in a design
For each trust boundary in the diagram (internet → edge, edge → service, service → DB, service →
third party): what crosses it, who can reach it, and what stops abuse (STRIDE: spoofing,
tampering, repudiation, information disclosure, denial of service, elevation of privilege). Put
the top 3 threats and their controls in the doc.

## Delivery: CI/CD and rollouts
- Every change through the pipeline: build once, promote the same artifact.
- Progressive delivery: canary (1% → 10% → 100%, with automatic rollback on SLO burn),
  blue/green (instant switch back), feature flags to separate deploy from release.
- Database changes: expand/contract, backward compatible with the previous app version (both
  run during a rollout); never couple a destructive migration to a deploy.
- Rollback plan for each change type (code, config, schema, data).
- Mobile and firmware cannot be rolled back on devices: server-side flags and compatibility
  windows instead (clients-mobile-embedded.md).

## Infrastructure as code and environments
- Terraform/OpenTofu/Pulumi with state split by blast radius; Kubernetes (Helm, operators) or
  managed platforms - choose by team skills.
- Environments: dev, staging that mirrors production topology, production; ephemeral preview
  environments where cheap.
- Config changes are deploys: staged, reviewed, reversible.

## Cost
- Estimate the big lines at today's and 10x scale: compute, storage (with replication and
  retention), egress, managed-service per-request fees, GPU/inference, observability (logs and
  metrics are often a top-5 line).
- Unit cost: per request, per active user, per tenant - and compare with revenue per unit.
- Levers: caching and CDN, right-sizing and autoscaling, spot/preemptible for batch, storage
  tiering (hot → warm → cold/archive), data retention, sampling telemetry, model routing for AI.
- Managed services trade money for team time; with a small team that is usually the right trade.
- AWS Well-Architected's six pillars (operational excellence, security, reliability, performance
  efficiency, cost optimization, sustainability) make a good final checklist.
