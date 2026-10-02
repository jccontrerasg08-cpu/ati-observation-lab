# ADR 0003: The edge vouches for every observation

## Status

Accepted.

## Context

The origin on Railway has a public address. If it accepted requests directly, anyone could
write records into the corpus, forge a client pseudonym or invent a session, and the
privacy guarantees would depend on every caller behaving. Client addresses and raw session
tokens are also exactly the data the laboratory must never store.

## Decision

Trust flows one way, from the Cloudflare Worker to the origin:

- **The Worker gates and derives.** It admits only catalogue routes carrying an allowlisted
  campaign marker. It issues an HMAC-signed session token (`ati1.<payload>.<signature>`,
  15-minute lifetime) bound to one campaign. It forwards only opaque HMAC-derived
  pseudonyms, never the raw address or token.
- **The origin refuses what the Worker did not vouch for.** Every observation must carry a
  private proxy token, compared in constant time, and well-formed pseudonyms. Otherwise it
  is refused with `503` and not logged. The origin never falls back to `X-Forwarded-For`,
  `CF-Connecting-IP`, the peer address or a cookie.
- **Defense in depth.** The origin repeats the Worker's query, cookie, catalogue and session
  checks rather than assuming the edge applied them.

## Consequences

- A forged, tampered, cross-campaign or replayed session is refused at the edge. A request
  sent straight to the origin is refused there. `ati-lab-perimeter` proves all of this
  against production after every deploy.
- The origin stores no data that identifies a client.
- Rotating the proxy token or the hash key is a coordinated change across the Worker and
  Railway configuration.
