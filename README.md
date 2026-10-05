# ATI Observation Lab

[![CI](https://github.com/jccontrerasg08-cpu/ati-observation-lab/actions/workflows/ci.yml/badge.svg)](https://github.com/jccontrerasg08-cpu/ati-observation-lab/actions/workflows/ci.yml)
![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)
![Edge: Cloudflare Workers](https://img.shields.io/badge/edge-Cloudflare%20Workers-orange)
![Origin: FastAPI on Railway](https://img.shields.io/badge/origin-FastAPI%20on%20Railway-purple)

## At a glance

| | |
|---|---|
| **What** | A deliberately small website, visited only under controlled, labelled conditions, that produces privacy-safe ground truth for [Agent Traffic Intelligence](https://github.com/jccontrerasg08-cpu/agent-traffic-intelligence). |
| **How** | A Cloudflare Worker gates a closed route catalogue, issues HMAC-signed campaign-bound sessions and forwards only opaque pseudonyms; the FastAPI origin refuses anything the Worker did not vouch for and logs pseudonymized JSONL. |
| **Tooling** | `ati-lab-session` runs one labelled session, `ati-lab-corpus` turns sessions and an origin export into a corpus (refusing class-confounded ones), `ati-lab-perimeter` checks production after each deploy. |
| **Evidence** | 22/22 live perimeter checks; 110 Python and 23 Worker tests; one route catalogue held equal across Worker, origin, executor and ATI by tests. |
| **Read next** | [Decision records](docs/README.md#decisions) · [Documentation map](docs/README.md) · [Case study](https://github.com/jccontrerasg08-cpu/agent-traffic-intelligence/blob/main/docs/case-study.md) |

## What this repository is

This repository is a **separate, privacy-first FastAPI laboratory** for controlled AI traffic campaigns. It is intentionally not a production site and has no database, account system, form handling, background job, analytics SDK, persistent volume, or cookie-based session handling.

## Trust boundary and recorded data

The application accepts observations only from a configured trusted proxy. Only at `observe.ati-observation-lab.com`, the Cloudflare Worker derives an opaque HMAC scope from the edge client address in `CF-Connecting-IP`; it sends only that HMAC-derived scope with a private origin token, never the raw address. On Workers.dev and every other hostname, the Worker derives the opaque **campaign scope** from the allowlisted marker instead. For controlled `/lab/*` navigation, the Worker additionally derives an opaque session pseudonym bound to that same campaign and forwards it as `X-ATI-Proxy-Session-ID`; the raw session token is never sent to Railway. The application rejects direct requests and invalid proxy context with `503`; invalid or missing laboratory session context receives `403`. The application itself never falls back to `CF-Connecting-IP`, `X-Forwarded-For`, `X-Real-IP`, the immediate Railway peer, a cookie, or a client-supplied proxy session identifier.

The laboratory serves only `GET` and `HEAD` observation traffic. For every accepted observation it emits one JSONL record to standard output and, when `ATI_LOG_PATH` is set, to a local file. The record is compatible with `agent-traffic-intelligence` JSONL input and includes only:

| Field | Purpose |
|---|---|
| `request_id` | Fresh random 128-bit opaque identifier returned only in `X-ATI-Request-ID` for the controlled executor to correlate a local observation with its local ground-truth label. It is not an authentication credential, client identifier, or IP address. |
| `time_iso8601` | Time of the accepted request. |
| `client_id` | Keyed BLAKE2b pseudonym of the opaque scope generated at the trusted edge. It is derived from the campaign scope on Workers.dev and all other hosts; at `observe.ati-observation-lab.com` it is a second-layer pseudonym of the edge address scope. It never contains a raw address or direct client identifier. |
| `session_id` | Optional edge-derived HMAC for a single `/lab/*` navigation session; it is absent for isolated `/observe`. |
| `request_method`, `request_uri`, `status`, `body_bytes_sent` | Request metadata; the URI is always path-only and belongs to the closed route catalogue. |
| `server_protocol`, `ua_provenance_bucket` | Protocol plus one edge-derived coarse User-Agent provenance category: `absent`, `scripted-http`, `browser-like`, or `other`. The Worker never forwards raw User-Agent text to Railway. This audit-only category is excluded from every model workflow. |
| `ati_campaign_id` | Optional controlled marker only when `X-ATI-Experiment-ID` matches the strict opaque-marker format. |

It never writes raw IP addresses, raw session tokens, query strings, cookies, `Authorization`, request bodies, arbitrary headers, raw User-Agent text, proxy tokens, or invalid campaign markers. Health checks and rejected methods are not logged. The Railway start command also disables Uvicorn access logs, because their default request lines can include full query strings.

> On `workers.dev`, the edge pseudonyms support campaign-wide rate limiting and grouped evaluation only. At `observe.ati-observation-lab.com`, the address-derived edge pseudonym can support a campaign-approved per-pseudonym limit, but it is still not a label or an assertion of identity, device, network, or intent. A campaign marker proves only that a request belongs to an authorized experiment.

## Controlled navigation catalogue

| Route | Methods | Purpose |
|---|---|---|
| `/observe` | GET, HEAD | Isolated observation retained for compatibility. |
| `/lab/start` | GET, HEAD | Starts a signed, 15-minute, cookie-free session. The Worker returns its opaque token only in `X-ATI-Lab-Session`. |
| `/lab/page/landing`, `/lab/page/catalog` | GET, HEAD | Shared static pages for each controlled task. |
| `/lab/page/detail`, `/lab/page/related`, `/lab/complete` | GET, HEAD | Two task branches and their shared completion page. |
| `/lab/assets/site.css`, `/lab/assets/pixel.svg` | GET, HEAD | Static local assets with no external dependencies. |
| `/lab/missing` | GET, HEAD | Deterministic controlled `404`. |

The Worker rejects query strings, fragments, cookies, `Authorization`, `Proxy-Authorization`, bodies and methods other than GET/HEAD before reaching the laboratory. The laboratory repeats the query, cookie, catalogue and session checks as defense in depth. GET and HEAD have equivalent status and representation metadata; HEAD has no response body.

## Local verification

Create a local virtual environment and run the checks:

```bash
uv sync --extra dev
uv run pytest -q
uv run ruff check .
```

For a local smoke test, set private local keys and run the server. The client and session context below are synthetic test values; they are generated by the Cloudflare Worker in deployment.

```bash
export ATI_CLIENT_HASH_KEY="replace-with-a-long-local-secret"
export ATI_TRUSTED_PROXY_TOKEN="replace-with-a-separate-long-local-secret"
export ATI_LOG_PATH="access.jsonl"
uv run uvicorn observation_lab.app:app --host 127.0.0.1 --port 8000
```

Then make a local request with matching `X-ATI-Proxy-Token`, a synthetic `X-ATI-Proxy-Client-ID` in `hmac-sha256:<64-lowercase-hex>` format and, for `/lab/*`, a synthetic `X-ATI-Proxy-Session-ID` in the same format. Keep `access.jsonl` outside Git.

## Railway deployment checklist

The repository contains `railway.toml` but does not select or create any Railway environment. After you choose an isolated Railway project, deploy this repository and configure exactly these variables:

| Variable | Required | Purpose |
|---|---:|---|
| `ATI_CLIENT_HASH_KEY` | Yes | Unique long random secret held only in Railway to derive the exported pseudonym from the opaque scope supplied by the trusted edge. |
| `ATI_TRUSTED_PROXY_TOKEN` | Yes | Separate long random secret shared only with the trusted edge proxy. |
| `ATI_RATE_LIMIT_PER_MINUTE` | Yes | `30` or another campaign-approved per-pseudonym limit. |
| `ATI_LOG_PATH` | No | Leave unset on Railway; use captured standard-output logs. |

The proxy protects the Custom Domain `observe.ati-observation-lab.com` and uses the shared token only in its proxy-to-Railway request. Do not expose that token to visitors, source control, logs, error reports, or campaign manifests. The Railway-generated domain remains an origin endpoint and is expected to reject direct observation attempts. Workers.dev intentionally has no trusted per-client identity; only the exact Custom Domain may derive its opaque address scope. Do not add login, CAPTCHA, application forms, a production database, reused production secrets, cookies, or persistence for laboratory sessions.

## Campaign and evaluation protocol

The approved Custom Domain matrix, opaque markers, session sequence, acceptance checks, and corpus exclusions are defined in [the versioned campaign matrix](docs/custom-domain-campaign-matrix.md). Do not reuse the legacy Workers.dev pilot marker for this corpus.

1. Configure and test the trusted edge proxy before opening a campaign.
2. Choose opaque markers that are not tokens, email addresses, account IDs or secrets. The marker is for local ground truth only and must not become a detector feature.
3. Start each navigation session at `/lab/start` through the Worker hostname with one allowlisted opaque marker, then execute a manifest-defined sequence across the closed catalogue with that same marker. Carry `X-ATI-Lab-Session` only in that session’s later `/lab/*` requests; do not put it in a cookie or a URL.
4. Export only the approved JSONL fields from Railway logs into a local corpus. Group every split by `session_id` when present; no session may appear in more than one train, validation or holdout split.
5. Use `ati campaign labels` to create local labels, then evaluate temporal, session-grouped and unseen-family holdouts. Report FPR, FNR, recall, PR-AUC, Brier score and ECE with denominators and uncertainty, and do not tune a threshold against the final holdout.
6. Stop after the approved window, redact exports, and follow the manifest’s retention and verified-deletion procedure.

The existing controlled-observation guide in `agent-traffic-intelligence` remains the source of truth for manifests and `ati run` invocation. Do not describe a pilot or conformance run as evidence of model generalization.

## Running an ATI-PF-2 collection end to end

`pip install -e .` installs three commands. Each fails closed rather than guessing, and
nothing leaves your machine except the controlled requests themselves.

| Command | Purpose |
|---|---|
| `ati-lab-session` | Runs one session through the edge. The same executor serves both cohorts. |
| `ati-lab-corpus` | Reconciles session records with an origin export into ATI's preflight inputs. |
| `ati-lab-perimeter` | Live conformance checks against production. Opt-in, never in CI. |

### Matched-executor design

A fitting corpus runs **both cohorts through `ati-lab-session`**, with the same route plan,
the same task menu and the same pacing regimes. The executor, its User-Agent, its header
handling and every regime are then shared by both classes, so the only thing left to
differ is who decides when each request happens — the behavior being measured. The
cohort is the label and the pacing variant is the regime; they are independent inputs.

```bash
# 1. One session per invocation. Assign tasks, regimes and windows so that every value
#    appears in both cohorts. The human cohort requires a consent record first and always
#    runs interactively; the automated cohort follows the same H regimes on a timer.
ati-lab-session --cohort automated \
  --marker owned-domain-2026-09-26-pf2-matched-automated \
  --task task-detail --pacing-variant H2 --collection-window 2026-09-27-block-1 \
  --output ./local/sessions/automated-001.json

ati-lab-session --cohort human-consented --participant p01 \
  --marker owned-domain-2026-09-26-pf2-matched-human-consented \
  --task task-detail --pacing-variant H2 --collection-window 2026-09-27-block-1 \
  --output ./local/sessions/human-001.json

# 2. Export the privacy-safe rows from the origin's captured output into one JSONL
#    (Railway dashboard or CLI). Keep it outside Git.

# 3. Reconcile by opaque request identifier. This refuses a corpus that is not
#    fitting-ready and writes nothing; --diagnostic writes it anyway for inspection.
ati-lab-corpus --session-dir ./local/sessions --exported ./local/exported.jsonl \
  --output-dir ./local/corpus

# 4. Hand the local inputs to ATI.
ati pf2-preflight ./local/corpus/access.jsonl \
  --labels-by-session ./local/corpus/labels-by-session.json \
  --tasks-by-session ./local/corpus/tasks-by-session.json \
  --collection-windows-by-session ./local/corpus/collection-windows.json \
  --groups-by-session ./local/corpus/groups-by-session.json \
  --model-output model.jsonl --split-output splits.jsonl \
  --preflight-output preflight.json
ati pf2-baseline model.jsonl --split-manifest splits.jsonl --output baseline.json \
  --target-false-positive-rate 0.05
```

`ati-lab-corpus` checks what ATI cannot see. Pacing variant, executor, scenario version
and catalogue version never reach ATI, so only this step can detect that one of them
occurs in a single target class — which makes a corpus invalid for fitting because that
value alone would separate the classes. The `burst` regime is therefore for diagnostics
and perimeter work only: a consented participant cannot follow it.

Each consented session also carries an operator-assigned participant code such as `p01`,
never a name. The corpus builder writes it to `groups-by-session.json`, and ATI keeps every
participant's sessions on one side of every split. Otherwise a model could be scored on
recognizing a person it was trained on. A consented cohort with an uncoded session, or
with fewer than two participants, is refused for fitting.

### One closed catalogue

[`src/observation_lab/pf2/catalogue.json`](src/observation_lab/pf2/catalogue.json) is the
single source of truth for the `/lab/*` routes, their statuses, their ATI-PF-2 categories,
the task branches and the pacing regimes. Tests hold the origin application, the Worker,
the executor and the corpus builder to it, and `agent-traffic-intelligence` pins the same
category mapping and version. A route changes there, with every consumer, in one review.

### Checks

```bash
make check       # lint, Python tests, Worker tests — exactly what CI runs
make perimeter   # live conformance against production; run after every deploy
```

The deployed perimeter and one multi-family collection run are recorded in
[the live perimeter evidence](docs/pf2-live-perimeter-evidence.md), including why the
executor must be verified as reachable before each campaign, why grouping keys only on
`session_id`, and why response headers are read case-insensitively.

