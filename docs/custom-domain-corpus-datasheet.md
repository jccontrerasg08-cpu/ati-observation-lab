# Custom-Domain Controlled Observation Corpus — Datasheet

**Corpus ID:** `custom-domain-2026-08-22`  
**Status:** Controlled collection in progress; this file is the governing specification, not a claim that the target sample count has been reached.  
**Data controller:** Laboratory operator.  
**Purpose limitation:** Research and evaluation of a privacy-preserving HTTP automation score in the ATI laboratory. The corpus must not be used to identify a person, infer an AI provider, make eligibility decisions, block access automatically, or train a cross-site identity system.

## Motivation and intended use

This corpus tests whether a score trained on allowed aggregate HTTP-session behavior transfers across controlled client families, time periods, and scenarios. It supports offline research only. A model trained or evaluated from this corpus may report results for the documented collection conditions; it does not establish general capability to identify bots, AI agents, or humans on the public internet.

The corpus is designed around request-level local correlation and session-level independence. A response returns `X-ATI-Request-ID`, a fresh random opaque identifier that joins the executor’s local label to one JSONL observation record. The identifier is not an authentication credential, session token, client identifier, or IP address.

## Composition plan

| Condition | Families or participants | Target sessions per family / participant | Ground truth source | Status |
|---|---|---:|---|---|
| Controlled HTTP automation | curl, wget, requests, httpx, node-fetch | 4 | Local executor record with approved marker | Approved |
| Controlled browser automation | Playwright Chromium | 4 | Local executor record with approved marker | Approved |
| Consent-based human control | One or more informed, consenting participants using their ordinary browser | 4 per consenting participant, preferably across more than one participant | Signed/recorded local consent plus local executor record | Requires separate authorized marker and participant action |
| Supplemental external automation controls | Two separately instructed, operator-authorized cloud executors using `external-cloud-a` or `external-cloud-b` | One complete session per external executor initially | Executor-local record with opaque response IDs and declared runtime | Optional robustness evidence; never merged into the fixed primary matrix without a versioned manifest update |

Each session must follow the closed catalogue: `GET /lab/start`, `GET /lab/page/landing`, `GET /lab/assets/site.css`, `GET /lab/page/catalog`, `HEAD /lab/page/detail`, and `GET /lab/missing`. The expected status sequence is `200, 200, 200, 200, 200, 404`. A session must use exactly one approved campaign marker and the signed session header only on later `/lab/*` requests.

The human control should use the same route catalogue but a documented pacing variant selected before execution. It must never be inferred from a browser request lacking consent or from a public visitor.

## Data retained and data prohibited

| Category | Policy |
|---|---|
| Retained in exported JSONL | Existing privacy-approved request ID, coarse timestamp, opaque client pseudonym, opaque session pseudonym when applicable, method, closed path, status, response size, protocol, `ua_provenance_bucket` (`absent`, `scripted-http`, `browser-like`, or `other`), approved campaign marker |
| Retained in local label file | Opaque request ID, documented condition/family, boolean controlled-automation label, scenario version, session-local sequence number |
| Prohibited | Raw IP addresses, geolocation, cookies, query strings, request or response bodies, Authorization values, arbitrary headers, account identifiers, prompts, tool arguments, browser fingerprinting surfaces, raw signed session headers |
| Prohibited as model features | Request ID, campaign marker, client/session pseudonym, raw or exact User-Agent, `ua_provenance_bucket`, provider, executor identity, participant identity, exact timestamp, scenario identifier, route names unique to a class |

## User-Agent provenance boundary

The origin derives `ua_provenance_bucket` in memory and immediately discards the raw User-Agent. The bucket is limited to `absent`, `scripted-http`, `browser-like`, or `other`. It may be reported only as aggregate corpus composition and must never be used for feature construction, preprocessing, calibration, threshold selection, model evaluation, drift scoring, filtering, or analyst decisions intended to improve score.

## Collection, authorization, and consent

Automation is collected only from executors controlled by the laboratory operator or separately authorized external executors, and only with an approved marker. Human control is collected only after the participant reads the consent statement, affirms affirmative consent, understands that participation is optional, and can stop at any point. No participant or external executor must provide a name, email address, account, location, IP address, cookie, browser fingerprint, system prompt, or unrelated output.

Participants and third-party agents must not access any route outside the closed catalogue, alter headers beyond the approved marker and session protocol, send query strings, cookies, credentials, bodies, prompts, or personal data, or use the endpoint for production browsing.

## Labeling and quality checks

Ground truth is an experimental condition, not a behavioral inference. Labels are created locally from the controlled executor’s record and are joined to exported observations only by `X-ATI-Request-ID`. A label is valid only when the local record, approved marker, expected route, expected method, expected status, and JSONL record agree. Rejected perimeter requests, unmarked requests, Workers.dev events, direct-origin requests, and earlier pilot traffic are excluded.

Before modeling, an operator reviews a stratified sample of local labels, confirms no prohibited field appears, verifies one-to-one request-ID joins, and documents missing, duplicate, or unmatched records. Any mismatch stops the affected family from entering the corpus until diagnosed.

## Splits and evaluation boundary

The independent unit is a complete controlled session. Train, calibration, test, temporal, and family/scenario holdout splits must keep all requests from one session together. Feature selection, preprocessing, calibration, and threshold selection use only training/calibration sessions. The final temporal holdout and any unseen-family or unseen-scenario holdout are not used for selection.

Every evaluation report must state session and request counts by class, held-out time window, held-out family/scenario, feature-contract version, threshold origin, TP/FP/TN/FN, FPR/FNR denominators, calibration metrics, and session-cluster uncertainty intervals. The report must say when any estimate is inconclusive due to limited independent sessions.

## Retention and deletion

Keep local label files and exported JSONL only in the access-controlled campaign workspace for the approved research purpose and period. Publish only aggregate results and the datasheet. Delete raw campaign artifacts according to the laboratory’s verified-deletion procedure once the approved retention period ends or the experiment is abandoned. A deletion record may retain corpus version, aggregate counts, deletion date, and verification outcome, but not request IDs or session tokens.

## Known limitations

The corpus is synthetic and controlled, so it can overrepresent protocol conformance, particular runtime versions, laboratory route structure, and expected pacing. Four sessions per family are enough to exercise integration and split mechanics, not to estimate generalization precisely. A small human control cannot establish population-level human false-positive rates. This corpus must never be represented as a benchmark for all AI agents, all automation, or all human web traffic.
