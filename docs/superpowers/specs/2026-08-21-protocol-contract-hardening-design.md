# Protocol Contract Hardening Design

## Status

Approved design for the next ATI Observation Lab hardening slice. This change repairs the Worker-to-FastAPI session-start contract, makes cookie rejection consistent across all observed routes, and adds CI coverage that validates both sides of the protocol together.

## Goals

1. Make `/lab/start` succeed end-to-end through the Cloudflare Worker and FastAPI origin.
2. Enforce the production rule that requests carrying `Cookie` are rejected before any observation is accepted or recorded, including `/observe`.
3. Add regression coverage for the actual protocol boundary rather than testing the Worker and FastAPI only in isolation.
4. Make CI execute the Worker validation that is already used manually during pull-request verification.
5. Preserve the current privacy model and JSONL compatibility with `agent-traffic-intelligence`.

## Non-goals

- No database, queue, Kafka, CQRS, microservice split, service mesh, or persistent session store.
- No cookie-based production session support.
- No detector-model changes.
- No new production observation fields.
- No client fingerprinting beyond the existing edge-derived pseudonyms.
- No analytics warehouse or streaming platform in this repository.

These patterns are intentionally deferred until a measured requirement exists. The lab is small enough that adding them now would increase failure modes without improving the experiment.

## Architecture choice

The lab keeps a small client-server deployment but adopts clearer **hexagonal boundaries** around the protocol:

- **Edge adapter:** Cloudflare Worker validates public input, issues and verifies the short-lived opaque lab-session token, derives pseudonyms, strips untrusted identity headers, and forwards only the allowlisted internal context.
- **Origin adapter:** FastAPI validates the trusted edge contract again, applies rate limits and route policy, serves deterministic synthetic resources, and emits privacy-safe observation events.
- **Observation event boundary:** accepted requests become immutable JSONL records. This is event-driven in the narrow sense that the record is an output event, not an excuse to introduce a broker.
- **Evaluation boundary:** downstream ATI tooling consumes exported JSONL and local ground-truth labels. Campaign markers, client pseudonyms, session pseudonyms and request IDs remain evaluation metadata, not detector features unless separately authorized.

This selectively applies ideas from layered, hexagonal, event-driven, TDD, CI/CD, networking/security, and data-analytics architecture. It explicitly avoids architecture-by-checklist.

## Protocol invariants

### Public request invariants at the Worker

The Worker accepts only `GET` and `HEAD` for `/observe` and the closed `/lab/*` catalogue. It rejects:

- query strings or fragments,
- `Cookie`, `Authorization`, or `Proxy-Authorization`,
- request bodies and unsupported methods,
- non-allowlisted campaign markers,
- invalid or missing session tokens on non-start lab routes,
- invalid runtime configuration.

The Worker never forwards `CF-Connecting-IP`, `X-Forwarded-For`, a raw lab-session token, or client-supplied proxy credentials.

### Internal request invariants at FastAPI

FastAPI accepts an observed request only when:

- `X-ATI-Proxy-Token` matches the configured origin secret,
- `X-ATI-Proxy-Client-ID` matches the edge HMAC format,
- every `/lab/*` request carries a valid proxy-derived session pseudonym,
- the path belongs to the backend's closed route catalogue,
- the request has no query string,
- the request has no `Cookie` header,
- the pseudonymous client is within the configured rate limit.

FastAPI must reject cookies on `/observe` as well as `/lab/*`. This provides defense in depth if a request reaches Railway with otherwise valid trusted-proxy headers.

## `/lab/start` contract

`/lab/start` is a synthetic origin resource, not a session issuer. Session issuance remains exclusively at the Worker.

Flow:

1. Client sends `GET` or `HEAD /lab/start` to the Worker with no session header.
2. Worker creates a signed 15-minute `ati1.<payload>.<signature>` token.
3. Worker derives `X-ATI-Proxy-Session-ID` from the raw token.
4. Worker forwards `/lab/start` to FastAPI with the proxy token, client pseudonym, derived session pseudonym, optional allowlisted campaign marker, and truncated User-Agent.
5. FastAPI recognizes `/lab/start` as part of the closed catalogue and returns deterministic `200` content.
6. FastAPI emits one observation record containing the derived `session_id`, never the raw session token.
7. Worker returns the origin response and adds `X-ATI-Lab-Session` to the client-facing response.

`HEAD /lab/start` must return the same status, content type, content length metadata and session header semantics as `GET`, while returning no body.

## Closed route catalogue

The Worker and FastAPI must agree on the following routes:

- `/observe`
- `/lab/start`
- `/lab/page/landing`
- `/lab/page/catalog`
- `/lab/page/detail`
- `/lab/assets/site.css`
- `/lab/assets/pixel.svg`
- `/lab/missing`

