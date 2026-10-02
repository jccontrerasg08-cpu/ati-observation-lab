# Documentation map

## Start here

- [README](../README.md): what the laboratory is, its trust boundary and what it records.
- [Case study](https://github.com/jccontrerasg08-cpu/agent-traffic-intelligence/blob/main/docs/case-study.md)
  (in the companion ATI repository): the problem, the design and what the evidence shows.

## Decisions

| ADR | Decision |
|---|---|
| [0001](adr/0001-closed-route-catalogue-contract.md) | One closed route catalogue is the contract |
| [0002](adr/0002-matched-executor-design.md) | The matched-executor design |
| [0003](adr/0003-edge-vouches-for-origin.md) | The edge vouches for every observation |

## Protocol

| Document | Scope |
|---|---|
| [ATI-PF-2 shared task graph](ati-pf2-shared-task-graph.md) | Tasks, branches and pacing regimes both cohorts follow. |
| [Feature contract](feature-contract.md) | What may and may not become a model feature. |
| [Human control consent](human-control-consent.md) | How a consented participant joins the human cohort. |
| [Corpus datasheet](custom-domain-corpus-datasheet.md) | Provenance, labelling, retention and known biases of the corpus. |
| [Cookie variant boundary](cookie-experiment-boundary.md) | Why cookie sessions stay a research variant. |

## Evidence

- [ATI-PF-2 live perimeter and collection evidence](pf2-live-perimeter-evidence.md):
  22-point perimeter conformance, a 24-session live run, and the findings that changed the
  protocol.

## History

- [Custom-domain campaign matrix](custom-domain-campaign-matrix.md): the pre-ATI-PF-2
  campaign plan, kept for traceability.
