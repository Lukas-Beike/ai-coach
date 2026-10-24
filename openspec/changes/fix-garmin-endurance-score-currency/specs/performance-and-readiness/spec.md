# Spec Delta

## ADDED Requirements

### Requirement: Current Garmin endurance-score history
The system SHALL request the bounded Garmin endurance-score history as daily dated readings and SHALL label that history with daily aggregation. The analysis view SHALL show, for each calendar week, the newest valid reading of that week, and its current value SHALL carry the date of the newest stored Garmin measurement. A week-start bucket SHALL never stand in for a later dated measurement.

#### Scenario: Running week has a newer measurement
- **WHEN** Garmin has endurance-score readings up to 2026-10-23 and the analysis history ends on 2026-10-24
- **THEN** the running calendar week shows the 2026-10-23 reading and the current value is dated 2026-10-23, not the preceding Sunday.

#### Scenario: Running tolerance uses daily readings
- **WHEN** a Garmin historic-metrics sync or a targeted analysis read requests the running-tolerance range
- **THEN** it requests daily aggregation, records `daily` as its aggregation metadata, and the current value carries the date of the newest stored running-tolerance reading.

#### Scenario: Collection requests daily readings
- **WHEN** a Garmin historic-metrics sync or a targeted analysis read requests the endurance-score range
- **THEN** it requests the bounded 90-day range with daily aggregation and records `daily` as the endurance score's aggregation metadata.

#### Scenario: Previously stored weekly payload
- **WHEN** a stored Garmin payload still contains weekly endurance-score buckets from an earlier sync
- **THEN** history projection remains readable without error, and the next successful Garmin sync replaces it with daily readings without deleting other stored provider data.

#### Scenario: No readings in a week
- **WHEN** a calendar week has no dated endurance-score reading
- **THEN** that week remains a gap and no value is carried forward or interpolated into it.

Evidence: observed defect from athlete diagnostics 2026-10-24 (`garmin.source_freshness.endurance_score.observed_at` = 2026-10-23 while the chart's latest point stayed at 2026-10-18); `backend/providers/garmin.py:_collect_historic_metrics`, `backend/providers/garmin.py:targeted_analysis_sources`, `backend/performance/garmin_metric_history.py:_records`, `backend/performance/chart_history.py:_provider_metrics`, `backend/performance/history.py:_provider_metrics`, `public/analysis.js:analysisWeeklyPerformancePoints`; `tests/test_provider_garmin_metric_history.py:test_known_sdk_methods_get_bounded_dates_and_explicit_aggregation`, `tests/test_performance_chart_history.py:test_saved_endurance_group_map_repairs_previously_empty_projection`, `tests/test_performance_chart_history.py:test_daily_weekly_view_metrics_reach_the_newest_measurement`, `tests/test_garmin_analysis_refresh.py:test_targeted_weekly_view_metrics_request_daily_readings`; running tolerance shares the weekly grouping in `public/analysis.js`. Gap: the exact daily `groupMap` key shape is inferred from the SDK docstring and existing weekly handling, not from a captured live payload.
