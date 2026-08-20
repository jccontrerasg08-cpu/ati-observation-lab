# ATI Observation Proxy

This directory contains the minimal Cloudflare Worker that forms the trusted edge in front of the Railway observation lab. It intentionally has no third-party runtime dependencies, storage, analytics, or request logging.

## Request contract

The Worker accepts only `GET` and `HEAD` requests for `/observe` without a query string or fragment. It rejects requests that include `Cookie`, `Authorization`, or `Proxy-Authorization`; it does not forward any visitor-supplied header except the optional `User-Agent` and an allowlisted opaque campaign marker.

At the Cloudflare edge, the Worker reads `CF-Connecting-IP`, derives an HMAC-SHA-256 pseudonym using a private secret, and discards the address before sending the request to Railway. It replaces any client-supplied `X-ATI-Proxy-Token` and `X-ATI-Proxy-Client-ID` with an origin token and generated pseudonym. Railway requires both values, so direct requests to its generated domain fail closed.

> The pseudonym is an operational key for a controlled-campaign rate limit, not an assertion of a visitor’s identity.

## Required secrets

Define all four values as Cloudflare Worker **secrets**. Do not place them in `wrangler.jsonc`, Git, a campaign manifest, a browser, or a log.

| Secret | Value | Rotation scope |
|---|---|---|
| `ATI_ALLOWED_CAMPAIGN_IDS` | Comma-separated allowlist of current opaque campaign IDs. | Before and after every campaign. |
| `ATI_CLIENT_PSEUDONYM_KEY` | Random secret used only by the Worker HMAC. | Every campaign or retention window. |
| `ATI_ORIGIN_URL` | Exact HTTPS Railway origin, with no path, query, or fragment. | When the Railway domain changes. |
| `ATI_PROXY_ORIGIN_TOKEN` | Random secret shared only with Railway as `ATI_TRUSTED_PROXY_TOKEN`. | Before every campaign and on suspected exposure. |

The Railway application must have the exact same value for `ATI_TRUSTED_PROXY_TOKEN`, while its `ATI_CLIENT_HASH_KEY` remains separate. No secret value is committed to the repository.

## Local verification

Use Node 22 or later. The tests use only Node’s built-in test runner.

```bash
cd cloudflare-worker
npm test
```

For local Worker development, create an untracked `.dev.vars` file with synthetic values matching the secret names. Never point a local Worker at a production Railway origin unless the corresponding campaign is explicitly authorized.

## Deployment after domain selection

1. Ensure the domain is an active Cloudflare zone and choose a dedicated subdomain such as `observe.example.com`.
2. Create the Worker from this directory in **Workers & Pages** and add the four secrets in **Settings → Variables and Secrets**.
3. Add the Custom Domain in **Settings → Domains & Routes**. Cloudflare provisions the DNS record and certificate for a subdomain in the active zone.
4. Configure the identical origin token as `ATI_TRUSTED_PROXY_TOKEN` in Railway, deploy the backend PR, then deploy this Worker.
5. Verify a direct `GET` to Railway `/observe` returns `503`. Verify `GET` and `HEAD` through the custom domain return `200` with `Cache-Control: no-store`; verify query strings, credentials, a non-allowlisted marker, and a direct Railway request all fail.
6. Start with one canary campaign cell and stop immediately on a privacy, availability, or contract failure.

To roll back, detach the Custom Domain from the Worker or restore the prior Worker version, then rotate `ATI_PROXY_ORIGIN_TOKEN` in both places. This blocks new observations but does not delete evidence; apply the campaign’s retention and verified-deletion procedure separately.

## Privacy controls

Worker observability is disabled in `wrangler.jsonc` to avoid persistent Worker logs. Cloudflare platform-level processing and provider retention remain outside the application’s control. The campaign manifest must document the provider, window, data stores, retention, and deletion evidence before traffic begins.
