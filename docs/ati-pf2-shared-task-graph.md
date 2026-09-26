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

Once those gates pass, `ati pf2-baseline` runs the ladder: a constant-prevalence classifier first, then one L2-regularized logistic regression over the permitted families only, across a forward-chained temporal holdout, a leave-one-task-out holdout and a grouped-session holdout. Standardization, coefficients and the operating threshold come from each split's training partition, and each metric carries a session-cluster resampling interval. A split missing a class on either side is reported without metrics rather than scored.

## Collection prerequisites verified in deployment

The live perimeter and collection run recorded in [`pf2-live-perimeter-evidence.md`](pf2-live-perimeter-evidence.md) adds four prerequisites that a future collection must satisfy before it can be considered valid for fitting:

1. Confirm every declared executor family actually reaches the Worker. Cloudflare's managed browser-integrity rule answers `403` with error `1010` for the Python standard-library client's default User-Agent, so such a family would be silently absent from the corpus instead of failing visibly.
2. Group only on `session_id`. The address-derived `client_id` changed within single sessions of the run and is not a stable group key from a multi-address collecting host.
3. Read response headers case-insensitively in the executor. The origin's request-correlation header reaches clients lowercased, and a case-sensitive read loses it without error.
4. Burst within a session and idle between sessions when a diagnostic run needs sub-second pacing. A flat inter-request delay chosen to satisfy the 30-per-minute per-pseudonym limit collapses the coarse tempo features to one bin, removing a permitted feature family from the corpus.

## Matched-executor design for a fitting corpus

A corpus intended for fitting runs both cohorts through the same approved executor, `ati-lab-session`, under one campaign: `owned-domain-2026-09-26-pf2-matched-automated` for the automated cohort and `owned-domain-2026-09-26-pf2-matched-human-consented` for the consented human cohort. The cohort is the label and the pacing variant is the regime, recorded independently:

| Held equal across cohorts | Why |
|---|---|
| Executor, User-Agent and provenance bucket | A per-cohort client would make executor identity a class proxy. |
| Route plan and task menu | Every session follows the catalogue plan; the operator assigns tasks from one menu. |
| Pacing regimes H1, H2, H3 | Automated sessions follow the same regimes on a timer that humans follow by hand. |
| Collection windows | Each window holds both cohorts, so the temporal holdout compares like with like. |

The `burst` regime exists only for diagnostics and perimeter work: a consented participant cannot follow it, so a corpus in which it appears in one class only is invalid for fitting.

`ati pf2-preflight` never sees pacing variant, executor, scenario version or catalogue version, so it cannot detect this kind of confounding. `ati-lab-corpus` does: it refuses, and writes nothing, when any of those values occurs in a single target class, or when the corpus has one class. `--diagnostic` builds such a corpus anyway for inspection only. The earlier multi-family run remains the right tool for a different question — whether automated families stay distinguishable from each other and from an unseen family — and is not a fitting design for the human-versus-automated baseline.

The closed catalogue these rules refer to is `src/observation_lab/pf2/catalogue.json`, shared by the origin, the Worker, the executor and the corpus builder and pinned in ATI.
