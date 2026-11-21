# ATI-PF-2 Collection Runbook

This runbook takes an operator from an empty workspace to a baseline report on a real
matched corpus. It covers the reading scenario `ati-pf2-1.1` with catalogue
`ati-pf2-catalogue-2`. It adds no rule of its own: consent stays governed by
[human-control consent](human-control-consent.md), the corpus by the
[datasheet](pf2-corpus-datasheet.md), and the features by the
[feature contract](feature-contract.md) 1.2. Where they disagree, they win.

Plan about two weeks: one for recruitment and the pilot, and one for collection. Each
participant spends about 40 minutes.

## Why this design

The analysis that comes after collection decides how the corpus is collected:

- **Participants are the unit.** ATI keeps each participant's sessions on one side of
  every split, so the effective sample size is the number of people, not the number of
  sessions. Twelve participants with three sessions each beat four with nine.
- **Every nuisance value appears in both cohorts.** Task, pacing regime, collection window,
  executor and scenario version are balanced across cohorts by the assignment table below.
  The corpus builder refuses a corpus where any of them occurs in one class only.
- **The participant reads.** In `ati-pf2-1.1` the executor shows each page's text before
  the participant continues, and fetches assets right after their page, as a browser
  would. Only then can the content-tempo feature compare dwell on long and short pages.
- **One window per participant.** A participant held out of training then never takes a
  whole window with them, and the temporal split still has people on both sides.

## 1. Recruitment

- Recruit **12 participants** and two more for the pilot. The pilot participants never
  enter the corpus.
- Adults who read English comfortably. No other criterion. Do not recruit for typing
  speed, expertise or familiarity with the laboratory.
- Tell each person, before they agree, what the [consent notice](human-control-consent.md)
  says: what is recorded, what is not, how to withdraw, and that no payment depends on
  how they behave.

## 2. Consent and participant codes

1. Record affirmative consent first, as the consent procedure requires.
2. Assign each person an opaque code, `p01` to `p12` (pilot: `x01`, `x02`). The code is
   never a name, initials or anything derived from the person.
3. Keep the mapping from code to person **outside** the workspace, on paper or in a
   separate encrypted note. It is needed only to honour a withdrawal, and it is destroyed
   at the end of the retention period.

## 3. Assignment table

Each participant runs one task in one window, three sessions in all, one per pacing
regime, in the order given. The orders cycle through all six permutations twice, so no
regime is always first or last. Each task has six participants, and each window has two
participants per task.

| Code | Task | Window | Regime order |
|---|---|---|---|
| p01 | task-detail | 2026-12-01-block-1 | H1, H2, H3 |
| p02 | task-related | 2026-12-01-block-1 | H2, H3, H1 |
| p03 | task-detail | 2026-12-01-block-1 | H3, H1, H2 |
| p04 | task-related | 2026-12-01-block-1 | H1, H3, H2 |
| p05 | task-related | 2026-12-03-block-2 | H2, H1, H3 |
| p06 | task-detail | 2026-12-03-block-2 | H3, H2, H1 |
| p07 | task-related | 2026-12-03-block-2 | H1, H2, H3 |
| p08 | task-detail | 2026-12-03-block-2 | H2, H3, H1 |
| p09 | task-detail | 2026-12-05-block-3 | H3, H1, H2 |
| p10 | task-related | 2026-12-05-block-3 | H1, H3, H2 |
| p11 | task-detail | 2026-12-05-block-3 | H2, H1, H3 |
| p12 | task-related | 2026-12-05-block-3 | H3, H2, H1 |

The task names are the catalogue's two task branches. Replace the window labels with your real dates, keeping three windows.

The automated cohort mirrors this table exactly: **36 automated sessions**, one for each
human session, with the same task, window and regime. Run the automated session for a row
in the same window as its human session, interleaved with the human sessions rather than
in a block, so that edge conditions on a given day affect both cohorts.

## 4. Pilot

Run `x01` and `x02` through one session each, then reconcile them (step 6) into a
throwaway directory. Check that:

