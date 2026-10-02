# ATI-PF-2 Corpus Datasheet

Structured after Gebru et al., *Datasheets for Datasets*, Communications of the ACM
64(12), 2021, [doi:10.1145/3458723](https://doi.org/10.1145/3458723). It answers the
paper's seven groups of questions for the corpus that ATI-PF-2 fits and evaluates on.

| | |
|---|---|
| **Corpus** | ATI-PF-2 matched corpus |
| **Route catalogue** | `ati-pf2-catalogue-1` ([`catalogue.json`](../src/observation_lab/pf2/catalogue.json)) |
| **Campaign markers** | `owned-domain-2026-09-26-pf2-matched-automated` and `owned-domain-2026-09-26-pf2-matched-human-consented` |
| **Feature contract** | [`1.0`](feature-contract.md) |
| **Status** | **Not yet collected for fitting.** The automated cohort can run at any time. The consented human cohort waits on participants, which is a person's decision, not a code change. A 24-session automated-only diagnostic run exists, and ATI's preflight refused it as one-class, as designed ([evidence](pf2-live-perimeter-evidence.md)). |

The earlier [custom-domain corpus datasheet](custom-domain-corpus-datasheet.md) governs the
pre-PF-2 six-request integrity scenario and is kept for history.

## 1. Motivation

**Why was the corpus created?** To test one question under controlled conditions: whether
coarse, privacy-preserving session behaviour (navigation categories, method and status
counts, binned tempo) separates consented people from automation that follows the *same*
route plan, tasks and pacing. Without such a corpus, an evaluation cannot tell signal apart
from artefacts of how the classes were collected.

**Who created it?** The laboratory operator, using this repository and the companion
[ATI](https://github.com/jccontrerasg08-cpu/agent-traffic-intelligence) repository.

## 2. Composition

**What does an instance represent?** One complete controlled session: a path through the
closed route graph, from `/lab/start` through a catalogue page, one of two task branches
(`detail` or `related`), and `/lab/complete`, with optional asset requests. Each request
in it is one row.

**What does each row contain?** Only the five fields the ATI preflight reads:
`session_id` (an HMAC-SHA256 pseudonym derived by the proxy), `request_uri` (a closed
catalogue path), `request_method` (`GET` or `HEAD`), `status`, and `time_iso8601`. The
corpus builder copies nothing else.

**What is the label?** The cohort recorded by the executor *before* the session runs:
`automated` or `human-consented`. Nothing infers a label from a route, a pacing pattern, a
User-Agent or a provenance bucket.

**Is any information missing, and is the corpus self-contained?** A session is excluded,
and counted, when any of its rows is missing from the export or ambiguous. It is never
repaired. The corpus is self-contained: it references no external resource.

**Does it contain data that identifies people, or that is sensitive?** No raw IP address,
prefix, geolocation, cookie, query string, body, Authorization value, full User-Agent,
fingerprint surface, mouse or keystroke data, or participant identity. The session
pseudonym is keyed and cannot be reversed without the proxy's secret. The full exclusion
list is in the [feature contract](feature-contract.md#prohibited-fields-and-proxies).

**Target size.** The ATI preflight requires at least 8 complete sessions for every
task-by-class cell by default, which means at least 32 sessions across two tasks and two
classes. That is enough to exercise the splits honestly, not to estimate population rates.

## 3. Collection process

**How was the data acquired?** Both cohorts run through one executor, `ati-lab-session`
([`executor.py`](../src/observation_lab/pf2/executor.py)), against the production edge:

1. The Cloudflare Worker admits only the closed catalogue, requires an allowlisted
   campaign marker, issues a signed session at `/lab/start` bound to that campaign, and
   forwards a coarse User-Agent bucket in place of the User-Agent itself.
2. The FastAPI origin refuses any request the Worker did not vouch for and writes
   pseudonymized JSONL.
3. Each response carries a fresh random `X-ATI-Request-ID`. The executor records it
   next to its own label, and that identifier is the only link between label and row.

**What is held equal across cohorts?** The executor and its User-Agent, the route plan and
task menu, the pacing regimes H1, H2 and H3, and the collection windows
([matched-executor design](ati-pf2-shared-task-graph.md#matched-executor-design-for-a-fitting-corpus),
[ADR 0002](adr/0002-matched-executor-design.md)). The `burst` regime exists for diagnostics
only, because a person cannot follow it.

**Who was involved, and was consent obtained?** Automated sessions are run by the
operator. Human sessions require the affirmative, revocable consent recorded under
[human-control consent](human-control-consent.md) *before* the marker is used. Unmarked
public traffic is never a human control.

**Ethical review.** This is an individual research project with no institutional review
board. The consent procedure, data minimization and the purpose limits below stand in for
one, and a participant may stop at any point.

## 4. Preprocessing, cleaning and labelling

`ati-lab-corpus` ([`corpus.py`](../src/observation_lab/pf2/corpus.py)) joins labels to
exported rows by request identifier. It fails a session closed when:

- an identifier is missing from the export or matches more than one row;
- the rows span more than one session pseudonym;
- a row is outside the catalogue;
- a row disagrees with the local record on path, method or status.

It refuses the whole corpus, and writes nothing, when the executor, pacing variant,
scenario version or catalogue version occurs in one class only, or when there is a single
class. Those fields never reach ATI, so only this step can catch them.

ATI's `ati pf2-preflight` then derives fixed-vocabulary aggregates and discards exact
timestamps. Session pseudonyms, tasks and windows go to a separate split manifest that no
estimator sees ([ATI ADR 0007](https://github.com/jccontrerasg08-cpu/agent-traffic-intelligence/blob/main/docs/adr/0007-pf2-feature-firewall.md)).
Local label files and raw exports stay in the access-controlled workspace for the research
period (see [Maintenance](#7-maintenance)), so every step can be re-run.

## 5. Uses

**Intended use.** Offline evaluation of the ATI-PF-2 baseline ladder: a constant baseline,
then L2-regularized logistic regression, across temporal, leave-one-task-out and
grouped-session holdouts with session-resampled intervals.

**What must it not be used for?** Identifying a person, inferring an AI provider,
eligibility decisions, automatic blocking, training a cross-site identity system, or being
presented as a benchmark for AI agents, automation or human traffic in general.

**What could make results misleading?** The corpus is small, synthetic in its routes and
collected from few hosts. A result says how these cohorts behaved on this site under these
rules. It says nothing about the public internet, population false-positive rates,
calibration or an operating threshold.

## 6. Distribution

Raw rows, label files and split manifests are **not distributed**. What leaves the
workspace is this datasheet, aggregate evidence documents, and the aggregate-only warehouse
export, which holds per-run metrics and per-class feature aggregates, never per-session rows
([ATI ADR 0008](https://github.com/jccontrerasg08-cpu/agent-traffic-intelligence/blob/main/docs/adr/0008-aggregate-only-warehouse-export.md)).

## 7. Maintenance

**Who maintains it?** The laboratory operator.

**How does it change?** Through versions, never in place. A route change means a new
catalogue version, which tests hold the Worker, origin, executor, corpus builder and ATI to
([ADR 0001](adr/0001-closed-route-catalogue-contract.md)). A feature change means a new
feature-contract version. Earlier corpora stay tied to the versions they were collected
under.

**Retention and deletion.** Raw campaign artifacts are kept only in the access-controlled
workspace for the research period and then deleted under the verified-deletion procedure.
A deletion record keeps the corpus version, aggregate counts, date and verification
outcome, and never request identifiers or session tokens.
