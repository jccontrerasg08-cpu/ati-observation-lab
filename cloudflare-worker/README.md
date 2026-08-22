# ATI Observation Proxy

This directory contains the minimal Cloudflare Worker that forms the trusted edge in front of the Railway observation lab. It intentionally has no third-party runtime dependencies, storage, analytics, or request logging.

## Request contract

The Worker accepts only `GET` and `HEAD`, with no query string or fragment. It rejects `Cookie`, `Authorization`, and `Proxy-Authorization` before forwarding. The closed route catalogue is `/observe`, `/lab/start`, `/lab/page/landing`, `/lab/page/catalog`, `/lab/page/detail`, `/lab/assets/site.css`, `/lab/assets/pixel.svg`, and `/lab/missing`.

`/observe` supports isolated observations. The `/lab/*` protocol supports controlled multi-step navigation without cookies. A request to `/lab/start` creates a signed, opaque, 15-minute session token in `X-ATI-Lab-Session`; the client presents that token only for later `/lab/*` requests. The Worker validates it and forwards only the HMAC-derived `X-ATI-Proxy-Session-ID` to Railway. It never forwards the raw session token, cookies, visitor IP, query string, credentials, body, or arbitrary client headers.

On `workers.dev` and every hostname other than `observe.ati-observation-lab.com`, the Worker does not derive or claim a visitor identity from IP-address headers. It derives an HMAC-SHA-256 campaign scope from the allowlisted marker using a private secret and discards all visitor-address headers before sending the request to Railway.

Only on `observe.ati-observation-lab.com`, Cloudflare supplies the edge client address in `CF-Connecting-IP`; the Worker uses it solely as input to a separately domain-separated HMAC-SHA-256 pseudonym. The raw address is never forwarded, logged, returned, or used as a label or detector feature. If Cloudflare does not supply the header, the Worker falls back to the campaign scope. It replaces any client-supplied `X-ATI-Proxy-Token`, `X-ATI-Proxy-Client-ID`, and `X-ATI-Proxy-Session-ID` with private or derived context. Railway requires the token and pseudonym, so direct requests to its generated domain fail closed.

> Campaign, client, and session pseudonyms support rate limiting and grouped navigation only. They are not an assertion of visitor identity and are not inputs for ground-truth labels or detector features.

## Runtime configuration

The Worker has two **versioned non-secret variables** in `wrangler.jsonc` so Git-connected builds cannot silently remove them. Campaign markers are opaque identifiers, not secrets; changing them requires a reviewed PR.

| Type | Name | Purpose |
|---|---|---|
| Versioned variable | `ATI_ALLOWED_CAMPAIGN_IDS` | Comma-separated allowlist for the active controlled campaign. |
| Versioned variable | `ATI_ORIGIN_URL` | Exact HTTPS Railway origin, with no path, query, or fragment. |
| Cloudflare secret | `ATI_CLIENT_PSEUDONYM_KEY` | Random key for the edge campaign-scope HMAC. |
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

## Deployment and domain boundary

The Worker is attached as the Cloudflare Custom Domain `observe.ati-observation-lab.com`. Custom Domains match the exact hostname and Cloudflare manages the associated DNS record and certificate. The public Workers.dev URL remains enabled only as a non-identity-bearing fallback for controlled compatibility checks.

1. Connect the Worker to this directory in the GitHub repository. Deployments must use `wrangler.jsonc` so the two public variables remain reproducible.
2. Add the three secrets in **Settings → Variables and Secrets**. Do not use plaintext variables or commit a `.dev.vars` file.
3. Configure the identical origin token as `ATI_TRUSTED_PROXY_TOKEN` in Railway before deploying a Worker revision that needs it.
4. Verify direct `GET` to Railway `/observe` returns `503`. Verify `GET` and `HEAD` through `https://observe.ati-observation-lab.com` return `200` and `Cache-Control: no-store`; verify that two distinct Cloudflare edge addresses produce distinct pseudonyms without forwarding either address.
5. Verify that client-supplied `CF-Connecting-IP` does not alter the campaign scope on Workers.dev or any other hostname, and that query strings, credentials, cookies, a non-allowlisted marker, invalid sessions, and a direct Railway request all fail.
6. Start with one canary session and stop immediately on privacy, availability, or contract failure.

To roll back, restore the prior Worker version, then rotate `ATI_PROXY_ORIGIN_TOKEN` in both places. This blocks new observations but does not delete evidence; apply the campaign’s retention and verified-deletion procedure separately.

## Privacy controls

Worker observability is disabled in `wrangler.jsonc` to avoid persistent Worker logs. Cloudflare platform-level processing and provider retention remain outside the application’s control. The campaign manifest must document the provider, window, data stores, retention, and deletion evidence before traffic begins.
