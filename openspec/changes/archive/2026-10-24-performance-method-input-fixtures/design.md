# Design

## Context

See proposal.md. The cards for M1–M4 are merged (#1442). M1–M3 are released for
the athlete's own use; M4 stays blocked. M1 and M4 have no implementation; M2
and M3 run as `personal-quartiles-v1` and `sleep-regularity-v1` on raw provider
rows. Prerequisites #1410, #1411, #1415, #1418–#1420 and #1423 are open and
owned by parallel sessions.

## Goals / Non-Goals

**Goals:**

- Executable evidence of which canonical fields and readers each method would
  use today, including the gaps.
- A documented trace from canonical storage to every consumer per method.

**Non-Goals:**

- No method implementation, reader change, mapping fix or schema change. Gaps
  are recorded, not closed.
- No real athlete data, provider calls or credential files.

## Decisions

- **One test module, one class per method.** `tests/test_performance_method_inputs.py`
  with one class per method, each with a complete, an incomplete and a
  contradictory test, plus focused tests where one set is not enough.
  Alternative: extend existing per-module tests; rejected because G1 evidence
  must be readable per method.
- **Reuse ingest and helpers.** Payloads go through the existing mappers and
  ingest functions into a temporary `DatabaseManager` database, as in
  `tests/test_session_linking.py` and `tests/canonical_detail_support.py`. Pure
  functions (`personal_recovery`, `sleep_regularity`, `power_profile`) are called
  directly where they are the current consumer.
- **Outcome where no method exists.** For M1 and M4 the asserted outcome is at
  input level: the field is available, absent (no value), or excluded/outranked
  (for example a downsampled stream). No test-only method implementation.
- **Gaps are pinned, not skipped.** A gap assertion states current behaviour and
  names the issue in its message, for example that the personal recovery reader
  ignores a canonical HRV observation (#1411). Closing the gap fails the test
  and forces an update, which is intended.
- **Trace document.** `inputs.md` sits next to the cards because it describes
  their inputs. #1425 asks for the trace in the issue; issue writes are outside
  this delivery, so the document is the durable copy and the PR links it.

## Risks / Trade-offs

- Pinned gap assertions will break when parallel work closes a gap. Mitigation:
  each message names the issue and the expected new behaviour.
- Provider payload shapes in fixtures are synthetic; field names follow the
  mappers, not live captures.