The implementation should minimize duplicated policy where practical, but it does not introduce a build-time code generator in this slice. The important property is a contract test that fails when either side diverges.

## Observation record contract

No new production fields are required. Accepted requests continue to emit:

- `request_id`
- `time_iso8601`
- `client_id`
- optional `session_id`
- `request_method`
- path-only `request_uri`
- `status`
- `body_bytes_sent`
- `server_protocol`
- truncated `http_user_agent`
- optional `ati_campaign_id`

The following must remain absent from logs and local exports:

- raw IP addresses,
- raw `X-ATI-Lab-Session` values,
- cookies,
- query strings,
- Authorization values,
- proxy tokens,
- raw edge client pseudonyms,
- request bodies,
- arbitrary headers.

## Contract-test strategy

Unit tests remain valuable, but a new protocol-contract test must exercise the integration semantics between the two components.

The contract suite must cover:

1. `GET /lab/start` succeeds through the Worker and produces an origin observation with a derived session pseudonym.
2. `HEAD /lab/start` succeeds with an empty body and equivalent representation metadata.
3. The returned raw session token can be reused for `/lab/page/landing`, `/lab/page/catalog`, and `/lab/page/detail`, producing one stable derived `session_id`.
4. Missing, tampered, and expired sessions are rejected before origin observation.
5. Cookies are rejected on both `/observe` and `/lab/*` and never logged.
6. Query strings, Authorization headers, unsupported methods, spoofed forwarded identity, and client-supplied proxy credentials cannot cross the edge boundary.
7. `/lab/missing` deterministically returns and records `404` within the same session.
8. Raw session tokens and secret proxy values never appear in FastAPI JSONL output.
9. Worker and backend route catalogues cannot silently diverge.

Because the Worker is JavaScript and FastAPI is Python, this slice should not introduce a cross-language runtime bridge solely for testing. The integration contract can be validated by combining deterministic component tests with a catalogue-consistency regression and a focused smoke test against the real deployed boundary when deployment credentials are available. CI must remain secretless and deterministic.

## CI design

CI keeps the Python 3.11 and 3.13 matrix and adds an independent Worker job.

### Python job

- hash-locked dependency installation,
- `ruff check .`,
- `pytest -q`,
- package build verification.

### Worker job

- supported Node runtime,
- `node --check cloudflare-worker/src/index.mjs`,
- `node --test cloudflare-worker/test/proxy.test.mjs`,
- pinned `wrangler@4.42.1 deploy --dry-run --config cloudflare-worker/wrangler.jsonc`.

The Worker job must not need production secrets because its tests use synthetic environment values and the Wrangler dry run validates configuration shape rather than deploying.

## Error handling

The current fail-closed status semantics remain:

- `400`: prohibited request shape such as query, cookie, unsupported route, or method at the public boundary.
- `403`: invalid campaign authorization or missing/invalid lab-session context.
- `429`: pseudonymous client rate limit exceeded.
- `503`: trusted-proxy or runtime configuration unavailable/invalid.

Rejected requests must not generate observation records.

## Security and privacy rationale

The production edge remains the only component that sees the connecting address and the only component that handles the raw navigation token. Railway receives two one-way derived pseudonyms, one for client grouping and one for session grouping. FastAPI repeats policy checks so accidental edge regressions do not automatically broaden the origin's accepted input.

Cookie rejection is global for observed routes because accepting a cookie that is merely ignored still creates an unnecessary privacy and correlation surface. A separate cookie comparison, if ever approved, remains isolated under the research boundary document and cannot reuse this production Worker/origin pair.

## Analytics and experiment-readiness

The architecture remains analytics-ready without embedding an analytics platform into the service. JSONL records are intentionally append-only and can later be transformed into session-grouped experiment tables. The primary analytical unit for navigation experiments is a session, so train/validation/holdout partitioning must keep every record from one `session_id` in exactly one split.

Future campaign tooling may add reproducible manifests, seeds, timing distributions, controlled client families, ground-truth joins by `request_id`, calibration metrics and dataset cards. Those belong in a later experiment-harness slice after this protocol is stable.

## Acceptance criteria

The slice is complete only when:

1. `/lab/start` works through both components for GET and HEAD.
2. `/observe` and every `/lab/*` route reject Cookie before logging.
3. The two previously open Codex review findings are addressed in code/docs and can be resolved with evidence.
4. Python tests, Ruff, package build, Worker syntax check, Worker tests, and Wrangler dry run pass.
5. CI executes both Python and Worker validation.
6. A reviewer can trace the Worker-to-origin session data flow without reading implementation internals.
7. No new persistent state, database, broker, production secret, detector feature, or privacy-sensitive field is introduced.
