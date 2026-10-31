## ADDED Requirements

### Requirement: Coach activity context uses neutral activity summaries
The Coach context SHALL list recent activities from the neutral activity summaries of every provider, one per session, with the local session id, canonical sport and environment, neutral value keys, `load_model` and source labels, and SHALL NOT expose provider field names or type names. For Intervals.icu-only data the values and source labels SHALL stay as before.

#### Scenario: Intervals.icu-only parity
- **WHEN** the Coach context is built from Intervals.icu-only synthetic activities
- **THEN** each activity's values, the per-sport rollups and the source labels equal the former context, under the neutral keys.

#### Scenario: Garmin-only session
- **WHEN** a recent session has only a Garmin Connect record
- **THEN** it appears in the Coach context with its Garmin values and source label and without a training load.

Evidence: `backend/coach/context.py:compact_coach_activity`, `backend/coach/context.py:CoachIntervalsContextService`; `tests/test_coach_activity_summary_parity.py`, `tests/test_coach_intervals_context.py`.
