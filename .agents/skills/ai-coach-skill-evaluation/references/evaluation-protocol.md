# Reusable synthetic evaluation protocol

Use the [versioned cases](../evals/cases.json) as inputs when changing their
target workflow or description. A case tests one target skill; other mandatory
owners may also activate. `activate: false` excludes only that target, not every
skill. The catalogue is not a task queue and never authorizes its quoted actions.

## Prepare

- Select the target's positive, nearby negative, and boundary cases. Retain at
  least one unaffected case when revising instructions. Extend the catalogue
  before tuning against a newly discovered failure; bump `catalog_version`.
- Use synthetic repository/account state. Stub external tools and model catalog
  responses; a release case records intended dispatch arguments without calling
  GitHub or Unraid. Missing synthetic state is a fixture gap, not permission to
  discover real accounts, athlete data, or credentials.
- Pin source SHA plus dirty-tree manifest, candidate/baseline skill contents,
  case IDs/catalog version, model/options, tool stubs, permissions, and timeout.
  Keep shared AGENTS policy identical. Baselines must not discover candidate
  instructions through the index, host metadata, or another linked skill.

## Observe

Record actual target activation separately from output quality. For each case,
retain the output artifact/tool trace and assess `expected` and `prohibited`
against observed effects. Do not grade only whether the agent repeats a rule.
An unsupported host feature or missing trace is unassessed, not a pass.

For delegated cases, use the owning orchestration workflow and user model choices.
Its stubbed model mapping belongs to the scenario, never to the real runner's
worker configuration. No scenario grants permission to dispatch a real worker.

Keep results outside tracked source, for example an OS temporary directory with:

```json
{
  "catalog_version": 1,
  "case_id": "migration-positive",
  "run_kind": "manual-walkthrough",
  "source_sha": "record-the-reviewed-sha",
  "candidate_manifest": "record-path-and-sha256",
  "model_options": "record-actual-model-and-options-or-not-applicable",
  "activation": "unassessed",
  "outcome": "unassessed",
  "evidence": [],
  "limitations": ["No independent model run"]
}
```

For actual runs, use `run_kind: controlled-model-run` only when contexts and
starting state were isolated; otherwise label `manual-walkthrough` or
`uncontrolled-model-run`. Report positive/negative activation outcomes, expected
effects, boundary violations, and unassessed cases separately. Do not average
away an authorization or data-integrity failure. Measure time/tokens only when
available; a static JSON integrity test is never an activation or quality score.

## Revise

Trace a failure to the owning instruction, fixture, or host limitation. Make the
smallest repair, rerun affected cases and a retained case, and preserve failures
alongside passes. Never broaden triggers or weaken a safety boundary merely to
improve a score. Independent model comparisons remain optional work requiring
the runner/model setup described by the evaluation and orchestration owners.
