## ADDED Requirements

### Requirement: Session-RPE load is a descriptive local method
The system SHALL compute the M1 session-RPE load (`session-rpe-load` v1) as elapsed minutes × whole-session RPE in AU for each canonical session, and sum it per athlete-local day, ISO week and sport with the known partial value, rated and total session counts and RPE source counts. AU SHALL never be added to or converted into TSS, provider load or TRIMP.

#### Scenario: Acceptance values
- **WHEN** a session of 60 minutes has local RPE 5, one of 30 minutes has RPE 0 and one has no RPE
- **THEN** they give 300 AU, 0 AU and no value with reason `no_rating`.

#### Scenario: Partial sum
- **WHEN** two rated sessions of 300 and 120 AU and one unrated session fall in a period
- **THEN** the period reports 420 AU known load with 2 of 3 sessions rated.

#### Scenario: Provider fallback
- **WHEN** a session has no local RPE and its Intervals.icu record reports RPE 6 over 50 minutes
- **THEN** it gives 300 AU labelled with the Intervals.icu source; a local RPE 5 of the same session would win instead.

#### Scenario: No valid input
- **WHEN** the session's provider records disagree on RPE without a local one, it has only a moving time, or its duration is not positive
- **THEN** it gives no value with reason `conflicting_provider_ratings`, `no_elapsed_duration` or `invalid_duration` and stays an open session in the sums.

#### Scenario: Duplicate imports and edits
- **WHEN** one session is imported from two providers, or its RPE is edited, cleared or the edit undone
- **THEN** it counts once, and the next read reflects the effective feedback or the provider fallback.

Detailed contract: each result names `metric_id`, `method_id`, `method_version`, unit, status (`descriptive` or `insufficient_data`), period with timezone, computation time, method note, limits and the evidence card `docs/performance-methods/m1-session-rpe-load.md`. Per session it lists RPE, source and label, duration in minutes and, for a local rating with a recorded rating time, `rated_minutes_after_end`. Values are rounded to one decimal only for output. The Coach training report carries it for the report period, the public performance history for the load tab's 84 days, where the PWA draws a separate AU chart with its coverage. The Coach SHALL name the inputs and source and SHALL NOT derive injury risk, readiness or ramp statements from AU.

Evidence: `backend/performance/session_rpe_load.py`, `backend/performance/training_report.py:training_report`, `backend/performance/report_service.py:TrainingReportReadService`, `backend/http_api/public_performance.py:PublicPerformanceStateService`, `backend/coach/prompt.py`, `public/analysis.js:appendSessionRpeLoadChart`; `tests/test_session_rpe_load.py`, `e2e/activity-details.spec.js`.

## MODIFIED Requirements

### Requirement: Method input fixtures
Every method with an evidence card SHALL have synthetic input fixtures for one complete, one incomplete and one contradictory input set, each with a defined outcome: a value, no value with a status or reason, or an exclusion. The fixtures SHALL keep transport provider, recording origin and local method apart and SHALL count an activity imported from several providers once.

#### Scenario: Incomplete input
- **WHEN** a required input is missing for a method (for example no session RPE, too few earlier nights, or only a downsampled stream)
- **THEN** the fixture asserts that no value is produced or that the input is excluded, with the status or reason the current code gives; where current code still produces a value from that input, the fixture pins it as a known gap naming the owning issue.

#### Scenario: Contradictory providers
- **WHEN** two providers report different values for the same input
- **THEN** the fixture asserts that the values stay separate per provider and method and are not averaged.

#### Scenario: Canonical provider RPE
- **WHEN** an Intervals.icu activity reports `icu_rpe` beside a local session RPE
- **THEN** the canonical activity record keeps the provider RPE with its provenance and the M1 result uses the local rating.

Evidence: `tests/test_performance_method_inputs.py`.
