# ATI-PF-2 Live Perimeter and Collection Evidence

**Run date:** 2026-09-26  
**Edge:** Cloudflare Worker `ati-observation-proxy` at `observe.ati-observation-lab.com`  
**Origin:** Railway service `ati-observation-lab` (project `triumphant-miracle`, `production`)

Every probe below was anonymous or carried only a marker already allowlisted in the
versioned Worker configuration. No probe carried a credential, cookie, body, personal
data, or a real participant's traffic. Rejected perimeter probes are excluded training
examples by the feature contract and are not part of any corpus.

## Perimeter conformance: 22 of 22 as specified

These checks are now a maintained command, `ati-lab-perimeter` (`make perimeter`), rather
than a one-off script. Its route-by-route catalogue check replaces the single controlled
`404` probe below, so every `/lab/*` route is compared against the shared catalogue on
each run.

| Check | Expected | Observed |
|---|---|---|
| `/lab/start` with no marker | `403` | `403` |
| `/lab/start` with an unallowlisted marker | `403` | `403` |
| `/lab/start` with a malformed marker | `403` | `403` |
| Route outside the closed catalogue | `400` | `400` |
| `/healthz` through the Worker | `400` | `400` |
| Query string present | `400` | `400` |
| `Cookie` header present | `400` | `400` |
| `Authorization` header present | `400` | `400` |
| `POST` method | `400` | `400` |
| `/lab/start` issues an opaque session and request id | `200` + both | `200` + both |
| Continuation without the signed session | `403` | `403` |
| Tampered signed session | `403` | `403` |
| Valid session replayed under another campaign | `403` | `403` |
| Correctly bound session continues with a fresh request id | `200` + new id | `200` + new id |
| `/lab/start` presenting an existing session | `403` | `403` |
| `HEAD` matches `GET` status and content type, no body | equal, 0 bytes | equal, 0 bytes |
| `/lab/missing` controlled error path | `404` | `404` |
| `Cache-Control: no-store` and no `Set-Cookie` | `no-store`, absent | `no-store`, absent |
| Railway origin refuses direct observation | `503` | `503` |
| Railway origin `/healthz` available | `200` | `200` |
| Origin refuses a forged proxy client id without the shared token | `503` | `503` |
| Edge bans only the Python stdlib User-Agent | `403`/`1010`, others `400` | matched |

The campaign-binding and `/lab/start`-rejects-an-existing-session results confirm the
signed session is bound to one marker and cannot be extended or re-minted by a caller.

## Collection run

Six automated executor families ran a two-task route graph through the live edge: `curl`,
`wget`, `python-requests`, `httpx`, Node `fetch` (undici), and Chromium driven by
Playwright.

| Metric | Value |
|---|---|
| Sessions sent | 24 |
| Observed requests | 148 |
| Throttled (`429`) responses | 0 |
| Non-`200` responses | 0 |
| Elapsed | 373 s |
| Sessions reconciled | 23 |
| Corpus rows | 141 |

One session was excluded because its `/lab/start` row fell outside the retrieved log
windows, so its local request identifiers did not each match one exported row. The
protocol excludes an incomplete session rather than inferring the missing record.

The companion record in `agent-traffic-intelligence`
(`docs/architecture/pf2-live-collection-evidence.md`) holds the corpus composition and
the outcome of running the ATI-PF-2 preflight over this corpus: it **refused** the corpus
because every family in the run is automated, so the corpus has one class. A Playwright
-driven Chromium is not a consented human control.

## Findings that change the collection protocol

### 1. Cloudflare bans one declared executor family before the Worker runs

Cloudflare answers `403` with error `1010` — "the owner of this website has banned your
access based on your browser's signature" — for the Python standard-library client's
default `Python-urllib/3.11` User-Agent. The Worker never executes, so none of its
contract applies and nothing is logged at the origin.

Verified against the same path in the same run:

| User-Agent | Result |
|---|---|
| `curl/8.5.0` | reaches the Worker (`400` for `/healthz`) |
| `Wget/1.21.4` | reaches the Worker |
| `python-requests/2.34.2` | reaches the Worker |
| `python-httpx/0.28.1` | reaches the Worker |
| `undici` | reaches the Worker |
| headless-Chrome UA | reaches the Worker |
| *(empty)* | reaches the Worker |
| `Python-urllib/3.11` | **`403`, error `1010`** |

