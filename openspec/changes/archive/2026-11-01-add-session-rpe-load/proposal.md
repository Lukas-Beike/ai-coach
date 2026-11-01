## Why

Epic S (#1409) work package P3, gate G3 (#1427): the athlete's local session RPE is stored but never turned into the session-RPE load that the released M1 evidence card describes. #1446 asked for a canonical home of the Intervals.icu `icu_rpe` fallback; it already lives on the canonical activity record (#1510).

## What Changes

- New behavior: `backend/performance/session_rpe_load.py` computes M1 (`session-rpe-load` v1): elapsed minutes × whole-session RPE in AU per session, local day, ISO week and sport, with rated/total coverage, RPE source counts, status, limits and the evidence-card reference.
- Local feedback RPE is the input; only without one the provider RPE of the same canonical session is a labelled fallback. Disagreeing provider ratings, a missing rating, a moving-time-only session or an invalid duration give no value with a reason.
- Schema v18 adds `activity_feedback.session_rpe_rated_at`, set when the RPE changes; earlier ratings keep an unknown rating time. The privacy export becomes format version 10.
- The Coach training report, the activity detail document and the public performance history carry the result; the load tab shows a separate AU chart, the activity detail shows the session's AU, and the RPE control becomes a 0–10 half-point selection with CR-10 anchors.
- The Coach prompt names inputs and source and forbids mixing AU with TSS or provider load.

Exclusions: no ACWR, readiness or risk statement; no change to provider load, ATL or scenarios; no new provider fetch.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `performance-and-readiness`: session-RPE load requirement.
- `activity-analysis-and-feedback`: rating time on feedback and the session load in the detail document.
- `encrypted-storage-and-migrations`: v17 frozen, v17 to v18 upgrade.

## Impact

`backend/performance/`, `backend/activities/`, `backend/db/` (schema v18), `backend/http_api/`, `backend/coach/prompt.py`, `public/activity-details.js`, `public/analysis.js`, asset versions, `docs/performance-methods/`, tests and fixtures.
