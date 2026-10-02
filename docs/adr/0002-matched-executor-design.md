# ADR 0002: The matched-executor design

## Status

Accepted.

## Context

The goal is to measure whether session behaviour alone separates people from paced
automation. Any difference between the cohorts other than *who decides when each request
happens* lets a classifier learn that difference instead, and then report a perfect score
for the wrong reason. Candidate differences include the HTTP client, the User-Agent, header
handling, the route plan, asset fetching and the pacing regime.

The first executor derived the label from the pacing regime, so pacing alone would have
separated the classes.

## Decision

Both cohorts run through the same executor, `ati-lab-session`, with the same route plans,
task menu and pacing regimes. The **cohort is the label** and the **pacing variant is the
regime**, and they are independent inputs. In the human cohort a consented participant
triggers each request by hand. In the automated cohort a timer follows the same regime. The
burst regime is automated-only, and a participant cannot be assigned it.

`ati-lab-corpus` checks the audit dimensions ATI never sees: pacing variant, executor,
scenario version and catalogue version. It refuses to write a corpus in which any value of
those dimensions occurs in one target class only, unless explicitly run as a diagnostic.

## Consequences

- The design makes the measurement hard on purpose. On a synthetic fixture built this way,
  the baseline ladder correctly declines to claim a win, and the ablation attributes the
  remaining signal to timing alone. On an unmatched fixture the same pipeline reports a
  perfect, meaningless score.
- Collection takes longer: every regime, task and window must appear in both cohorts.
- The check lives in the laboratory because only the laboratory holds these fields. ATI's
  own feature firewall cannot see them
  ([ATI ADR 0007](https://github.com/jccontrerasg08-cpu/agent-traffic-intelligence/blob/main/docs/adr/0007-pf2-feature-firewall.md)).