A family whose client trips that managed rule is **absent** from the corpus rather than
visibly failing, which biases corpus composition by executor family without any local
error. Confirm every declared family reaches the Worker before opening a campaign, and
record the check alongside the runtime validation.

### 2. The address-derived pseudonym is not stable within a session

Within single sessions of this run, `client_id` changed between consecutive requests while
the edge-derived `session_id` stayed fixed. The collecting host's egress address rotates,
and `client_id` is a keyed pseudonym of that address.

Consequences, all of which the current contract already implies but which this run makes
concrete:

- Group splits must key on `session_id`. `client_id` is unusable as a grouping key when
  traffic originates from a multi-address host.
- The per-pseudonym rate limit is weaker than it appears against such a host, because the
  limiter's key changes with the address.
- `client_id` remains what the README says it is: not a device, person, or identity.

### 3. Response header casing differs by hop

The Worker re-emits `X-ATI-Lab-Session` in its own casing, while the origin's
`X-ATI-Request-ID` reaches the client lowercased as `x-ati-request-id`. An executor that
reads response headers case-sensitively silently loses the request-correlation identifier
and then cannot reconcile its local labels against the exported rows — with no error.

This is the response-side counterpart of the request-side normalization already fixed for
declarative headers. Executors must read response headers case-insensitively; the
consent-procedure executor checklist should state it explicitly.

### 4. The per-pseudonym rate limit caps intra-session pacing from one host

`ATI_RATE_LIMIT_PER_MINUTE` is 30 per opaque pseudonym. Sustained sub-second pacing
across many sessions is not achievable from a single edge address. Bursting within a
session at roughly 0.3 s and idling between sessions held the run at about 22 observed
requests per minute with zero `429` responses, and preserved realistic intra-session
delay bins. A flat inter-request delay chosen to satisfy the limiter would instead have
collapsed the coarse tempo features to a single bin, quietly removing a permitted feature
family from the corpus.

## Fixes applied after this run

Two defects the run exposed were corrected rather than only recorded.

**The coarse provenance bucket understated scripted traffic.** Node's global `fetch` sends
exactly `node` as its User-Agent. The Worker's marker list carried `node-fetch` and
`undici` but not the bare token, so a declared executor family was bucketed `other`
throughout this run. `ua_provenance_bucket` is audit-only and excluded from every model
workflow, so no model was affected — but corpus-composition reporting, the one thing the
field exists for, was wrong. The Worker now matches bare runtime tokens on token
boundaries, so `node` is `scripted-http` while a browser agent containing a longer word
such as `NodeWebkit` stays `browser-like`. `python-urllib` was added to the substring
markers for the same reason.

**The consent procedure's route plan could not produce a usable corpus.** The plan
predated ATI-PF-2: it ended at `/lab/missing` and never reached `/lab/complete`. That is
unusable for two independent reasons. `/lab/missing` is not an eligible ATI-PF-2 route, so
`ati pf2-preflight` rejects any session containing it outright — verified against the
implementation. And because every automated family terminates at `/lab/complete` while
that plan never did, the completion flag and route-category counts would have separated
the cohorts perfectly, which is exactly the class proxy the feature contract forbids.
Running the old plan would have yielded either a rejected corpus or a model that learned
the executor instead of the behavior. The procedure now follows the shared task graph,
with the branch chosen by the participant.

The approved local executor the procedure assumed now exists as
`ati-lab-session` (`src/observation_lab/pf2/executor.py`), and `ati-lab-corpus`
(`src/observation_lab/pf2/corpus.py`) reconciles its records
against an export. The whole chain — reconcile, preflight, baseline, warehouse export —
was verified end to end on a clearly-labeled two-class fixture.

## Still pending, and pending on a person

A two-class ATI-PF-2 corpus requires the consented human cohort defined in
[`human-control-consent.md`](human-control-consent.md), using the
`owned-domain-2026-08-25-pf2-human-consented` marker, an affirmative consent record, and
a declared pacing variant. Additional automated collection cannot substitute for it, and
browser-driven automation must never be labeled as a human control.
