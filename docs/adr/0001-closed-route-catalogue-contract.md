# ADR 0001: One closed route catalogue is the contract

## Status

Accepted.

## Context

Four components need to agree on which `/lab/*` routes exist and what each returns: the
Cloudflare Worker's allowlist, the FastAPI origin's content table, the executor's route
plans, and ATI's ATI-PF-2 route categories in the companion repository. Each one used to
restate the list. They drifted: the consent procedure prescribed a route that the ATI-PF-2
preflight rejects, and nothing caught it until the plan was run against the code.

## Decision

`src/observation_lab/pf2/catalogue.json` is the single versioned source for routes, expected
statuses, ATI-PF-2 categories, task branches and pacing regimes (`ati-pf2-catalogue-1`).

- The executor loads it directly to build its route plans.
- The origin keeps its content table next to the handlers that serve it, and a test asserts
  that it serves exactly the catalogue's routes with the catalogue's statuses.
- The Worker, which runs JavaScript at the edge, keeps its own allowlist literal, and a
  Python test and a Node test both assert that it equals the catalogue exactly.
- ATI pins the same route mapping and catalogue version; tests on both sides fail if either
  side changes alone.

## Consequences

- A route cannot be added, removed or recategorized in one place only: the test suite of
  whichever component was missed fails.
- The catalogue version travels with every session record, so a corpus can never mix
  sessions collected against different catalogues unnoticed.
- Changing the catalogue is a coordinated change across two repositories by design. That
  friction is the point.
