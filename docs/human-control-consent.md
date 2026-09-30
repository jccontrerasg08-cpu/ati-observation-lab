# Consent-Based Human Control Procedure

**Status:** Required before any human-control request is included in the corpus.  
**Scope:** A voluntary, controlled laboratory visit to `https://observe.ati-observation-lab.com` using the closed `/lab/*` route catalogue. This is not a public-site analytics program and does not authorize collection from unconsenting visitors.

## Participant notice

> You are invited to perform a short, voluntary test of a laboratory website so that a privacy-preserving automation detector can measure false-positive behavior under controlled conditions. Participation is optional. You may stop at any time, without explanation or penalty. Do not enter personal information, log in, submit forms, upload files, use a query string, or send cookies or credentials. The laboratory does not intentionally retain raw IP addresses, cookies, query strings, request or response bodies, browser fingerprints, prompts, or account information. It records only a limited, opaque, privacy-approved HTTP observation record and a random request-correlation identifier.

The participant must understand that the visit is not a diagnosis of whether they are human, trustworthy, or an AI user. The participant’s browser and network may still produce normal transport data at network providers; this laboratory’s corpus and labels must not retain raw IP data.

## Required affirmative consent record

Before starting, the participant states or records locally:

> “I understand that this is a voluntary controlled observation test. I consent to the collection of the privacy-limited HTTP records described above for research evaluation. I will not send personal data, credentials, cookies, query parameters, content, or account information. I may stop at any time.”

The local consent record stores only: consent date, corpus ID, protocol version, and a non-identifying participant-local alias if needed for the operator’s audit. It must not store a name, email address, IP address, browser fingerprint, or account identifier.

## Operator prerequisites

The operator must confirm all items before the participant begins:

| Check | Required outcome |
|---|---|
| Marker | `owned-domain-2026-09-26-pf2-matched-human-consented` is deployed and only used after affirmative consent; the automated cohort of the same campaign uses `owned-domain-2026-09-26-pf2-matched-automated` |
| Endpoint | Custom Domain resolves with valid HTTPS; direct Railway origin remains unavailable |
| Protocol | Participant receives the closed route sequence and a way to send only the approved marker and signed session header |
| Local capture | The executor records only `X-ATI-Request-ID`, method, closed path, expected status, observed status, a local sequence number, cohort, task, pacing variant code, collection window, executor, scenario and catalogue versions |
| Exclusions | No response or local record contains the signed session token, raw address, cookie, query, authorization value, body, full User-Agent, or arbitrary header |
| Executor reachability | The executor reaches the Worker rather than an edge denial. The managed browser-integrity rule answers `403` (error `1010`) for the Python standard library's default User-Agent, so a client that trips it is silently absent from the corpus instead of failing visibly. `ati-lab-session` runs this check itself and refuses to start if it fails |
| Header reading | The executor reads response headers case-insensitively. The Worker keeps its own casing on `X-ATI-Lab-Session` while the origin's `X-ATI-Request-ID` arrives lowercased, so a case-sensitive read loses the correlation identifier with no error |
| Stop condition | Operator agrees that any unexpected data field, status, or route stops the control and excludes its incomplete session |

## Closed route sequence

The participant follows the **ATI-PF-2 shared task graph**, the same route plan available to every automated family. They must send the approved human marker on every request and preserve the short-lived signed session header only for the later `/lab/*` requests.

| Order | Method | Path | Expected status |
|---:|---|---|---:|
| 1 | GET | `/lab/start` | 200; receive opaque session header and opaque request ID |
| 2 | GET | `/lab/page/landing` | 200 |
| 3 | GET | `/lab/assets/site.css` | 200 |
| 4 | GET | `/lab/page/catalog` | 200 |
| 5 | GET | `/lab/assets/pixel.svg` | 200 |
| 6 | GET | `/lab/page/detail` **or** `/lab/page/related` | 200 |
| 7 | GET | `/lab/complete` | 200 |

The operator assigns the task, and therefore the branch at step 6, from the same menu used for the automated cohort, balancing tasks across both cohorts. Assigning rather than letting the participant choose keeps the task label identical in meaning for both classes.

> **This replaces the earlier six-request sequence, which ended at `/lab/missing`.** That
> plan cannot be used for an ATI-PF-2 corpus for two independent reasons. `/lab/missing`
> is not an eligible ATI-PF-2 route, so `ati pf2-preflight` rejects any session containing
> it outright. And because every automated family terminates at `/lab/complete` while that
> plan never reached it, the completion flag and the route-category counts would have
> separated the cohorts perfectly — a route category present in only one target class,
> which the feature contract forbids. Running the old plan would have produced either a
> rejected corpus or a model that learned the executor instead of the behavior.

A standard browser navigation cannot automatically replay a custom response session header on the next request. The operator must therefore use the approved local executor, `ati-lab-session`, which carries only the marker and the transient session header, defers every request to the participant, and records only the fields listed below. The signed header is never written to the label file, shared with third parties, or pasted into this document.

The automated cohort runs through the **same** executor, with the same route plan and the same H1–H3 regimes on a timer. Executor, User-Agent, header handling, route plan and pacing regime are then shared by both classes, so none of them can separate the cohorts; see the matched-executor design in the laboratory README.

```bash
ati-lab-session --cohort human-consented \
  --marker owned-domain-2026-09-26-pf2-matched-human-consented \
  --task task-detail \
  --pacing-variant H1 \
  --collection-window 2026-09-27-block-1 \
  --output ./local/sessions/human-01.json
```

For the human cohort the executor waits for the participant before each request, so pacing comes from the person; the declared variant is shown to them as guidance only, and no delay is recorded. A consented participant may only be assigned H1, H2 or H3. The executor declares its own User-Agent; it is neither a browser nor a known scripted client, so the edge records its coarse provenance as `other`. That category is audit-only and excluded from every model workflow, so it neither helps nor harms the corpus — but do not disguise the executor as a browser to change it.

## Pacing variants

To avoid a single laboratory script becoming a proxy for class, select one pacing variant before the session and document only the variant code:

| Variant | Controlled pacing guidance |
|---|---|
| H1 | Pause 5–12 seconds between requests, selecting each pause independently within the range |
| H2 | Pause 12–25 seconds between requests, selecting each pause independently within the range |
| H3 | Pause 25–45 seconds between requests, selecting each pause independently within the range |

Do not record the exact delay vector in the corpus. The operator may keep a local completion note that identifies the variant code only.

## Completion, labeling, and withdrawal

For each accepted response, record the returned opaque `X-ATI-Request-ID` locally with `controlled_automation=false`, `condition=human_consented`, scenario version, pacing variant code, method, closed path, and status. The human control is valid only if **every** request identifier in the plan matches one exported JSONL record apiece and the expected status sequence occurs; a session with a missing or duplicated identifier is excluded rather than repaired. `ati-lab-session` writes exactly these fields and marks the session `excluded` with a reason when any step deviates.

The participant may ask the operator to withdraw their session before it is aggregated or used. In that case, the operator deletes the associated local labels and exported JSONL rows using opaque request IDs, verifies the deletion, and records only an aggregate withdrawal count. The participant does not need to explain the request.

## Non-permitted alternatives

Do not label an unmarked public visitor as human. Do not infer consent from a browser User-Agent, IP address, account, provider, or browsing style. Do not ask participants to disable privacy protections, use personal accounts, reveal their location, or install a fingerprinting tool. Do not send the participant to a third-party website or request activity beyond this laboratory’s closed route catalogue.
