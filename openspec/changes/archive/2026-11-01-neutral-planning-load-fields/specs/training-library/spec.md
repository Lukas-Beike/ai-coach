## ADDED Requirements

### Requirement: Provider-neutral planning metrics

Local planning records SHALL use provider-neutral names for planned load, intensity and frozen target FTP. The Intervals.icu adapter SHALL translate its wire fields at the provider boundary.

#### Scenario: Provider workout is imported
- **WHEN** a provider workout has planned load or intensity
- **THEN** its local record retains those values under provider-neutral names.

#### Scenario: Workout is exported
- **WHEN** a local workout is explicitly synchronized to Intervals.icu
- **THEN** the adapter emits the corresponding provider fields with unchanged values.

#### Scenario: Frozen target basis
- **WHEN** an activity detail freezes a local workout target
- **THEN** the stored FTP basis uses a provider-neutral name and retains its value.

Evidence: `backend/planning/library.py`, `backend/planning/target_snapshot.py`, `backend/providers/intervals_workouts.py`; `tests/test_workout_export_intervals.py`, `tests/test_target_snapshot_summaries.py`, `tests/test_db_planning_metrics_migration.py`.
