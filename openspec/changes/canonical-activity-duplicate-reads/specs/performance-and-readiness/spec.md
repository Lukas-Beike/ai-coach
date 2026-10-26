## MODIFIED Requirements

### Requirement: Training reports retain coverage and actual execution
The system SHALL build local period reports from deduplicated canonical activity rows using athlete-local dates, exclude future completed data, and expose measured-session coverage for duration, distance, and load. Reports SHALL include supported period comparisons, daily/cumulative load, eight calendar weeks of load, sports, key sessions, feedback, and plan-execution context with a common period. Unknown values SHALL stay unknown while valid zero load remains measured. The report `observed_at` SHALL be the Intervals.icu activity fetch time of the canonical provider coverage, or null when none is stored.

#### Scenario: Partial current week
- **WHEN** a report includes the current calendar week with measured, zero, and missing load rows
- **THEN** it reports the partial period and measured/total-session counts, deduplicates copies, and includes valid zero contributions.

#### Scenario: Timezone boundary or future record
- **WHEN** an absolute start crosses an athlete-local midnight or an activity is dated in the future
- **THEN** grouping uses the athlete-local date and future completed evidence does not inflate historical totals.

#### Scenario: Report without snapshot rows
- **WHEN** a report is requested and the stored snapshot holds no activity rows
- **THEN** the report is built from the canonical activity rows and its `observed_at` comes from canonical coverage, null when none is stored.

Evidence: `backend/performance/training_report.py:training_report`, `backend/performance/training_report.py:activity_day`, `backend/performance/report_service.py:TrainingReportReadService`; `tests/test_training_report.py:test_eight_week_load_totals_keep_missing_zero_duplicates_and_boundaries`, `tests/test_training_report.py:test_sport_filter_and_plan_execution_use_the_same_period`, `tests/test_training_report.py:test_timezone_boundary_and_future_records_are_handled_without_provider_reads`. Missing evidence (planned in this change): report, observation list, tag impact and focus tests with an empty snapshot, and `observed_at` from coverage.

## ADDED Requirements

### Requirement: Report-family reads use canonical activity rows only
The system SHALL read the activity rows of period reports, the training-record observation list, tag impact and training focus from the canonical activity row port only, and SHALL NOT fall back to the stored snapshot's `raw_provider_data.activities` or `recent_activities`.

#### Scenario: Canonical rows with an empty snapshot
- **WHEN** any of these reads runs with canonical activity rows and a snapshot without activity sections
- **THEN** it computes from the canonical rows exactly as it would with the rows in the snapshot.

#### Scenario: No activity rows
- **WHEN** the canonical row port returns no rows
- **THEN** the read returns its existing empty-data result (no sessions, insufficient data) instead of an error or snapshot data.

Detailed contract: The services that run these reads require their canonical source at construction. Duplicate Garmin copies are still removed from the rows by the existing Wahoo/Garmin de-duplication.

Evidence: `backend/performance/training_report.py:canonical_rows`, `backend/performance/report_service.py:TrainingRecordsService.observations`, `backend/performance/tag_impact.py:_day_loads`, `backend/performance/training_focus.py:training_focus`, `backend/performance/canonical_inputs.py:activity_rows_for`; `tests/test_training_report.py:test_derived_and_season_reads_keep_missing_data_fallbacks`, `tests/test_training_focus.py:test_recorded_hr_and_power_zones_remain_separate_and_bounded`. Missing evidence (planned in this change): tests that the snapshot is never read for activities and that construction without a canonical source is rejected.
