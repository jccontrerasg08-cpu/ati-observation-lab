# Custom-Domain Observation Campaign Matrix

**Status:** Approved controlled plan; traffic begins only after the reviewed configuration is deployed and the acceptance checks below pass.

## Purpose and scope

This matrix creates reproducible, privacy-preserving observations through the exact Custom Domain `https://observe.ati-observation-lab.com`. It is designed to test controlled navigation behavior across independent runtime families, rather than to assert the identity or intent of an external visitor. The Railway-generated domain remains an origin-only endpoint and must continue to reject direct observation requests. The Workers.dev hostname is retained for compatibility checks but its new observations are excluded from this corpus because it deliberately uses campaign-scoped rather than edge-address-scoped client pseudonyms.

Each marker below is an opaque, reviewed campaign identifier. It is local ground-truth context only. It must not be treated as a detector feature, a secret, an account identifier, or evidence that a runtime family is an AI agent.

## Approved matrix

Each family executes four independent sessions. Every session starts with `GET /lab/start` and then follows the closed navigation sequence. The expected User-Agent token is set deliberately by the controlled client so that runtime validation can detect a misconfigured executor without retaining any personal or ambient browser identifier.

| Family | Campaign marker | Expected User-Agent token | Sessions | Ground-truth class |
|---|---|---|---:|---|
| curl | `owned-domain-2026-08-22-curl` | `ATI-Lab/curl` | 4 | controlled automation |
| wget | `owned-domain-2026-08-22-wget` | `ATI-Lab/wget` | 4 | controlled automation |
| requests | `owned-domain-2026-08-22-requests` | `ATI-Lab/requests` | 4 | controlled automation |
| httpx | `owned-domain-2026-08-22-httpx` | `ATI-Lab/httpx` | 4 | controlled automation |
| node-fetch | `owned-domain-2026-08-22-node-fetch` | `ATI-Lab/node-fetch` | 4 | controlled automation |
| playwright-chromium | `owned-domain-2026-08-22-playwright-chromium` | `ATI-Lab/playwright-chromium` | 4 | controlled automation |

A separately approved human control may be added later with a distinct marker and a documented consenting executor. No unmarked request, infrastructure smoke request, or pre-existing Workers.dev event belongs in this campaign corpus.

## Closed session sequence

The executor sends the same campaign marker and expected User-Agent token on every request in a session. `GET /lab/start` must be sent without `X-ATI-Lab-Session`. The Worker returns a signed opaque token in `X-ATI-Lab-Session`; the executor sends that token only in the subsequent five `/lab/*` requests of the same session. It must never place the token in a cookie, URL, query string, log, label, or source-controlled file.

| Order | Method | Path | Expected status | Session header |
|---:|---|---|---:|---|
| 1 | GET | `/lab/start` | 200 | Absent on request; captured from response |
| 2 | GET | `/lab/page/landing` | 200 | Present |
| 3 | GET | `/lab/assets/site.css` | 200 | Present |
| 4 | GET | `/lab/page/catalog` | 200 | Present |
| 5 | HEAD | `/lab/page/detail` | 200 with no response body | Present |
| 6 | GET | `/lab/missing` | 404 | Present |

The control plane rejects a query string, fragment, Cookie, `Authorization`, `Proxy-Authorization`, request body, unsupported method, missing marker, invalid marker, invalid session, or a path outside this table. These rejected inputs must be exercised only as perimeter checks and excluded from the observation corpus.

## Local plan and label preparation

The `ati campaign plan` command produces one non-secret local plan per family because campaign markers are intentionally family-specific. The following example prepares the curl plan; repeat it with the matching marker, family name, and expected token from the approved matrix.

```bash
ati campaign plan \
  --campaign-id owned-domain-2026-08-22-curl \
  --corpus-id custom-domain-2026-08-22 \
  --family curl=ATI-Lab/curl \
  --sessions-per-family 4 \
  --output curl-plan.json
```

Keep plans, local executor records, local labels, and exported JSONL in an access-controlled working directory outside the repository. Labels should reference the local request correlation identifier and the approved family declaration only. They must not add raw client addresses, full User-Agent strings beyond the approved token, cookies, credentials, request bodies, query strings, arbitrary headers, or session tokens.

## Acceptance and stop conditions

A family is ready for collection only when its independent sessions complete the closed sequence with the expected statuses, each record has the approved campaign marker, each `/lab/*` record has an opaque session pseudonym, and `ati campaign validate-runtime` reports no incompatible or missing-session records for that family. The operational acceptance suite must also show a 200 response through the Custom Domain, a 503 response from the direct Railway origin, and rejection of prohibited perimeter inputs.

Stop the campaign immediately if a prohibited field appears in a record or label, a direct Railway request succeeds, a session crosses campaign markers, the configured rate limit causes unexpected failures, a runtime does not produce the expected session sequence, or a client family cannot be labeled from a local controlled execution record. Preserve the minimum necessary evidence for diagnosis and follow the retention and verified-deletion procedure before retrying.

## Evaluation boundary

The completed corpus supports grouped session/client splits, temporal holdout, an unseen-family holdout, and provider/User-Agent ablation. It does not establish general detection capability by itself. Report the size and composition of every split, false-positive and false-negative rates with denominators, calibration metrics, and uncertainty. Do not choose a threshold against the final unseen-family holdout.