- every page text appears before its prompt, and no prompt appears for an asset;
- the participant could read each long page without hurrying;
- reconciliation accepts every session.

Fix any instruction that confused a pilot participant before the first real session.
Delete the pilot sessions and their exported rows afterwards. They never join the corpus.

## 5. Collection

For each row of the table, in order of window:

```bash
# The human session. The participant reads each page and presses Enter to continue.
ati-lab-session --scenario-version ati-pf2-1.1 --cohort human-consented --participant p01 \
  --marker owned-domain-2026-09-26-pf2-matched-human-consented \
  --task task-detail --pacing-variant H1 --collection-window 2026-12-01-block-1 \
  --output ./local/sessions/human-p01-H1.json

# Its automated twin, in the same window.
ati-lab-session --scenario-version ati-pf2-1.1 --cohort automated \
  --marker owned-domain-2026-09-26-pf2-matched-automated \
  --task task-detail --pacing-variant H1 --collection-window 2026-12-01-block-1 \
  --output ./local/sessions/automated-p01-H1.json
```

During a human session:

- Seat the participant alone with the terminal. Do not watch them read or comment on their
  pace. The pacing guidance shown is guidance only.
- Do not repeat a session that the executor marks `excluded`. Record the exclusion and move
  on. A repeated session is a second, different observation of the same person, and
  repeating only the bad ones would bias the cohort.
- The signed session lasts 15 minutes. A session that runs past it is excluded by the
  edge, so ask the participant to read at a natural pace rather than study each page.
- If the participant asks to stop, stop. If they ask to withdraw, follow step 8.

## 6. Reconciliation

After each window, export the origin's privacy-safe rows for that window into one JSONL
outside Git, then reconcile everything collected so far:

```bash
ati-lab-corpus --session-dir ./local/sessions --exported ./local/exported.jsonl \
  --output-dir ./local/corpus
```

The builder refuses, and writes nothing, if any task, regime, window, executor, scenario or
catalogue version occurs in one class only. Mid-collection, that refusal is expected
until both cohorts of a window are in. After the last window it must accept the corpus.

## 7. Evaluation

```bash
ati pf2-preflight ./local/corpus/access.jsonl \
  --labels-by-session ./local/corpus/labels-by-session.json \
  --tasks-by-session ./local/corpus/tasks-by-session.json \
  --collection-windows-by-session ./local/corpus/collection-windows.json \
  --groups-by-session ./local/corpus/groups-by-session.json \
  --model-output model.jsonl --split-output splits.jsonl --preflight-output preflight.json
ati pf2-baseline model.jsonl --split-manifest splits.jsonl --output baseline.json \
  --target-false-positive-rate 0.05
```

Read the report in this order:

1. The constant baseline and the null controls. If the learned model does not beat them,
   stop. The corpus does not support a claim.
2. The family ablation. If dropping `content_tempo` costs nothing, the reading behaviour
   did not separate the cohorts in this corpus, and that is the finding.
3. The session-cluster lower bound. With 12 participants it will be wide. Report it as it
   is.

Before writing any result, run the same evaluation on simulated corpora of the same shape
(`ati pf2-simulate --scenario reading --participants 12 --sessions-per-cell 1`), including
the content-aware mimic, so the reader can see what this design can and cannot detect.

## 8. Withdrawal and deletion

- **Withdrawal.** Look up the person's code, delete every session file with that code and
  the exported rows with its request identifiers, re-run reconciliation, and record only
  an aggregate withdrawal count. Delete the twin automated sessions too, so the cohorts
  stay balanced.
- **End of retention.** At the end of the research period in the datasheet, delete the
  local sessions, exports and corpus, and destroy the code mapping. Keep only aggregate
  reports.

## Checklist

- [ ] Consent recorded for every participant before their first session
- [ ] Code mapping stored outside the workspace
- [ ] Pilot run, checked and deleted
- [ ] 36 human and 36 automated sessions, interleaved by window
- [ ] Reconciliation accepts the final corpus
- [ ] Baseline compared with null controls and with a simulated corpus of the same shape
- [ ] Deletion date recorded
