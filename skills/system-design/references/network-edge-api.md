# Network, edge and APIs

## Contents
- [DNS and global traffic](#dns-and-global-traffic)
- [Load balancing](#load-balancing)
- [CDN and edge caching](#cdn-and-edge-caching)
- [API styles](#api-styles)
- [API contract essentials](#api-contract-essentials)
- [Real-time push](#real-time-push)
- [Rate limiting and admission control](#rate-limiting-and-admission-control)
- [Transport choices](#transport-choices)

## DNS and global traffic
- GeoDNS / latency-based routing sends users to a nearby region; anycast IPs (used by CDNs and
  global load balancers) let the network route to the nearest edge.
- DNS failover is only as fast as TTLs and client caching allow (minutes, often longer in
  practice); anycast or a global L7 load balancer fails over faster.
- DNS is a shared dependency of every "redundant" path; count it in availability math.

## Load balancing
| | L4 (TCP/UDP) | L7 (HTTP/gRPC) |
|---|---|---|
| Sees | IPs, ports | paths, headers, cookies, methods |
| Can do | very high throughput, connection-level spreading, pass-through TLS | routing by path/host, retries, header-based canaries, TLS termination, auth offload |
| Watch | long-lived connections pin load to a few backends | it is a hop with its own capacity and failure modes |
- Algorithms: round robin, least connections / least outstanding requests (better with uneven
  request cost), consistent hashing (stickiness for caches), power-of-two-choices.
- gRPC and HTTP/2 multiplex many requests on one connection: L4 balancing then spreads
  connections, not requests - use L7 or client-side balancing.
- **Health checks can take a system down.** Deep checks that query the DB fail every instance at
  once when the DB is slow, and the LB ejects the whole fleet. Keep LB checks shallow (process up
  and able to serve); report dependency trouble through readiness and degraded responses.

## CDN and edge caching
- Pull (cache on first request) for most content; push/pre-warm for known launches.
- `Cache-Control` per path: `max-age`, `immutable` for content-hashed assets,
  `stale-while-revalidate` and `stale-if-error` to ride out origin trouble.
- Normalise cache keys (drop tracking params and irrelevant cookies) or the hit ratio collapses.
- An **origin shield** (one mid-tier cache) collapses concurrent misses from many edges into one
  origin request; request coalescing does the same per node.
- Add jitter to TTLs so mass expiry does not stampede the origin.
- Egress is often the largest bill line for media; estimate it.

## API styles
| Style | Use for | Watch |
|---|---|---|
| REST/JSON over HTTP | public APIs, cacheable reads, broad client support | over/under-fetching, chatty clients |
| gRPC (HTTP/2 + Protobuf) | internal service-to-service, streaming, strict schemas | browser support needs a proxy; L7 balancing |
| GraphQL | many client shapes over one graph (often via a BFF or federation) | query cost limits, N+1 resolvers, caching is harder |
| Async (queue/stream) | work that need not finish in the request | see services-architecture.md |
- A **BFF** (backend for frontend) per client type keeps client-specific aggregation out of core
  services.

## API contract essentials
- **Idempotency keys** on every mutating endpoint that a client may retry (payments, orders):
  store key → result, return the stored result on replay, expire after the retry window.
- **Pagination**: cursor/keyset (stable under inserts, O(1) per page) over offset.
- **Versioning**: additive changes only within a version; old mobile clients live for years.
- **Timeouts and deadlines** propagated across hops (gRPC deadlines); a callee should stop work
  the caller has abandoned.
- Error model: retryable vs not, with `Retry-After` for throttling.
- Large payloads: upload directly to object storage with pre-signed URLs; never through the API
  tier.

## Real-time push
| | WebSocket | Server-Sent Events | Long polling | Push notifications |
|---|---|---|---|---|
| Direction | both | server → client | server → client | server → device, via APNs/FCM |
| Good for | chat, collaboration, games | feeds, LLM token streaming, live status | fallback | app not open |
| Cost | stateful connections; needs a connection registry and resume protocol | plain HTTP, auto-reconnect | request per message | best effort, rate-limited |
- Size gateways by concurrent connections (memory per connection) not QPS, and plan the
  **reconnect storm** after a deploy or outage (jittered backoff, staged drain).

## Rate limiting and admission control
- Algorithms: token bucket (bursts allowed up to the bucket), leaky bucket (smooth output), fixed
  window (cheap, edge bursts), sliding window log/counter (accurate, more memory).
- Limit per API key/tenant/user/IP at the edge; separate limits for expensive endpoints.
- Decide **fail-open or fail-closed** when the limiter store (e.g. Redis) is down: fail-open
  protects availability, fail-closed protects the backend. State it per endpoint.
- Under overload, shed load early (at the edge) and by priority, rather than queueing everything.

## Transport choices
- TCP: reliable, ordered; head-of-line blocking per connection.
- HTTP/2: multiplexing over one TCP connection, still TCP-level head-of-line blocking.
- HTTP/3 (QUIC over UDP): per-stream loss recovery, faster handshakes, connection migration
  (helps mobile networks).
- UDP: real-time media and games where late data is useless.
