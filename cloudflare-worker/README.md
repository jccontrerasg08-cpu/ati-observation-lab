# ATI Observation Proxy

This directory contains the minimal Cloudflare Worker that forms the trusted edge in front of the Railway observation lab. It intentionally has no third-party runtime dependencies, storage, analytics, or request logging.

## Request contract

The Worker accepts only `GET` and `HEAD`, with no query string or fragment. It rejects `Cookie`, `Authorization`, and `Proxy-Authorization` before forwarding. The closed route catalogue is `/observe`, `/lab/start`, `/lab/page/landing`, `/lab/page/catalog`, `/lab/page/detail`, `/lab/assets/site.css`, `/lab/assets/pixel.svg`, and `/lab/missing`.

`/observe` supports isolated observations. The `/lab/*` protocol supports controlled multi-step navigation without cookies. A request to `/lab/start` creates a signed, opaque, 15-minute session token in `X-ATI-Lab-Session`; the client presents that token only for later `/lab/*` requests. The Worker validates it and forwards only the HMAC-derived `X-ATI-Proxy-Session-ID` to Railway. It never forwards the raw session token, cookies, visitor IP, query string, credentials, body, or arbitrary client headers.

At the Cloudflare edge, the Worker reads `CF-Connecting-IP`, derives an HMAC-SHA-256 client pseudonym using a private secret, and discards the address before sending the request to Railway. It replaces any client-supplied `X-ATI-Proxy-Token`, `X-ATI-Proxy-Client-ID`, and `X-ATI-Proxy-Session-ID` with private or derived context. Railway requires the token and client pseudonym, so direct requests to its generated domain fail closed.

> Client and session pseudonyms support rate limiting and experiment grouping only. They are not an assertion of visitor identity and are not inputs for ground-truth labels or detector features.

## Runtime configuration

The Worker has two **versioned non-secret variables** in `wrangler.jsonc` so Git-connected builds cannot silently remove them. Campaign markers are opaque identifiers, not secrets; changing them requires a reviewed PR.

| Type | Name | Purpose |
|---|---|---|
| Versioned variable | `ATI_ALLOWED_CAMPAIGN_IDS` | Comma-separated allowlist for the active controlled campaign. |
| Versioned variable | `ATI_ORIGIN_URL` | Exact HTTPS Railway origin, with no path, query, or fragment. |
| Cloudflare secret | `ATI_CLIENT_PSEUDONYM_KEY` | Random key for the edge client HMAC. |
| Cloudflare secret | `ATI_PROXY_ORIGIN_TOKEN` | Random token shared only with Railway as `ATI_TRUSTED_PROXY_TOKEN`. |
| Cloudflare secret | `ATI_SESSION_SIGNING_KEY` | Random key that signs and validates the opaque laboratory session token. |

No secret value belongs in Git, a campaign manifest, browser-visible content, or a log. `ATI_SESSION_SIGNING_KEY` is independent from both other Worker secrets. Railway retains only `ATI_CLIENT_HASH_KEY`, `ATI_TRUSTED_PROXY_TOKEN`, and `ATI_RATE_LIMIT_PER_MINUTE`.

## Local verification

Use Node 22 or later. The tests use only Node’s built-in test runner.

```bash
cd cloudflare-worker
npm test
```

For local Worker development, create an untracked `.dev.vars` file with synthetic values matching all three secret names and both non-secret variables. Never point a local Worker at a production Railway origin unless the matching campaign is explicitly authorized.

## Deployment on Workers.dev

This account currently has no active Cloudflare zone, so the no-cost deployment uses the public Workers.dev route. Cloudflare documents Workers.dev for personal or hobby projects; migrate to a Custom Domain before treating the service as business-critical.

1. In **Workers & Pages**, configure the account-level `workers.dev` subdomain if Cloudflare prompts for one.
2. Connect the Worker to this directory in the GitHub repository. Deployments must use `wrangler.jsonc` so the two public variables remain reproducible.
3. Add the three secrets in **Settings → Variables and Secrets**. Do not use plaintext variables or commit a `.dev.vars` file.
4. Configure the identical origin token as `ATI_TRUSTED_PROXY_TOKEN` in Railway before deploying a Worker revision that needs it.
5. Verify direct `GET` to Railway `/observe` returns `503`. Verify `GET` and `HEAD` through Workers.dev return `200` and `Cache-Control: no-store`; verify query strings, credentials, cookies, a non-allowlisted marker, invalid sessions, and a direct Railway request all fail.
6. Start with one canary session and stop immediately on privacy, availability, or contract failure.

To roll back, restore the prior Worker version, then rotate `ATI_PROXY_ORIGIN_TOKEN` in both places. This blocks new observations but does not delete evidence; apply the campaign’s retention and verified-deletion procedure separately.

## Privacy controls

Worker observability is disabled in `wrangler.jsonc` to avoid persistent Worker logs. Cloudflare platform-level processing and provider retention remain outside the application’s control. The campaign manifest must document the provider, window, data stores, retention, and deletion evidence before traffic begins.
