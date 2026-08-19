# ATI Observation Lab

This repository is a **separate, privacy-first FastAPI laboratory** for a controlled AI traffic campaign. It is intentionally not a production site and has no database, account system, form handling, background job, analytics SDK, or persistent volume.

## What it records

The laboratory serves only `GET` and `HEAD` observation traffic. For every accepted observation it emits one JSONL record to standard output and, when `ATI_LOG_PATH` is set, to a local file. The record is compatible with `agent-traffic-intelligence` JSONL input and includes only:

| Field | Purpose |
|---|---|
| `time_iso8601` | Time of the accepted request. |
| `client_id` | Keyed BLAKE2b pseudonym of the immediate network peer. |
| `request_method`, `request_uri`, `status`, `body_bytes_sent` | Request metadata; the URI is always path-only. |
| `server_protocol`, `http_user_agent` | Protocol and truncated User-Agent. |
| `ati_campaign_id` | Optional controlled marker only when `X-ATI-Experiment-ID` matches the strict opaque-marker format. |

It never writes raw IP addresses, query strings, cookies, `Authorization`, request bodies, arbitrary headers, or invalid campaign markers. Health checks and rejected non-`GET`/`HEAD` methods are not logged. The Railway start command also disables Uvicorn access logs, because their default request lines can include full query strings.

> The lab deliberately does not trust forwarded-address headers. Depending on the hosting platform, `client_id` can represent the platform proxy rather than the ultimate visitor. This is safe for a first controlled marker campaign; do not treat it as external identity verification.

## Local verification

Create a local virtual environment and run the checks:

```bash
uv sync --extra dev
uv run pytest -q
uv run ruff check .
```

For a local smoke test, set a private local key and run the server:

```bash
export ATI_CLIENT_HASH_KEY="replace-with-a-long-local-secret"
export ATI_LOG_PATH="access.jsonl"
uv run uvicorn observation_lab.app:app --host 127.0.0.1 --port 8000
```

Then make an authorized request to `http://127.0.0.1:8000/observe` with a non-secret `X-ATI-Experiment-ID` value. Keep `access.jsonl` outside Git.

## Railway deployment checklist

The repository contains `railway.toml` but does not select or create any Railway environment. After you choose an isolated Railway project, deploy this repository and configure exactly these variables:

| Variable | Required | Example |
|---|---:|---|
| `ATI_CLIENT_HASH_KEY` | Yes | A unique long random secret held only in Railway. |
| `ATI_RATE_LIMIT_PER_MINUTE` | Yes | `30` for a controlled campaign. |
| `ATI_LOG_PATH` | No | Leave unset on Railway; use captured standard-output logs. |

Railway must expose the generated domain publicly. Do not add login, CAPTCHA, or application forms for the first controlled campaign. Do not connect a production database or reuse production secrets.

## First controlled campaign

1. Choose an opaque marker such as `owned-shadow-2026-08-19-a`; it must not be a token, email, account ID, or secret.
2. Tell the authorized agent to visit only `/observe` or `/`, at an agreed rate, with `X-ATI-Experiment-ID` set to that marker.
3. Export the JSONL observation lines from Railway logs into a local `access.jsonl` file.
4. Use the merged `agent-traffic-intelligence` feature to produce labels and evaluate the run:

```bash
export ATI_HASH_KEY="the-local-analysis-key"
ati campaign labels access.jsonl \
  --campaign-id "owned-shadow-2026-08-19-a" \
  --corpus-id "owned-shadow-2026-08" \
  --output labels.jsonl
```

Follow the existing controlled-observation guide in `agent-traffic-intelligence` for the manifest and `ati run` steps. Stop the Railway service after collecting the agreed window of observations.
