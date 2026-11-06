## MODIFIED Requirements

### Requirement: Provider-neutral activity summary per session
The system SHALL give activity consumers one provider-neutral summary per live canonical session, built from the active records of every provider in it. Each value SHALL come from the best-ranked record that has it (measured values from the recording platform's own copy first, derived values by provider rank) and name its source label. Consumers outside the provider adapters, sync and canonical owners SHALL NOT read provider activity field names.

#### Scenario: Copies of one session
- **WHEN** Intervals.icu and Garmin Connect both report a session that canonical linking bundled
- **THEN** consumers receive one summary with the local session id, the canonical sport and environment, and each value's source label.

#### Scenario: Load on different scales
- **WHEN** a session has only a Garmin training load
- **THEN** the summary has no provider TSS-like load, still counts its duration and distance, and loads of TSS-like models (Intervals.icu training load, TSS) are kept as `provider_training_load` with their `provider_load_model`.

#### Scenario: Served load is local
- **WHEN** a reader serves a session's summary
- **THEN** `training_load` and `intensity` are the stored local load and power IF (M6) labelled `derived`, never a provider value.

#### Scenario: Stored keys of a session
- **WHEN** a consumer looks up feedback, workout profiles or analyses of a summary
- **THEN** it uses the session's Intervals.icu activity id when it holds one, else the local session id, as the reference resolver does.

Detailed contract: summary keys follow `activity_detail.v1` (`started_at_local`, `moving_duration_s`, `elapsed_duration_s`, `distance_m`, `elevation_gain_m`, `avg_hr`, `max_hr`, `avg_power`, `normalized_power`, `avg_speed_mps`, `pace_mps`, `grade_adjusted_speed_mps`, `rpe`, `feel`, `ftp_w`, `eftp_w`, `vo2max`, `provider_training_load`, `provider_load_model`, `provider_intensity`, the served `training_load`, `intensity`, `load_method`, `load_method_version`, `load_branch` and `load_threshold_after_session`, zone times as `{id, secs}` lists, `planned_event_id`, `recorded_by`, `source`, `sources`, `record_ids`). The Intervals.icu (v6) and Garmin (v7) mappers store the summary values in the record details, so the existing backfill re-maps stored rows; no schema change.

Evidence: `backend/activities/activity_summary.py`, `backend/sync/canonical_table_reader.py:CanonicalTableReader.activity_sessions`, `backend/sync/canonical_read_selector.py:CanonicalReadSelector.activity_summaries`; `tests/test_activity_summary.py`, `tests/test_canonical_table_reader.py:ActivitySessionReadTests`, `tests/test_intervals_activity_mapping.py:SummaryValueTests`, `tests/test_garmin_activity_mapping.py:SummaryValueTests`, `tests/test_provider_coupling_guard.py`.
