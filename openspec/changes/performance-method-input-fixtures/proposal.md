# Proposal

## Why

Epic S (#1409) gate G1 (#1425) requires proof that the inputs of methods M1–M4
exist in the canonical model with separable provenance before any method is
built on them. The method cards (#1424) name the inputs, but nothing shows
which canonical fields carry them today, which readers bypass them, or how
incomplete and contradictory provider data behave.

## What Changes

- Add synthetic fixture tests per method (M1–M4) with one complete, one
  incomplete and one contradictory input set. Each set has a defined, asserted
  outcome: a value, no value with a status or reason, or an exclusion.
- Assert transport provider, recording origin and device class separately, and
  that a ride imported from Intervals.icu and Garmin forms one canonical session.
- Pin current gaps (reader bypasses, missing fields) as explicit assertions that
  name the owning issue, so closing a gap changes a known test.
- Add `docs/performance-methods/inputs.md`: per-method canonical inputs, consumer
  trace (canonical read → method → report/context → HTTP/UI/Coach), data gaps
  and persistence needs mapped to #1408 sub-issues or the owning method issue.
- No application behavior, API, UI, persistence or schema change.

## Capabilities

### New Capabilities

- None.

### Modified Capabilities

- `performance-and-readiness`: adds a requirement that every method card has
  synthetic input fixtures and a documented consumer trace.

## Impact

- New test: `tests/test_performance_method_inputs.py` (temporary storage,
  synthetic payloads, no provider access).
- New documentation: `docs/performance-methods/inputs.md`; README links it.
- Main spec `openspec/specs/performance-and-readiness/spec.md` gains one
  requirement after sync.
