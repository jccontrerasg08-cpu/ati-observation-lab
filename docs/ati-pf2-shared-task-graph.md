# ATI-PF-2 Shared Task Graph

ATI-PF-2 is a **controlled, consent-based collection protocol** for future evaluation of privacy-preserving session features. It does not classify public visitors, infer human status from unmarked traffic, or authorize model training by itself.

## Purpose

The former six-request route sequence remains a protocol-integrity scenario. It is not sufficient for a learnable behavioral baseline because every permitted aggregate is constant. ATI-PF-2 introduces a small, shared route graph so controlled sessions can vary in navigation while retaining the same origin, proxy boundary, signed-session mechanism, and data-minimization rules.

## Allowed routes

| Route | Route category | Intended role |
|---|---|---|
| `/lab/start` | `start` | Creates an opaque signed lab session. |
| `/lab/page/landing` | `landing` | Shared entry page. |
| `/lab/page/catalog` | `catalog` | Shared branch point. |
| `/lab/page/detail` | `detail` | One valid branch toward completion. |
| `/lab/page/related` | `related` | A second valid branch toward completion. |
| `/lab/complete` | `complete` | Shared terminal page. |
| `/lab/assets/site.css`, `/lab/assets/pixel.svg` | `asset` | Browser-resource category only. |
| `/lab/missing` | `missing` | Closed error-path integrity control; excluded unless a future reviewed protocol admits it. |

All `/lab/*` routes accept only `GET` or `HEAD`, reject queries, cookies and sensitive headers, and require the proxy-derived opaque session pseudonym. The Worker issues a signed token only at `/lab/start`, transforms it to a proxy session pseudonym for the origin, and never forwards the signed token to the origin.

## Collection controls

The task menu, branch availability and any coarse pacing regime must be made available to both explicitly labeled cohorts. Campaign marker, task assignment, family, executor version, deployment provenance, consent record and coarse collection order are local audit/split metadata only. They are unavailable to feature construction, preprocessing, fitting, calibration, threshold selection and drift scoring.

A future collection is invalid for model fitting when a task, scenario, route category, executor version or pacing regime occurs in one target class only. Human-assisted controls require affirmative voluntary consent; unmarked public traffic is never a human control.

## Permitted model aggregates

The companion ATI preflight derives only fixed-vocabulary session aggregates: route-category counts, category-transition counts, GET/HEAD count, 2xx/4xx counts, completion, duplicate category count, four predeclared delay-bin counts and a four-level duration bucket. Exact timestamps are used only in memory to derive bins and are discarded before the model table is emitted.

The preflight emits two separate local artifacts: a model table with target plus allowed aggregates, and a split manifest with opaque session pseudonym and audit-only task label. The split manifest must never be supplied to an estimator.

## Explicit exclusions

No raw IP address, IP prefix, geolocation, full User-Agent, `ua_provenance_bucket`, cookies, query string, Authorization, body, arbitrary headers, request ID, client or session pseudonym, signed session token, account/participant identity, exact timestamp, exact delay vector, browser/device/TLS fingerprint, screen property, mouse trajectory, click coordinates, scroll trace or keystroke data is a model feature.

## Evaluation gate

A baseline is permitted only after the preflight reports both target classes, shared task coverage, the predeclared minimum sessions for every task×class cell, at least one varying permitted feature, and a separate session-level split manifest. These gates establish collection readiness—not generalization, population FPR, calibration or an operational threshold.
