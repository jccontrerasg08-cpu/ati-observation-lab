# ATI Controlled-Corpus Feature Contract

**Version:** `1.0`  
**Applies to:** `custom-domain-2026-08-22` and any successor corpus that explicitly adopts this contract.  
**Purpose:** Prevent privacy expansion and experimental leakage before model training or evaluation.

## Binding rules

A feature may be used only if it is listed as permitted, is computed entirely within the applicable training partition, and is documented in an experiment specification. Any new feature requires review of privacy, reidentification risk, class-proxy risk, split behavior, and an ablation plan before use.

No model, baseline, calibration stage, threshold policy, or monitoring job may ingest an identifier or a field that can directly encode the experiment condition. The absence of a field from a persisted training table does not make it permissible if it influenced feature selection, filtering, grouping, or an analyst decision using held-out data.

## Allowed feature families

| Family | Permitted derived feature examples | Transform and guardrail |
|---|---|---|
| Session navigation | Request count, closed-route category counts, transition-category counts, completion flag, duplicate-route count | Use route categories shared by every class; exclude campaign-specific route names and scenario-only resources |
| HTTP method and status | GET/HEAD proportions, status-class counts, expected-vs-observed method/status compatibility | Do not use arbitrary response headers, bodies, or unapproved routes |
| Coarsened tempo | Predefined inter-request delay bins, session duration bucket, retry-count bucket | Compute from rounded timestamps; never retain exact timestamps as a feature |
| Protocol conformance | Valid signed-session continuation count, missing-session rejection count, query/cookie/body violation count in excluded perimeter tests | Use only controlled-session outcomes; rejected perimeter tests are never training examples unless a separate threat model approves them |
| Aggregated consistency | Number of changes among approved coarse capability buckets, resource-request ratio, session sequence entropy after fixed bucketing | Do not use raw header strings or browser fingerprint surfaces; require cohort-size review for rare combinations |

## Audit-only User-Agent provenance

The trusted Worker may derive one of four coarse provenance categories in memory: `absent`, `scripted-http`, `browser-like`, or `other`. It discards the raw User-Agent before the request reaches Railway; the origin accepts only the fixed category from the authenticated Worker. `ua_provenance_bucket` is retained solely for aggregate corpus-composition reporting and is prohibited from feature construction, filtering, preprocessing, feature selection, calibration, threshold selection, model evaluation, drift scoring, and any analyst decision intended to improve a score.

## Prohibited fields and proxies

The following are prohibited from feature extraction, filtering, feature selection, calibration, threshold selection, drift alerting, or analyst review intended to improve model score:

| Category | Examples |
|---|---|
| Direct identifiers | Raw IP address, IP prefix, geolocation, account ID, participant name, email, device ID, request ID, client pseudonym, session pseudonym, signed session token |
| Tracking and payload data | Cookies, query strings, Authorization, arbitrary request headers, request/response bodies, prompts, tool calls, uploaded content |
| Browser or device fingerprinting | Canvas/WebGL/audio results, font or plugin lists, screen dimensions, GPU, timezone, language stack, hardware concurrency, high-entropy client hints |
| Experiment labels and aliases | Campaign marker, family name, provider name, scenario ID, executor host, participant identity, source repository, version label if unique to a class |
| High-resolution indirect identifiers | Exact timestamp, exact delay vector, full User-Agent, TLS fingerprint, request ordering unique to one class, rare categorical values that identify a session |
| Audit-only provenance metadata | `ua_provenance_bucket`; it may describe corpus composition but cannot enter any model or score-selection workflow |

## Split firewall

The following fields may be retained locally for split construction or audit only: opaque session pseudonym, coarse collection time, family, scenario, executor-version record, and local consent record. They must be removed before feature construction and unavailable to estimators, scalers, imputers, calibrators, threshold search, feature selection, and drift scoring.

| Activity | Permitted metadata | Prohibited use |
|---|---|---|
| Group split | Opaque session pseudonym | Adding it to the model or deriving a stable target encoding |
| Temporal holdout | Coarse collection time | Selecting a threshold after viewing the final holdout |
| Family/scenario holdout | Family and scenario label | Learning family/specific routes or encoding the label as a feature |
| Label join | Opaque request ID | Using request ID as a feature, row sort signal, or leakage key |
| Quality audit | Local executor version and scenario version | Training on a version-specific artifact without leave-version-out testing |

## Required preflight checks

Before an experiment runs, the evaluator must produce a machine-readable feature inventory and a negative assertion that the prohibited fields are absent. It must report session overlap across every split, feature cardinality, missingness, cohort counts, and the output of an ablation that removes each allowed feature family. A run fails closed if it finds a prohibited column, duplicated request ID, session overlap, unapproved scenario, or a class present in only one split.

## Baseline ladder

The first baseline is a non-model constant classifier that reports the observed class prevalence. The first learnable model is a regularized logistic regression with the permitted feature families only. Any more complex model must beat the baseline on the final temporal holdout and the held-out family/scenario tests with session-cluster uncertainty intervals, while preserving or improving the predeclared false-positive operating point.

## Change log

| Version | Change | Approval requirement |
|---|---|---|
| 1.0 | Initial controlled-corpus feature firewall | Review before first model run |
