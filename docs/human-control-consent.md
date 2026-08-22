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
| Marker | `owned-domain-2026-08-22-human-consented` is deployed and only used after affirmative consent |
| Endpoint | Custom Domain resolves with valid HTTPS; direct Railway origin remains unavailable |
| Protocol | Participant receives the closed route sequence and a way to send only the approved marker and signed session header |
| Local capture | The executor records only `X-ATI-Request-ID`, method, closed path, expected status, scenario version, and a local session sequence number |
| Exclusions | No response or local record contains the signed session token, raw address, cookie, query, authorization value, body, full User-Agent, or arbitrary header |
| Stop condition | Operator agrees that any unexpected data field, status, or route stops the control and excludes its incomplete session |

## Closed route sequence

The participant uses an ordinary browser and the same logical sequence as the automation families. They must send the approved human marker on every request and preserve the short-lived signed session header only for the later `/lab/*` requests. The route plan is:

| Order | Method | Path | Expected status |
|---:|---|---|---:|
| 1 | GET | `/lab/start` | 200; receive opaque session header and opaque request ID |
| 2 | GET | `/lab/page/landing` | 200 |
| 3 | GET | `/lab/assets/site.css` | 200 |
| 4 | GET | `/lab/page/catalog` | 200 |
| 5 | HEAD | `/lab/page/detail` | 200, no response body required |
| 6 | GET | `/lab/missing` | 404 |

A standard browser navigation cannot automatically replay a custom response session header on the next request. The operator must therefore use an approved local executor or browser-tool procedure that can set the marker and transient session header without placing it in a URL or cookie. The signed header is never written to the label file, shared with third parties, or pasted into this document.

## Pacing variants

To avoid a single laboratory script becoming a proxy for class, select one pacing variant before the session and document only the variant code:

| Variant | Controlled pacing guidance |
|---|---|
| H1 | Pause 5–12 seconds between requests, selecting each pause independently within the range |
| H2 | Pause 12–25 seconds between requests, selecting each pause independently within the range |
| H3 | Pause 25–45 seconds between requests, selecting each pause independently within the range |

Do not record the exact delay vector in the corpus. The operator may keep a local completion note that identifies the variant code only.

## Completion, labeling, and withdrawal

For each accepted response, record the returned opaque `X-ATI-Request-ID` locally with `controlled_automation=false`, `condition=human_consented`, scenario version, pacing variant code, method, closed path, and status. The human control is valid only if all six IDs match one exported JSONL record apiece and the expected status sequence occurs.

The participant may ask the operator to withdraw their session before it is aggregated or used. In that case, the operator deletes the associated local labels and exported JSONL rows using opaque request IDs, verifies the deletion, and records only an aggregate withdrawal count. The participant does not need to explain the request.

## Non-permitted alternatives

Do not label an unmarked public visitor as human. Do not infer consent from a browser User-Agent, IP address, account, provider, or browsing style. Do not ask participants to disable privacy protections, use personal accounts, reveal their location, or install a fingerprinting tool. Do not send the participant to a third-party website or request activity beyond this laboratory’s closed route catalogue.
