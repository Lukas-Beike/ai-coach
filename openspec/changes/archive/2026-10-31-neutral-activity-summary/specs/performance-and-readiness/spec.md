## MODIFIED Requirements

### Requirement: Training reports retain coverage and actual execution
The system SHALL build local period reports from the neutral activity summaries, one per canonical session, using athlete-local dates, exclude future completed data, and expose measured-session coverage for duration, distance, and load. Reports SHALL include supported period comparisons, daily/cumulative load, eight calendar weeks of load, sports, key sessions, feedback, and plan-execution context with a common period. Unknown values SHALL stay unknown while valid zero load remains measured.

#### Scenario: Partial current week
- **WHEN** a report includes the current calendar week with measured, zero, and missing load rows
- **THEN** it reports the partial period and measured/total-session counts, counts each session once across providers, and includes valid zero contributions.

#### Scenario: Timezone boundary or future record
- **WHEN** an absolute start crosses an athlete-local midnight or an activity is dated in the future
- **THEN** grouping uses the athlete-local date and future completed evidence does not inflate historical totals.

#### Scenario: Report without snapshot rows
- **WHEN** a report is requested and the stored snapshot holds no activity rows
- **THEN** the report is built from the canonical activity summaries and its `observed_at` comes from canonical coverage, null when none is stored.

#### Scenario: Garmin-only session
- **WHEN** a session in the period has only a Garmin Connect record with a Garmin training load
- **THEN** it counts as a session with its duration and distance but adds no training load.

Detailed contract: The report `observed_at` SHALL be the Intervals.icu activity fetch time of the canonical provider coverage, or null when none is stored. Totals are named `moving_duration_s`, `distance_m` and `training_load`; `sports` and sport filters use canonical sports (`ride`, `run`, ...).

Evidence: `backend/performance/training_report.py:training_report`; `tests/test_training_report.py`.

### Requirement: Report-family reads use canonical activity rows only
The system SHALL read the activities of period reports, the training-record observation list, tag impact, training focus, load rollups, eFTP and season preparation from the canonical activity summary port only, and SHALL NOT fall back to the stored snapshot's `raw_provider_data.activities` or `recent_activities`.

#### Scenario: Canonical rows with an empty snapshot
- **WHEN** any of these reads runs with canonical activity summaries and a snapshot without activity sections
- **THEN** it computes from the summaries exactly as it would with the rows in the snapshot.

#### Scenario: No activity rows
- **WHEN** the canonical summary port returns no summaries
- **THEN** the read returns its existing empty-data result (no sessions, insufficient data) instead of an error or snapshot data.

#### Scenario: Copies stored by the first backfill
- **WHEN** the first canonical backfill stores an Intervals.icu and a Garmin Connect copy of one activity
- **THEN** it links them into one session, so these reads count the activity once, as the legacy projection bundles it.

Detailed contract: The services that run these reads require their canonical source at construction. Duplicates are merged by canonical session linking, not by row de-duplication; only the raw-row equipment read keeps the Wahoo/Garmin row de-duplication.

Evidence: `backend/performance/training_report.py`, `backend/performance/report_service.py:TrainingRecordsService.observations`, `backend/performance/tag_impact.py`, `backend/performance/training_focus.py:training_focus`, `backend/performance/canonical_inputs.py:activity_summaries_for`, `backend/sync/canonical_backfill.py:_link_work_sessions`; `tests/test_training_report.py`, `tests/test_training_focus.py`, `tests/test_season_canonical_reads.py`, `tests/test_canonical_table_reader.py:ActivitySessionReadTests`.
