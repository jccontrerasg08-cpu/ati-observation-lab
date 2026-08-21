# Cookie Session Variant: Research Boundary

## Status

This document describes a **non-deployable research comparison**. It does not add cookie support to the ATI Observation Lab. Production Worker and FastAPI code reject any incoming `Cookie` header before an observation is accepted or recorded.

The deployed protocol uses a signed, opaque, short-lived `X-ATI-Lab-Session` token at the edge and forwards only an HMAC-derived session pseudonym to Railway. It deliberately avoids client-managed cookies.

## Why compare cookies at all?

A temporary cookie can approximate ordinary browser navigation, where a browser maintains state across a page, asset and link sequence. That can be informative when estimating whether detector features are robust to web-browser state. It is not required for the first privacy-first benchmark and would not be comparable with many HTTP libraries, crawlers and API SDKs that do not manage a cookie jar by default.

A cookie also expands the correlation surface. It can persist beyond the intended run, be replayed, be forwarded accidentally by a client, or become a direct identifier if logged. These risks conflict with the project rule that observations must not retain cookies, raw session values, IP addresses, query strings, Authorization, bodies or arbitrary headers. OWASP advises that session identification values should generally be removed, masked, sanitized, hashed or encrypted before logging.[1]

## Non-deployable experiment design

An experiment may be proposed only after the session-token benchmark completes and only on a separately deployed, non-production laboratory instance. It must use synthetic routes, synthetic clients and campaign-specific secrets. It must not reuse the production Worker, Railway environment, hostname, data store or secret values.

| Control | Required condition |
|---|---|
| Session value | Random 128-bit value with no encoded label, client identifier, address, User-Agent or timestamp. |
| Cookie attributes | `Secure`, `HttpOnly`, `SameSite=Strict`, path restricted to the synthetic lab, no domain widening, and a short `Max-Age`. |
| Logging | Raw `Cookie` and `Set-Cookie` values are rejected or redacted before every log sink, error report, trace and export. |
| Storage | No persistent database or client-profile linkage. Detailed events use the same short retention and verified deletion policy as the token protocol. |
| Split integrity | Cookie value, session, client pseudonym and all requests from one navigation are confined to exactly one split. |
| Evaluation | Cookie-enabled and token-enabled clients use equivalent route catalogue, methods, intervals, campaigns and labels; cookie presence is not a detector feature. |
| Shutoff | The experiment stops on any sensitive-value leak, unexpected cross-session replay, retention failure or change to the production privacy boundary. |

## Required tests before any separate experiment

The separate instance would need tests proving that a cookie is not accepted on the production route, is absent from all logs and exports, expires as configured, cannot be replayed after expiry, is restricted to the synthetic path, and never crosses a campaign boundary. It would also need a paired-browser test that compares the cookie and token variants without using cookie presence, session value, client identity or campaign marker as a model feature.

No production implementation is authorized by this document. The current regression suite's Worker test that rejects `Cookie` is the active policy control.

## References

[1]: https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html "OWASP Logging Cheat Sheet"
[2]: https://www.rfc-editor.org/rfc/rfc6265.html "RFC 6265 — HTTP State Management Mechanism"
