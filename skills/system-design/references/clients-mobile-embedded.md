# Mobile, offline-first and embedded clients

## Contents
- [What changes when the client is a device](#what-changes-when-the-client-is-a-device)
- [Mobile app architecture](#mobile-app-architecture)
- [Offline-first and sync](#offline-first-and-sync)
- [Conflict resolution](#conflict-resolution)
- [Networking on mobile](#networking-on-mobile)
- [Version skew and releases](#version-skew-and-releases)
- [Push and background work](#push-and-background-work)
- [Embedded and IoT](#embedded-and-iot)
- [Fleet operations and OTA updates](#fleet-operations-and-ota-updates)
- [Traps](#traps)

## What changes when the client is a device
- The network is slow, lossy and often absent; the device sleeps; battery and data cost money.
- You cannot roll back code on devices - old versions run for years.
- The client holds state (local DB) that must reconcile with the server.
- Security: the client is untrusted and can be reverse-engineered; never put secrets or
  authorization decisions there.

## Mobile app architecture
- Presentation patterns: MVVM (common on Android/SwiftUI), MVI/unidirectional data flow, VIPER/
  clean architecture for large teams; pick for testability and team size.
- Layers: UI → view models / state holders → repositories (single source of truth = the local
  DB) → network and storage data sources.
- Local storage: SQLite (Room, Core Data, GRDB), key-value for settings, encrypted storage for
  tokens (Keychain/Keystore).
- Modularisation by feature for large apps; dependency injection.

## Offline-first and sync
- The local DB is the source of truth for the UI; the network updates it in the background.
- Queue local mutations (outbox on the device) with idempotency keys; retry with backoff when
  online.
- Delta sync: server keeps a change log/version per record; client asks "changes since version
  N" (with pagination and tombstones for deletes) instead of downloading everything - but see
  the change-feed cursor trap below.
- Per-device operation numbering lets the server detect gaps and reject replays; compact
  repeated unsent edits to the same field into one operation before upload.
- Test the client's local database migrations from every supported app version.
- Audit-sensitive data (inspections, claims): tamper-evident op logs (hash chains), immutable
  evidence storage - and reconcile that with deletion obligations.
- Decide which features work offline and what the user sees when they cannot.

## Conflict resolution
| Strategy | Fits | Loses |
|---|---|---|
| Last-write-wins (timestamp/version) | settings, simple fields | concurrent edits |
| Server wins / client wins | authoritative data | the other side's change |
| Field-level merge | forms, profiles | conflicting edits to the same field |
| CRDTs | collaborative text, lists, counters | metadata size, complexity |
| Ask the user | rare, high-value conflicts | user time |
Choose per data type and say it.

## Networking on mobile
- Fewer, larger requests; compress; paginate; prefetch on Wi-Fi.
- Timeouts and retries tuned for cellular; resumable uploads (chunked, multipart).
- HTTP/3/QUIC helps on lossy networks and network switches.
- Image sizes per device density via CDN transforms.
- A BFF per client to shape payloads for screens.

## Version skew and releases
- Assume clients 6-24 months old hit the newest API: additive API changes, versioned endpoints,
  tolerant readers, a minimum-supported-version check with a forced-upgrade screen.
- Server-driven configuration and feature flags (kill switches) to change behaviour without a
  release.
- Phased store rollouts (staged percentages); crash and ANR monitoring per version.

## Push and background work
- Push via APNs/FCM: best effort, rate-limited, may be delayed; use silent pushes to trigger sync,
  not to carry critical data.
- OS limits background execution; use the platform schedulers (WorkManager, BGTaskScheduler).

## Embedded and IoT
- Constraints: KB-MB of RAM, low-power CPUs, battery for years, intermittent links.
- Protocols: MQTT (pub/sub over TCP, QoS 0/1/2, retained messages, last will) for most telemetry;
  CoAP (UDP, REST-like) for very constrained devices; BLE/Zigbee/LoRa to a gateway.
- Topology: device → gateway (optional) → broker/ingest → stream processing → time-series store;
  commands back through the broker with acknowledgements.
- Device identity: unique per-device credentials (X.509 certs) provisioned at manufacture, never a
  shared key; rotation and revocation.
- Device shadow / digital twin: last reported and desired state, so commands survive offline
  devices.
- Size the broker for the **reconnect storm** (all devices reconnecting after an outage) with
  jittered backoff on devices, not only for average message rate.
- Edge processing: filter and aggregate on device/gateway to save bandwidth and power.

## Fleet operations and OTA updates
- OTA with A/B partitions (or a recovery partition) and automatic rollback if the new image fails
  health checks; signed images and secure boot.
- Staged rollout by cohort (1% → 10% → 100%) with halt on failure metrics.
- Delta updates to save bandwidth; resume interrupted downloads.
- Fleet telemetry: version distribution, crash/reboot rates, connectivity.

## Traps

### Change-feed cursors from an auto-increment sequence skip rows
**Seen in:** blind-graded eval `d-mobile` (offline field inspection), 2026-11-02 - the
no-skill design used `bigserial` as the cursor; the grader flagged the silent skip.
**Mistake:** "changes since sequence N" with N assigned at insert.
**Instead:** order the feed by commit - serve only changes below the oldest in-flight
transaction, or use a log-based (CDC) position.
**Why:** a slow transaction commits a lower number after a client has read past it, and that
change is never delivered.
