# provider-normalization-and-provenance Specification

## Purpose

Describe canonical interpretation of provider fields, units, dates, origins, source precedence, corrections, and the limits of current canonical coverage. Garmin and Wahoo are the data providers. Intervals.icu is an output target only (#1728) and never a source: no mapper reads its records, and rows of a database restored from a release before 2.0.0 stay stored and are not replayed. The current build contains no code that deletes stored Intervals.icu rows; the one-time purge of release 2.0.0 ran in production and its code was removed (#1848), and the production database holds no such rows (athlete count-only check, 2026-11-10). The field-by-field map is `docs/canonical-field-map.md`.

## Requirements

### Requirement: Validated canonical values and provenance
The system SHALL map provider data into validated activity records and observations with provider, source kind, source-record identity, retrieval time, metric unit, optional observation time, sport, and recording origin. Invalid required identity or time SHALL drop a record with a structured issue; invalid optional measurements SHALL remain absent with an issue. Mapping issues SHALL identify the field and reason without echoing raw values.

#### Scenario: Sparse activity
- **WHEN** an activity has a usable identity and start but lacks an optional metric
- **THEN** it remains available with that metric absent instead of a fabricated zero.

#### Scenario: Invalid provider measurement
- **WHEN** a provider sends a nonfinite, invalid-type, or out-of-range measurement
- **THEN** normalization reports a content-free issue and excludes the invalid measurement.

#### Scenario: Issue reasons
- **WHEN** a mapper reports a problem
- **THEN** the reason is one of `missing`, `invalid_type`, `invalid_number`, `out_of_range`, `unknown_value` or `unsupported`, with the record reference and field name only.

#### Scenario: Number text
- **WHEN** a mapper reads a number from text
- **THEN** activity and health values accept dot-decimal text only; Garmin weight and body fat, the reported sleep duration, Wahoo FTP and weight and the Garmin performance values at ingest also accept a comma as the decimal mark, except text of one to three digits not starting with 0, a comma and exactly three digits (`1,200`, `72,500`), which could be grouped thousands and is an invalid number.

Detailed contract: Unknown provider fields SHALL not automatically enter public canonical records.

Evidence: `backend/canonical/records.py:Provenance`, `backend/canonical/records.py:Observation`, `backend/canonical/mapping.py:MappingIssue`, `backend/providers/wahoo_activity_mapping.py:map_wahoo_activities`; `tests/test_garmin_health_mapping.py:test_issues_never_echo_raw_values`.

Added evidence:
- `backend/canonical/decimal_text.py:comma_decimal_float`
- `backend/canonical/mapping.py:IssueReason`
- `backend/canonical/mapping.py:coerce_comma_decimal_number`
- `tests/test_canonical_decimal_text.py:test_comma_with_three_digits_after_a_short_integer_is_ambiguous`
- `tests/test_canonical_mapping.py:test_ambiguous_grouped_thousands_are_rejected`

### Requirement: Normative field map and mapper versions
The system SHALL keep `docs/canonical-field-map.md` as the normative field map of every provider mapper: provider keys, alias order, unit conversions, bounds, zero rules and the orders that decide a result. A change to what a mapper emits SHALL change the map in the same change and raise the `MAPPER_VERSION` that replays the mapper, so stored raw records are re-projected.

#### Scenario: Mapper output changes
- **WHEN** a mapper change alters the canonical records it emits for a stored payload
- **THEN** the field map states the new rule and the replaying `MAPPER_VERSION` is raised; `tests/test_mapper_version_guard.py` fingerprints the mapping code and every `backend/providers` or `backend/canonical` module a replayed mapper imports, directly or through another (#2501), not their output, and fails when that code changes without a bump of every version that replays it.

#### Scenario: Mapper that feeds another
- **WHEN** `garmin_training_mapping`, `garmin_status_mapping`, `garmin_zone_mapping`, `garmin_gear_mapping` or `sleep_period_mapping` changes
- **THEN** the Garmin health version rises; a change to `fit_rr_mapping` or `fit_sensor_mapping` raises the FIT activity detail and Garmin activity detail versions, and a change to `wahoo_activity_mapping` raises the Wahoo and Garmin activity versions (`REPLAYED_BY` of the guard is the table).

#### Scenario: Outbound mapper
- **WHEN** `wahoo_plan_mapping` changes
- **THEN** no version is required, because it builds export payloads and nothing it builds is stored and replayed (`NOT_REPLAYED`).

#### Scenario: Versions of the stored record kinds
- **WHEN** stored raw records are re-projected
- **THEN** each uses the current version of its mapper, keyed `garmin.activity`, `garmin.health`, `wahoo.activity`, `wahoo.power_zones` and `wahoo.user`; the backfill state keeps these versions, so a raised version makes the worker re-project the records of that kind.

Evidence:
- `backend/providers/canonical_plans.py:current_mapper_versions`
- `tests/test_mapper_version_guard.py:NOT_REPLAYED`
- `tests/test_mapper_version_guard.py:REPLAYED_BY`
- `tests/test_mapper_version_guard.py:test_code_changes_come_with_a_replaying_version_bump`
- `tests/test_mapper_version_guard.py:test_every_mapping_module_is_registered`

### Requirement: Provider-aware time and sport normalization
The system SHALL preserve explicit instants, date each activity on the day it was lived using the UTC offset the provider reports for it and otherwise the active athlete timezone, normalize supported sports and indoor/outdoor/virtual environments, and apply the implemented wall-time DST rules to local timestamps.

#### Scenario: DST overlap or gap
- **WHEN** provider local wall time lies in a DST overlap or spring gap
- **THEN** canonical localization uses the first overlap occurrence or the implemented forward-gap interpretation and retains a valid aware instant.

#### Scenario: Unknown workout type
- **WHEN** a Wahoo workout has an unrecognized type identifier
- **THEN** it maps to other sport and unknown environment rather than claiming a known activity type.

#### Scenario: Activity recorded abroad
- **WHEN** an athlete with profile zone Europe/Berlin records a run at 06:30 in Tokyo, reported by Garmin (`startTimeLocal` nine hours after `startTimeGMT`) or by Wahoo (`time_zone` Asia/Tokyo)
- **THEN** the activity, its session, `started_at_local` and every week or plan read are dated on the Tokyo day at 06:30, not on the previous Berlin day.

#### Scenario: Profile zone change
- **WHEN** the athlete changes the profile zone and stored records are reprojected
- **THEN** activities with their own offset keep their date and wall time, and only activities without one follow the new zone.

#### Scenario: Zone differs from the zone of the stored projection
- **WHEN** the athlete zone differs from the zone stored with the backfill state, or the state holds no zone
- **THEN** the next pass re-projects every active raw record once, whatever its mapped version, so stored local dates follow the zone; reads stay on the tables meanwhile and the state is not current until that pass finished.

#### Scenario: No provider offset
- **WHEN** a provider reports no usable offset (no exact start, a non-IANA zone name, or an offset beyond +-14 hours or off the quarter hour)
- **THEN** the activity is dated in the athlete zone as before.

Detailed contract: Wahoo's naive `starts` SHALL be interpreted as UTC. The offset is stored as `local_offset_minutes` in the activity record's details; a session uses its primary record's offset, else that of the first record reporting one. A summary carrying an offset keeps its own `started_at_local` date even when a reader converts to the athlete zone.

Evidence:
- `backend/activities/detail_contract.py:session_local_start`
- `backend/canonical/activity_summary.py:summary_local_date`
- `backend/canonical/local_time.py:localize_wall_time`
- `backend/canonical/local_time.py:wall_clock_offset_minutes`
- `backend/canonical/local_time.py:wall_time`
- `backend/canonical/local_time.py:zone_offset_minutes`
- `backend/performance/analysis_input.py:analysis_sport`
- `backend/performance/pace_at_hr.py:pace_at_heart_rate`
- `backend/providers/garmin_activity_mapping.py:GARMIN_ACTIVITY_TYPES`
- `backend/providers/garmin_activity_mapping.py:map_garmin_activities`
- `backend/providers/wahoo_activity_mapping.py:WAHOO_WORKOUT_TYPES`
- `backend/sync/canonical_backfill.py:CanonicalBackfill.run_batch`
- `tests/test_activity_local_offset.py`
- `tests/test_analysis_input.py:test_a_trail_terrain_marks_a_trail_run_for_every_provider`
- `tests/test_canonical_read_selector.py:test_state_without_a_stored_zone_reprojects_once_on_the_tables`
- `tests/test_canonical_read_selector.py:test_zone_change_keeps_serving_tables_until_reprojection_finishes`
- `tests/test_garmin_activity_mapping.py:test_only_off_road_runs_are_outdoor_runs`
- `tests/test_pace_at_hr.py:test_indoor_and_virtual_runs_ignore_course_altitude`
- `tests/test_pace_at_hr.py:test_outdoor_run_without_terrain_is_unknown_but_indoor_is_flat`
- `tests/test_wahoo_activity_mapping.py:test_local_date_follows_the_athlete_zone`
- `tests/test_wahoo_activity_mapping.py:test_start_without_an_offset_is_read_as_utc`
- `tests/test_wahoo_activity_mapping.py:test_the_workouts_own_time_zone_dates_it_where_it_was_recorded`

### Requirement: Activity terrain, motor assistance and native type
The system SHALL map the terrain and motor assistance a provider activity type names into provider-neutral qualifiers, keep the provider's native type, and filter analyses by these qualifiers, never by provider identity.

#### Scenario: Trail runs carry an explicit terrain
- **WHEN** a Garmin `trail_running` or `obstacle_run`, or a Wahoo workout type 4 is mapped
- **THEN** it is an outdoor run with terrain `trail`, and the session analyses (decoupling, pace at heart rate), the critical-speed fit and the equal-effort run trend leave it out by that terrain, never by provider; treadmill and virtual runs count as flat for pace at heart rate (method `pace-at-heart-rate-v2`), never grade-adjusted by a course altitude.

#### Scenario: E-bike rides carry motor assistance
- **WHEN** a Garmin `e_bike_fitness` or `e_bike_mountain`, or a Wahoo workout type 64 is mapped
- **THEN** it is a ride with assist `electric`; its session stays out of the power and speed best values, CP/CS fits and mean-max and equal-effort trends, and counts in time-based volume, reported again as `electric_assist_hours`.

#### Scenario: Equivalent types across providers
- **WHEN** the same activity type that names an environment or a terrain exists in two provider tables (for example cyclocross, mountain bike, lap or open-water swim, treadmill run)
- **THEN** each provider maps it to the same sport, environment and terrain.

#### Scenario: Generic types
- **WHEN** a provider reports its generic ride, run, walk or hike
- **THEN** a Garmin `cycling`, `running`, `walking` or `hiking` has environment `unknown`, which only the words `virtual`, `zwift`, `indoor`, `trainer`, `treadmill` or `laufband` in its type key or name refine, while a Wahoo generic ride (0, 11), run (1, 4, 67), walk (6 to 8) or hike (9, 10) has environment `outdoor`; a session takes its primary record's environment.

Detailed contract: Terrain (road, trail, track, gravel, mountain, treadmill, pool, open water, unknown), assist (none, electric, unknown) and `native_type` (the provider type name or id, at most 64 characters) are stored in the record's details; a type a provider table knows without naming assistance is assist `none`, an unknown type is `unknown`. A session takes its primary record's terrain unless that is unknown and another record knows it; it is electric whenever any record is, since a generic type such as a plain ride maps to assist `none`. The session summary, the session analysis and the Coach activity list carry the terrain when known and `assist` only as `electric`; comparable sessions compare trail runs only with trail runs.

Evidence: `backend/canonical/vocabulary.py:Terrain`, `backend/canonical/vocabulary.py:Assist`, `backend/canonical/records.py:session_terrain`, `backend/providers/garmin_activity_mapping.py:GARMIN_ACTIVITY_QUALIFIERS`, `backend/providers/wahoo_activity_mapping.py:WAHOO_WORKOUT_QUALIFIERS`, `backend/performance/critical_power.py:critical_power_speed`, `backend/performance/load.py:activity_rollup`; `tests/test_activity_qualifiers.py`, `tests/test_mean_max_curve.py:test_e_bike_sessions_stay_out_of_the_bests_and_fits`, `tests/test_garmin_activity_mapping.py:test_known_key_environment_is_refined_by_name_when_unknown`, `tests/test_garmin_activity_mapping.py:test_every_table_entry_maps_to_its_sport_and_environment`, `tests/test_wahoo_activity_mapping.py:test_each_workout_type_maps_to_its_sport_and_environment`.

### Requirement: Activity field and load semantics
The system SHALL retain distinct moving and elapsed durations from every provider, distance in metres, power in watts, heart rate in bpm, ascent in metres, speed in metres per second, cadence in rpm, energy in kJ where mapped, and provider-specific load models. Wahoo SHALL use summary active duration before total duration and never use planned workout minutes as completed duration.

#### Scenario: Planned versus completed Wahoo duration
- **WHEN** a workout has planned minutes but no processed summary duration
- **THEN** actual duration remains unknown rather than using the plan as a measurement.

#### Scenario: Listed Wahoo workout without a recording
- **WHEN** Wahoo lists a workout without any measured duration, distance, heart rate, power or TSS, such as an unprocessed copy or a loaded plan that was never recorded
- **THEN** it is not stored as a completed activity and a copy stored earlier is tombstoned only when that copy holds no measured value either, so the calendar shows no extra activity; once a later sync brings its summary, the activity is stored or revived and linked as usual. A workout whose summary offers a recording file is a recording and is never withdrawn.

#### Scenario: Elapsed duration beside moving duration
- **WHEN** a Wahoo workout has both an active and a total duration, or a Garmin activity has `elapsedDuration` (else `duration`) and a `movingTime` timer alias
- **THEN** the total or `elapsedDuration` is stored as the elapsed duration and the moving time is not.

#### Scenario: Garmin strength session duration
- **WHEN** a Garmin strength activity has an active timer `duration` and a longer `elapsedDuration`
- **THEN** `elapsedDuration` is stored as the elapsed duration, and as the activity duration, so rest between sets counts; Wahoo strength sessions follow the same rule.

#### Scenario: Provider loads differ
- **WHEN** a stored Intervals.icu training load and Wahoo TSS describe copies of a session
- **THEN** their canonical values retain their respective load models and provenance rather than being relabeled as interchangeable measurements.

Detailed contract: Wahoo work in joules SHALL convert to kJ; zero ascent remains measured, while zero unsupported/unmeasured summary power, cadence, energy, and TSS remain absent under its mapper rules.

Evidence: `backend/providers/garmin_activity_mapping.py:map_garmin_activities`, `backend/providers/wahoo_activity_mapping.py:map_wahoo_activities`; `tests/test_wahoo_activity_mapping.py:test_summary_metrics_map_from_decimal_text`, `tests/test_wahoo_activity_mapping.py:test_planned_minutes_are_never_the_duration`, `tests/test_garmin_activity_mapping.py:test_strength_duration_is_the_whole_session_not_the_active_timer`, `backend/providers/canonical_plans.py:wahoo_ingest_plan`, `backend/sync/canonical_ingest.py:ingest_plan`, `tests/test_wahoo_activity_mapping.py:test_workouts_without_a_measured_value_are_withdrawn`, `tests/test_session_linking.py:test_a_stored_placeholder_is_withdrawn_and_revived_with_its_summary`, `tests/test_session_linking.py:test_a_stored_recording_listed_without_its_summary_is_kept`, `tests/test_wahoo_activity_mapping.py:test_a_workout_with_a_recording_file_is_never_withdrawn`.

### Requirement: One activity duration and cadence meaning
The system SHALL fill the activity duration by one rule for every provider: moving time, else timer time, else elapsed time, and the elapsed time when it is longer for strength. Cadence SHALL be rpm, counting one leg per minute for runs, never steps per minute.

#### Scenario: Garmin moving time beside its timer time
- **WHEN** a Garmin activity has `movingDuration` and a longer timer `duration`
- **THEN** since Garmin activity mapper 12 the activity duration is the moving time, as for Wahoo, and session bundling also compares the two elapsed times of a Garmin and a Wahoo record.

#### Scenario: Strength session from any provider
- **WHEN** a Wahoo or Garmin strength session has a moving or timer time shorter than its elapsed time
- **THEN** the activity duration is the elapsed time, so rest between sets counts.

Evidence: `backend/canonical/records.py:activity_duration_s`, `backend/activities/canonical_sessions.py:_duration_gap`; `tests/test_canonical_records.py:ActivityDurationRuleTests`, `tests/test_garmin_activity_mapping.py:test_moving_duration_comes_from_moving_duration_only`, `tests/test_canonical_wahoo_sessions.py:test_moving_and_elapsed_durations_are_candidates`.

### Requirement: Garmin activity summary values
The system SHALL map the Garmin activity list's zone times, training-effect values, altitude extremes, elevation loss, temperature range, estimated sweat loss, lap count and average cadence onto the canonical activity record, so Garmin-only sessions carry them with the Garmin Connect source label.

#### Scenario: Garmin run with zone times and extremes
- **WHEN** a Garmin activity row carries `hrTimeInZone_1..5`, `aerobicTrainingEffect`, `minElevation`/`maxElevation`, `minTemperature`/`maxTemperature` and `averageRunningCadenceInStepsPerMinute`
- **THEN** since Garmin activity mapper 14 the record carries heart-rate zones `Z1..Z5` by Garmin's own zones, the effect values on Garmin's 0.0-5.0 scale beside the effect label, both extremes, and the cadence halved to one-leg rpm; stored rows gain them by reprojection without a refetch.

#### Scenario: Inconsistent Garmin extremes
- **WHEN** a Garmin minimum altitude or temperature lies above its maximum, or one zone time is invalid
- **THEN** that pair or zone distribution is dropped with one mapping issue, and the rest of the record is kept.

Evidence: `backend/providers/garmin_activity_mapping.py:map_garmin_activities`, `backend/activities/activity_summary.py:activity_summary`, `backend/activities/detail_contract.py:activity_detail_contract`; `tests/test_garmin_activity_mapping.py:ZoneEffectAndExtremeTests`, `tests/test_activity_summary.py:test_effect_values_and_garmin_extremes_reach_the_summary`, `tests/test_activity_detail_contract.py:test_garmin_summary_values_are_labelled_metrics`.

### Requirement: Health and body unit normalization
The system SHALL normalize Garmin health and body values to canonical units using supported aliases and plausible bounds. Weekly HRV SHALL not stand in for a last-night reading. Declared grams, pounds and kilograms SHALL convert to kg and body-fat fractions to percent, with bounded magnitude interpretation only for undeclared units.

#### Scenario: Normalized Garmin kinds
- **WHEN** Garmin supplies sleep duration and score, night SpO2, respiration and sleeping heart rate, last-night RMSSD, weekly HRV average, resting heart rate, readiness, body measurements, daily counts and energy, VO2max, thresholds, race predictions or endurance score
- **THEN** each is mapped through its supported aliases and plausible bounds, and an invalid value is dropped with a content-free issue.

#### Scenario: Garmin personal records
- **WHEN** Garmin's personal records include running records
- **THEN** the records of the types the pinned SDK documents as 1 km (1), 5 km (3), 10 km (4), half marathon (5) and marathon (6) become `personal_record_1k`, `_5k`, `_10k`, `_half` and `_full` in seconds, each dated by its own local start day; other sports, the mile and the longest run are skipped, and another running type or a record without a day is a content-free issue.

#### Scenario: Declared weight unit
- **WHEN** a valid Garmin weigh-in explicitly declares pounds or grams
- **THEN** canonical weight is converted once to kilograms and its dated provenance is retained.

#### Scenario: Several Garmin readiness readings per day
- **WHEN** Garmin lists several training-readiness readings for one day
- **THEN** a reading flagged as a re-score after exercise or a real-time update never becomes READINESS, even when stored and re-projected alone; of the rest, READINESS and its level, in the canonical and legacy reads, come from the scored reading flagged as taken after waking, else the earliest timed scored reading, else the first listed.

#### Scenario: Manually entered Garmin weigh-in
- **WHEN** a Garmin weigh-in declares `sourceType` `MANUAL`
- **THEN** its weight is provider-reported and recorded by manual entry rather than a device measurement; the performance-history weight copy, which carries no source type, is provider-reported too.

#### Scenario: Different HRV windows
- **WHEN** a payload has only a weekly HRV average and no last-night value
- **THEN** the canonical last-night observation stays absent rather than borrowing the weekly statistic, and the weekly average is stored as its own weekly HRV observation.

#### Scenario: Garmin night SpO2, respiration and sleeping heart rate
- **WHEN** a Garmin sleep element carries `averageSpO2Value`, `lowestSpO2Value`, `averageRespirationValue` or `avgHeartRate`, at top level or in its `dailySleepDTO` (the SDK element and the wrapped flat Personal API `dailySleep` alike)
- **THEN** each becomes a device-measured SPO2 (mean), SPO2_LOWEST (minimum), RESPIRATION_RATE (mean) or SLEEPING_HR (mean) observation with the `overnight` window on the night's date; a 0 value is "not measured" and yields nothing without an issue, and Garmin's whole-day pulse-ox and respiration summaries are not mapped to these kinds.

#### Scenario: Stored Garmin health records after the weekly HRV mapping
- **WHEN** the Garmin health mapper version changes to add the weekly HRV kind
- **THEN** stored Garmin health records are reprojected through the existing canonical backfill without a provider refetch, schema change or remote write.

Detailed contract: Zero SHALL remain valid for sleep score, steps, floors, and active energy where implemented, while absent or invalid measurements remain unknown.

Evidence: `backend/providers/garmin_health_mapping.py:map_garmin_health`; `tests/test_garmin_health_mapping.py:test_weight_converts_declared_units_to_kilograms`, `tests/test_garmin_health_mapping.py:test_wake_up_reading_wins_regardless_of_list_order`, `tests/test_garmin_health_mapping.py:test_manual_weigh_in_is_provider_reported_and_recorded_by_manual`, `tests/test_garmin_health_mapping.py:test_hrv_prefers_last_night_and_ignores_weekly_average`, `tests/test_garmin_health_mapping.py:test_zero_sleep_score_is_kept`, `tests/test_garmin_health_mapping.py:SleepNightValueTests`, `tests/test_garmin_health_mapping.py:test_daily_stats_map_counts_and_energy_with_units`.

### Requirement: Current thresholds and dated special metrics
The system SHALL keep FTP and threshold sport scope, Garmin scaled running speed conversion to canonical m/s, display conversion to seconds/km, date-bearing historical FTP, running race-prediction seconds, and endurance-score wrapper normalization. An undated current Garmin FTP, running threshold, zone maximum, or prediction may use the fetch's local day only in its implemented current-value path. Undated current FTP SHALL never invent historical FTP.

#### Scenario: Current FTP without history date
- **WHEN** Garmin returns an undated current FTP together with no dated historical FTP record
- **THEN** the current reading may be dated to the local fetch day and historical gaps remain empty.

#### Scenario: Garmin FTP history range records
- **WHEN** stored Garmin FTP history holds biometric range records with `from` and `value`
- **THEN** since Garmin health mapper version 14 each becomes a ride FTP observation on its `from` day, reprojected without a provider refetch; a bare `value` without `from` is not FTP.

#### Scenario: Running threshold power under one kind
- **WHEN** Garmin or Wahoo report a running threshold power
- **THEN** since Garmin health mapper version 17 each is FTP with sport run; Garmin rows stored earlier under the legacy run threshold power kind stay readable as the run FTP until replay re-projects them.

#### Scenario: Multiple Wahoo zone revisions
- **WHEN** Wahoo returns multiple power-zone sets for one supported family
- **THEN** the newest update time wins, later input wins an equal-time tie, and only that selected source row supplies the FTP observation.

#### Scenario: Garmin performance values at ingest
- **WHEN** the Garmin sync merges a fetched payload into the performance history
- **THEN** it reads the latest-value sections through the Garmin health mapper and keeps cycling FTP and running threshold power within 50 to 700 W, threshold heart rate within 80 to 230 bpm, the profile maximum heart rate within 80 to 250 bpm and VO2max within 20 to 100, and drops other values; a race prediction counts within 60 to 100,000 s (a larger number is read as milliseconds), a threshold pace within 120 to 900 s/km (a value below 1 is read as 100 / value, below 20 as metres per second) and a weight within 30 to 300 kg (pounds x 0.45359237, an undeclared value above 300 as grams).

#### Scenario: Performance history retention
- **WHEN** the merge stores the performance history
- **THEN** it keeps one entry per observed day and the newest 90; past FTP values come only from the FTP range of the last 90 days (points of 20 to 2000 W at two decimals), and the current FTP is never written into earlier days. Each provider metric series reports `current`, `stale`, `failed`, `unsupported` or `unknown`.

Detailed contract: Wahoo SHALL map the newest power-zone set per cycling/running family to FTP dated on the athlete-local day of the set's `updated_at`, and the profile weight to the athlete-local day of the fetch; it SHALL not infer zone boundaries or other profile metrics from them.

Evidence: `backend/providers/garmin_health_mapping.py:map_garmin_health`, `backend/performance/garmin_canonical.py:garmin_thresholds`, `tests/test_current_thresholds.py:test_garmin_run_power_is_one_ftp_kind_with_the_legacy_kind_readable`, `backend/providers/wahoo_threshold_mapping.py:select_power_zone_sets`, `backend/providers/wahoo_threshold_mapping.py:map_wahoo_power_zones`; `tests/test_garmin_health_mapping.py:test_latest_ftp_without_a_date_uses_the_sync_day_only_for_current`, `tests/test_garmin_health_mapping.py:test_ftp_history_reads_biometric_range_records`, `tests/test_garmin_health_mapping.py:test_scaled_running_speed_is_stored_as_metres_per_second`, `tests/test_garmin_health_mapping.py:test_wrapped_endurance_score_is_mapped`, `tests/test_wahoo_threshold_mapping.py:test_the_newest_zone_set_of_each_family_is_kept_in_input_order`, `tests/test_wahoo_threshold_mapping.py:test_the_profile_is_dated_on_the_local_day_of_the_fetch`.

Added evidence:
- `backend/performance/activity_validation.py:bounded_performance_metric`
- `backend/performance/garmin_canonical.py:_pace_seconds_per_km`
- `backend/performance/garmin_canonical.py:_profile_max_hr`
- `backend/providers/garmin_health_mapping.py:_race_seconds`
- `backend/providers/garmin_health_mapping.py:_weight_kg`
- `backend/sync/garmin_performance_history.py:_ftp_history`
- `backend/sync/garmin_performance_history.py:_provider_metric_state`
- `backend/sync/garmin_performance_history.py:append_garmin_performance_history`
- `backend/sync/garmin_performance_history.py:current_garmin_metrics`
- `tests/test_garmin_health_parity.py:test_legacy_ingest_shapes_the_mapper_does_not_read`
- `tests/test_garmin_performance_history_canonical.py:test_the_history_reprojects_to_the_pinned_observations_and_context`
- `tests/test_garmin_health_parity.py:test_race_predictions_match_legacy_seconds`
- `tests/test_garmin_health_parity.py:test_threshold_pace_converts_to_legacy_seconds_per_kilometre`
- `tests/test_performance_history.py:test_historical_ftp_rows_are_added_without_backfilling_current_ftp`
- `tests/test_performance_history.py:test_retains_sorted_last_90_dates_and_uses_explicit_current_date`
- `tests/test_provider_garmin_metric_history.py:test_missing_capabilities_are_explained_without_failing_other_sources`

### Requirement: Metric-specific source priority and local authority
The system SHALL apply per-metric source rules rather than a universal provider order. A locally confirmed zone configuration precedes every provider for thresholds. Intervals.icu is never a source. Current ride FTP prefers Garmin, with Wahoo last; threshold and maximum heart rate, threshold pace, run power and VO2max are Garmin's. Weight is Garmin's newest weigh-in, else the profile value, else Wahoo's profile weight; body fat is Garmin's newest value, else the profile value.

#### Scenario: Three FTP sources
- **WHEN** eligible Intervals.icu, Garmin, and Wahoo cycling FTP values coexist and no local zone configuration applies
- **THEN** current metric composition selects Garmin's, labels its provider, lists the Wahoo value as an alternative with a conflict flag above 3 %, and ignores the Intervals.icu value, also for the dated thresholds of the local session load.

#### Scenario: Old Wahoo fallback
- **WHEN** Wahoo is the only eligible source but its dated value is older than the current-value age limit
- **THEN** the current selector returns no Wahoo value while historical storage remains intact.

#### Scenario: Stale threshold sources
- **WHEN** a Garmin threshold was observed more than 180 days before the local day
- **THEN** that value is not current and the next source in the rule's order supplies the threshold.

#### Scenario: A newer scale reading via Intervals.icu
- **WHEN** Intervals.icu wellness holds today's weight and Garmin's newest weight is three days old
- **THEN** the current weight is Garmin's; the Intervals.icu weight is neither current nor an alternative.

#### Scenario: Plausibility bounds
- **WHEN** a value is a candidate for the current or the daily selection
- **THEN** it must lie within its kind's inclusive bounds before ranking: FTP 50 to 700 W (Garmin and Wahoo), threshold heart rate 80 to 230 bpm, maximum heart rate 80 to 260 bpm, resting heart rate 30 to 230 bpm, RMSSD and weekly HRV 1 to 300 ms, sleep score 0 to 100 and VO2max 20 to 100; the chart series, the power-to-weight series and the Garmin readers apply the same bound per kind, with a threshold pace of 120 to 900 s/km, run threshold power as FTP, Garmin weight of 30 to 300 kg and body fat of 2 to 70 %.

#### Scenario: Ranking inside one provider
- **WHEN** one provider has several values of a kind
- **THEN** weight takes the newest day, then the latest time, then the last record; other dated kinds take the newest day, then the last Garmin record or the first record of another provider; FTP, thresholds, maximum heart rate and VO2max ignore the day and take the last Garmin record or the first record of another provider; a per-day selection takes the first record of the day.

#### Scenario: Age counting and weight conflict
- **WHEN** a value is exactly at its age limit (180 days for a Garmin threshold, 90 days for a Wahoo FTP or weight), or two sources' current weights differ by more than 1.5 kg
- **THEN** the age counts whole days, so a value exactly at its limit is still current; Garmin weight has no age limit and without a day no limit applies; the alternative weight carries the conflict flag.

Detailed contract: Only Garmin weight and body-fat values are dated, so a Garmin weigh-in of any age precedes a profile value entered later. Within one day of the newest weight or body fat, a device measurement precedes a provider report, which precedes a local entry; the manual profile value and Wahoo's profile weight are fallbacks in that order. Body fat follows the weight rule with a 2-percentage-point conflict tolerance; readiness, sleep, RMSSD, and resting HR are Garmin's (performance-and-readiness); CTL, ATL and form are local (M7) and have no source rule. Wahoo current FTP/weight older than 90 days SHALL be excluded when an as-of local day is supplied, without deleting history. The PWA display preference of weight, body fat, sleep, HRV, resting HR, threshold pace and VO2max is the first provider of that metric's rule; FTP and W/kg charts keep Garmin, whose FTP history they draw. Local profile and competition records SHALL retain their domain authority rather than being overwritten by provider read sync.

Evidence: `backend/performance/source_policy.py:CURRENT_RULES`, `backend/performance/source_policy.py:resolve_candidates`, `backend/performance/current_thresholds.py:resolve_current_thresholds`, `backend/performance/display_sources.py:preferred_providers`, `backend/performance/current_metrics.py:current_performance_metrics`, `backend/sync/authority.py:PlanningAuthorityService`; `tests/test_current_thresholds.py`, `tests/test_source_policy.py:RecencyResolutionTests`, `tests/test_performance_current_metrics.py:test_garmin_ftp_beats_wahoo_ftp_and_intervals_is_ignored`, `tests/test_performance_current_metrics.py:test_manual_profile_weight_beats_wahoo_weight`, `tests/test_performance_display_sources.py`, `tests/test_sync_authority.py:test_revision_failure_rolls_back_planning_update_atomically`. Added evidence: `backend/performance/activity_validation.py:PERFORMANCE_METRIC_BOUNDS`, `tests/test_source_policy.py:test_garmin_thresholds_tie_keeps_the_last_input`, `tests/test_source_policy.py:test_garmin_weight_is_not_age_limited`, `tests/test_source_policy.py:test_resting_hr_bounds_are_inclusive_at_30_and_230`, `tests/test_source_policy.py:test_wahoo_ftp_at_89_and_90_days_is_current_but_91_days_is_not`, `tests/test_source_policy.py:test_wahoo_thresholds_tie_keeps_the_first_input`.

### Requirement: Correction and reprojection continuity
The system SHALL preserve provider raw-record identity and mapper version, ingest canonical data with the owning provider transaction, and reproject stored records on mapper/timezone changes. Before the first successful canonical backfill, canonical reads SHALL return no values and consumers SHALL report a pending state; after first completion, reads SHALL continue from tables during later reprojection/failure rather than disappearing or becoming pending again.

#### Scenario: Mapper update after completed backfill
- **WHEN** a new mapper version requires reprojection
- **THEN** stored table values remain readable while batches create corrected observations and current versions take precedence as available.

#### Scenario: Provider clears or deletes a value
- **WHEN** a sync or reprojection maps a raw record again (a Garmin health element or a Wahoo threshold record) and it no longer emits an observation that record owns
- **THEN** the observation is retired: it stays stored and in backups, but no canonical read, Coach context or readiness serves it; a later projection that emits it again makes it active. A record retires only on the days it speaks for: its own day (a dated element) or, for a dateless snapshot (athlete profile, Wahoo profile, a whole Garmin section), its fetch day, plus the days it still emits; values of earlier days stay as history. A raw record the sync did not fetch (failed, skipped or empty section) retires nothing, and an observation another record emits or without an owner is untouched.

#### Scenario: Garmin weigh-in deleted in Garmin Connect
- **WHEN** a complete Garmin weight fetch for a day window no longer returns a stored weigh-in or daily weight summary of a window day
- **THEN** the stored weight section drops it and its observation is retired; readings of other days and undated readings stay, and an incomplete, failed or empty fetch changes nothing.

#### Scenario: First backfill has not completed
- **WHEN** initial backfill is pending, running, or failed
- **THEN** activities, activity rows and summaries, observations, metric windows and the chosen reader return nothing, coverage reports only current persisted summaries, and performance and Coach contexts mark the unavailable canonical data instead of presenting partial values. A failure is reported as such and the worker retries after a delay from the last committed cursor without requiring a restart.

#### Scenario: Read state is decided from the backfill state alone
- **WHEN** a canonical read is served
- **THEN** the state is `pending` until the backfill completed once (marker `completed_once`, or a stored status `complete` from before the marker existed), `tables` while the stored mapper versions and zone equal the current ones, and `tables_reprojecting` otherwise; a missing or corrupt state record reads as `pending`.

#### Scenario: Failure after a first completion
- **WHEN** a batch fails after the backfill completed once
- **THEN** the completion marker is kept and reads stay on the tables.

#### Scenario: Mapper raises on one stored record
- **WHEN** a mapper raises for one raw record during re-projection
- **THEN** nothing is written for it, its mapped version stays behind, it is counted as `skipped_invalid`, the pass completes and the follow-up stages run; its observations of the older version stay stored but are not served once the pass completed, and its activity rows stay served.

Detailed contract: No legacy snapshot projection serves reads. Reprojection SHALL preserve session ownership and mark retired or invalid mapped records without deleting original provider evidence.

Evidence: `backend/sync/canonical_ingest.py:ingest_plan`, `backend/sync/canonical_backfill.py:CanonicalBackfill`, `backend/sync/canonical_read_selector.py:CanonicalReadSelector`; `tests/test_canonical_read_selector.py:test_observations_stay_available_until_the_reprojection_completes`, `tests/test_canonical_read_selector.py:test_first_backfill_not_complete_serves_nothing_from_filled_tables`, `tests/test_canonical_backfill.py:test_a_dropped_activity_is_invalid_and_a_later_version_restores_it`, `tests/test_canonical_backfill.py:test_retry_preserves_committed_cursor_and_finishes`, `tests/test_performance_canonical_parity.py:test_failed_first_backfill_is_visible_but_completed_data_stays_available`, `tests/test_observation_retirement.py:test_a_failed_or_skipped_garmin_section_retires_nothing`, `tests/test_garmin_snapshot_writer.py:test_a_complete_window_retires_the_deleted_weigh_in_only`.

Added evidence:
- `backend/sync/canonical_backfill.py:CanonicalBackfill.mark_failed`
- `backend/sync/canonical_backfill.py:ReadState`
- `backend/sync/canonical_backfill.py:_complete_reprojection`
- `backend/sync/canonical_backfill.py:read_state`
- `tests/test_canonical_backfill.py:test_a_raising_mapper_leaves_the_old_observations_stored_but_hidden`
- `tests/test_canonical_backfill.py:test_a_raising_mapper_skips_only_that_record_and_the_pass_completes`
- `tests/test_canonical_read_selector.py:test_a_failure_keeps_a_completion_that_predates_the_marker`
- `tests/test_canonical_read_selector.py:test_a_state_complete_without_the_marker_counts_as_completed_once`
- `tests/test_canonical_read_selector.py:test_corrupt_backfill_status_reads_as_never_completed`

### Requirement: Provenance and incomplete coverage remain visible
The system SHALL expose source labels, observation dates, retrieval freshness, and missing or unsupported coverage without synthesizing measurements. Canonically mapped Garmin status, load balance and Body Battery SHALL retain provider-estimate labels, their supported measurement windows and explicit partial coverage.

#### Scenario: Source not canonically supported
- **WHEN** a stored Garmin section contains an unsupported field
- **THEN** coverage records the limitation and consumers do not advertise complete support for that field.

#### Scenario: Derived value displayed
- **WHEN** a detail average is calculated from samples or a load value carries a provider calculation
- **THEN** its public document includes the corresponding source and kind/model rather than presenting it as an athlete-entered measurement.

Detailed contract: Public metric names SHALL be provider-neutral while source labels identify origin, derived values, and AI estimates when present.

Evidence: `backend/canonical/records.py:Provenance`, `backend/canonical/coverage.py:ProviderCoverage`, `backend/sync/canonical_coverage_store.py:CanonicalCoverageStore`, `backend/sync/canonical_table_reader.py:CanonicalTableReader`, `backend/activities/zone_settings.py`; `tests/test_canonical_records.py`, `tests/test_canonical_store.py`, `tests/test_garmin_health_mapping.py`, `tests/test_canonical_rollback_prerequisites.py:test_persisted_value_holds_counts_only`.

### Requirement: Reproducible observation metadata
Canonical observations SHALL round-trip optional method, aggregation, method version, input fingerprint and observation-period metadata. Derived observations MUST supply a method, version and input fingerprint. Numeric and categorical provider values SHALL remain distinct, validated values.

#### Scenario: Metadata survives storage
- **WHEN** a valid observation with method metadata and a bounded period is stored and read again
- **THEN** its value, source, method, version, aggregation, fingerprint and period remain unchanged.

#### Scenario: Incomplete derived record
- **WHEN** a derived observation lacks its method, version or input fingerprint
- **THEN** validation rejects it before persistence.

#### Scenario: Mapper method correction
- **WHEN** stored provider records are reprojected by a newer mapper
- **THEN** provider-fixed HRV method and aggregation metadata are populated without refetching or changing displayed measurements and labels; obsolete projections do not appear current.

Evidence: `backend/canonical/records.py:Observation`, `backend/canonical/records.py:ObservationPeriod`, `backend/canonical/records.py:fingerprint_inputs`, `backend/db/canonical_store.py:upsert_observation`; `tests/test_canonical_observation_metadata.py:ObservationMetadataTests.test_derived_observations_name_method_version_and_inputs`, `tests/test_canonical_observation_metadata.py:ObservationMetadataStoreTests.test_metadata_and_context_round_trip_through_store_and_reader`, `tests/test_canonical_observation_metadata.py:ObservationMetadataStoreTests.test_metadata_and_context_changes_update_the_row_under_its_key`.

### Requirement: Canonical sleep periods
Canonical sleep periods SHALL retain aware UTC start/end, local wake date, night/unknown kind, reported duration and provenance, and the ingest timezone only when it gives that wake date. The wake date SHALL be the provider's own day (Garmin `calendarDate`) when it lies within a day of the end's UTC date, else the end's date in the ingest zone. Invalid or reversed periods SHALL be rejected. Periods from different providers SHALL remain separate.

#### Scenario: Midnight and DST
- **WHEN** a valid period crosses midnight or a DST transition
- **THEN** its instants preserve actual duration and its assigned date is the wake date in the recorded timezone.

#### Scenario: Missing nights and overlapping providers
- **WHEN** nights are missing or two providers overlap
- **THEN** no missing night is fabricated and provider periods are not silently merged.

#### Scenario: Garmin main sleep during daytime
- **WHEN** Garmin identifies a period as its main daily sleep episode, including daytime sleep for a shift worker
- **THEN** its canonical kind is NIGHT, meaning main sleep rather than a clock-night classification; arbitrary periods are not classified by hour or duration.

#### Scenario: Travel night
- **WHEN** the athlete wakes at 06:00 in Tokyo with profile zone Europe/Berlin and Garmin files the night under that Tokyo day
- **THEN** the period's wake date is the Tokyo day, the same day as the morning run recorded there, and it keeps no timezone because Berlin names another day.

Evidence: `backend/providers/sleep_period_mapping.py:map_sleep_periods`, `backend/canonical/domain_records.py:SleepPeriod`; `tests/test_sleep_period_mapping.py`, `tests/test_activity_local_offset.py:TravelDaySleepTests`.

### Requirement: Explicit measurement context and continuity
Observations and activities SHALL preserve supported device model, firmware, algorithm, sensor, measurement window and protocol, explicitly representing unavailable context as unknown. Canonical readers SHALL expose a deterministic context identity so downstream consumers can identify changes. Context SHALL not infer device or protocol from the provider brand or expose device serials.

#### Scenario: Device changes mid-series
- **WHEN** two otherwise comparable observations have different known device or measurement context
- **THEN** their canonical context identities differ and the continuity break is visible to readers.

#### Scenario: Provider omits context
- **WHEN** a payload omits device or protocol information
- **THEN** reads report unknown context rather than a guessed device, sensor or protocol.

#### Scenario: Known measurement semantics without hardware attribution
- **WHEN** Garmin last-night HRV supplies the established RMSSD measurement but no trustworthy measurement-associated hardware fields
- **THEN** canonical metadata preserves the RMSSD method and overnight window while device model, firmware and sensor remain explicitly unknown; inventories and primary-device selection do not fill those fields.

Evidence: `backend/canonical/records.py:MeasurementContext`, `backend/canonical/records.py:Observation`; `tests/test_canonical_observation_metadata.py:MeasurementContextTests.test_the_identity_is_stable_and_changes_with_every_field`, `tests/test_canonical_observation_metadata.py:MeasurementContextTests.test_device_identifiers_and_free_text_are_rejected`, `tests/test_canonical_observation_metadata.py:ObservationMetadataStoreTests.test_a_device_change_mid_series_is_a_visible_continuity_break`, `tests/test_garmin_training_mapping.py:test_unresolved_devices_are_reported_as_a_coverage_gap`.

### Requirement: Canonical sport zone configuration
Canonical zone configuration SHALL retain sport, metric, boundaries in canonical units, model, source and validity date. Provider and confirmed local configurations SHALL remain separately readable. Effective selections SHALL prefer applicable confirmed local values and SHALL never promote CP/CS into FTP, lactate threshold or zone-2 boundaries automatically.

#### Scenario: Canonical-only calendar and plan
- **WHEN** canonical zones exist without a provider snapshot
- **THEN** calendar, plan and affected time-in-zone calculations use those boundaries and retain source labels.

#### Scenario: Local configuration and provider refresh
- **WHEN** provider zones are refreshed after a confirmed local edit
- **THEN** local values retain authority and the refreshed provider alternative remains available separately.

#### Scenario: Garmin watch heart-rate zones
- **WHEN** Garmin reports heart-rate zone sets (`DEFAULT`, `RUNNING`, `CYCLING`) on any calculation basis, such as percent of the lactate threshold HR, heart-rate reserve or maximum HR
- **THEN** each set becomes a canonical heart-rate zone configuration valid from the local day it was first fetched, with Garmin's absolute bpm floors taken as they are (zone N ends one bpm below the floor of zone N + 1, the top zone at the maximum HR) and the basis kept as its model; a changed set of one sport is a new configuration (an unchanged set is not stored again) and the earlier ones stay valid for their days; Garmin leads Wahoo, a confirmed local configuration still wins, a sport's own set precedes Garmin's default set, a day before the first fetch takes the earliest later set within 90 days, and the standard limits apply only without any configuration.

#### Scenario: Target range of planned steps
- **WHEN** a planned unit's step targets a zone, a percent of a threshold, or absolute bpm or watts
- **THEN** its profile segment carries the range in bpm, W or s/km from the zones and thresholds in effect on the unit's day (a zone starts one above the zone below it, the lowest zone has no lower end, the open top zone no upper end); whole bpm and watts end at the last whole unit below the limit, so Garmin zones read as on the watch; a zone step without the athlete's own zones of that signal or outside their zone count, or any step without its threshold, carries no range.

#### Scenario: Thresholds without a zone configuration
- **WHEN** a planned workout's sport has no configuration for a metric
- **THEN** its FTP, threshold HR and maximum HR come from the source-policy provider winners (Garmin, Wahoo) with the default limits, never from Intervals.icu or the stored snapshot, and nothing is served before the first completed backfill.

Detailed contract (#1851): the watch zones are projected by `garmin_zone_mapping.py` with the Garmin health mapper version; the section accumulates, one element per changed set; absolute limits convert to percent of the threshold the settings carry with the operation order of the zone lookup, so a value on a limit stays in its zone.

Detailed contract (#1416): indoor and virtual workouts use the INDOOR power configuration's threshold, else the sport's FTP (no provider indoor FTP is read); the Ride FTP falls back to the athlete's configured FTP as the canonical current metrics do; zone lists and values the mappers reject leave the default limits or no threshold.

Evidence: `backend/performance/canonical_current.py:read_zone_thresholds`, `backend/activities/zone_settings.py:ZoneSettings.from_thresholds`, `backend/planning/calendar_read_model.py:project_planning_calendar`, `backend/activities/workout_profile.py:planned_profile`; `tests/test_workout_profile.py:test_planned_steps_carry_their_target_range_from_the_zones_of_the_day`, `tests/test_plan_zone_canonical_parity.py`, `tests/test_zone_configuration_canonical.py:EffectiveZoneTests`, `tests/test_zone_settings.py`; `backend/providers/garmin_zone_mapping.py:map_garmin_heart_rate_zones`, `backend/activities/zone_settings.py:effective_zone_configuration`; `tests/test_garmin_zone_mapping.py`.

### Requirement: Retained provider domains and equipment links
Training status and load balance, running tolerance, readiness history, endurance score details/history, performance history, Body Battery, stress, resting energy, subjective provider wellness and equipment SHALL have canonical representations. Their affected consumers SHALL read canonical values with provider labels. Proprietary scores SHALL not be rebuilt locally; equipment links SHALL resolve to canonical sessions.

#### Scenario: Stored provider-only history
- **WHEN** existing provider records contain supported retained domains
- **THEN** local reprojection makes them available to canonical readers and affected consumers without network access or backdating current values.

#### Scenario: Provider resting energy
- **WHEN** a provider reports resting energy
- **THEN** it remains a labelled provider observation; absence does not trigger an unrequested local estimate.

#### Scenario: Garmin daily physiological stress
- **WHEN** an existing daily summary reports nested stress.avgLevel or flat averageStressLevel
- **THEN** canonical STRESS retains the daily provider mean, source date and established field precedence on the 0-100 scale, including valid zero, without a second stress fetch or substitution from subjective stress; missing or invalid values do not become measurements.

#### Scenario: Gear on duplicate imports
- **WHEN** provider gear links refer to copies of the same canonical session
- **THEN** equipment reads resolve those links through session identity without duplicating usage or overriding an explicit local assignment.

Evidence: `backend/providers/garmin_training_mapping.py:training_values`, `backend/providers/garmin_gear_mapping.py:map_garmin_gear`, `backend/providers/garmin_health_mapping.py:map_garmin_health`; `tests/test_garmin_training_mapping.py`, `tests/test_garmin_gear_mapping.py`, `tests/test_equipment_canonical_sessions.py:test_canonical_gear_keeps_the_partial_activity_list`.

### Requirement: Metric vocabulary accountability
Every metric kind SHALL have an implemented provider producer or a documented local method and a consumer or explicit export-only retention purpose. Retiring a kind SHALL preserve or migrate stored observations. Provider load-model vocabulary SHALL remain separate from local session-RPE methods.

#### Scenario: Unsupported vocabulary addition
- **WHEN** a kind is added without a producer/method or consumer/retention purpose
- **THEN** the vocabulary consistency check fails.

Evidence: `backend/canonical/vocabulary.py:UNPRODUCED_METRIC_KINDS`, `backend/canonical/vocabulary.py:EXPORT_ONLY_METRIC_KINDS`; `tests/test_canonical_vocabulary_accountability.py:VocabularyAccountabilityTests.test_every_metric_kind_has_a_producer_and_a_consumer_or_a_reason`, `tests/test_canonical_vocabulary_accountability.py:RetainedKindStorageTests.test_a_stored_unproduced_kind_is_still_read`, `tests/test_canonical_enum_retirement.py:EnumRetirementTests.test_stored_values_are_still_members_or_retired`.

### Requirement: Provider-neutral activity summary per session
The system SHALL give activity consumers one provider-neutral summary per live canonical session, built from the active records of every provider in it. Each value SHALL come from the best-ranked record that has it (measured values from the recording platform's own copy first, derived values by provider rank) and name its source label. Consumers outside the provider adapters, sync and canonical owners SHALL NOT read provider activity field names.

#### Scenario: Copies of one session
- **WHEN** Wahoo and Garmin Connect report a session that canonical linking bundled
- **THEN** consumers receive one summary with the local session id, the canonical sport and environment, and each value's source label.

#### Scenario: Recording relayed through Garmin Connect
- **WHEN** a Garmin Connect activity names a Wahoo or Zwift manufacturer
- **THEN** its origin is that manufacturer (any other manufacturer stays a Garmin recording), so the Wahoo recording, not the Garmin copy, wins the measured values; Wahoo rides that are not indoor or virtual, including such relayed copies, carry the bike computer device type, and Garmin's own recordings name none.

#### Scenario: Stored Intervals.icu record
- **WHEN** a session of a database restored from an earlier release still holds a stored Intervals.icu record
- **THEN** the readers leave it out (#2148): the Wahoo record, else the Garmin record, supplies the session's primary, measured values and laps, and the Intervals.icu record is no member of the summary.

#### Scenario: Load on different scales
- **WHEN** a session has only a Garmin training load
- **THEN** the summary has no provider TSS-like load, still counts its duration and distance, and loads of TSS-like models (Intervals.icu training load, TSS) are kept as `provider_training_load` with their `provider_load_model`.

#### Scenario: Served load is local
- **WHEN** a reader serves a session's summary
- **THEN** `training_load` and `intensity` are the stored local load and power IF (M6) labelled `derived`, never a provider value.

#### Scenario: Stored keys of a session
- **WHEN** a consumer looks up feedback, workout profiles or analyses of a summary
- **THEN** it uses the local session id, which the reference resolver returns for any reference to the session; rows stored under a provider record id are still found through the feedback and equipment lookups.

Detailed contract: the summary keys are the `ActivitySummary` keys listed in `docs/canonical-field-map.md` ("`ActivitySummary` keys"), each with its unit and source field; zone times are `{id, secs}` lists, and the served `training_load`, `intensity` and their load method keys come from the stored local load. The Garmin mapper stores the summary values in the record details, so the existing backfill re-maps stored rows; no schema change.

Evidence: `backend/activities/activity_summary.py`, `backend/sync/canonical_table_reader.py:CanonicalTableReader.activity_sessions`, `backend/sync/canonical_read_selector.py:CanonicalReadSelector.activity_summaries`; `tests/test_activity_summary.py`, `tests/test_canonical_table_reader.py:ActivitySessionReadTests`, `tests/test_garmin_activity_mapping.py:SummaryValueTests`, `tests/test_provider_coupling_guard.py`.

### Requirement: Consumers read canonical records, not raw provider views
Consumer packages (performance, Coach, HTTP API, planning, activities, athlete, nutrition) SHALL NOT read metric or detail values from the raw provider snapshot, its sections, the raw Garmin views or retired kv detail records; payload parsing SHALL live with its ingestion owner. An architecture guard SHALL enforce this with an explained allowlist that can only shrink.

#### Scenario: Allowlist reasons
- **WHEN** a consumer file keeps a raw read
- **THEN** its allowlist entry names one of the reasons `writer` (persists or ingests the raw snapshot), `export` (backup or privacy export), `sync-status` (freshness, not values), `legacy-label` (the view still emits a source label itself) or `owner` (the morning refresh keeps only its bookkeeping).

#### Scenario: A consumer adds a raw view read
- **WHEN** a module in a consumer package references `recent_wellness`, `raw_provider_data`, `read_view`, `recent_view`, `recent_view_in`, an `activity_detail:` key string, `latest_snapshot`, `garmin_store.read_state` or a quoted `garmin_snapshot` / `intervals_snapshot` key
- **THEN** the provider-coupling guard fails unless the file is allowlisted with an explained reason; docstrings and comments do not count.

#### Scenario: A raw read is removed
- **WHEN** an allowlisted file no longer makes the read
- **THEN** the guard reports its allowlist entry as stale until it is removed.

Detailed contract: rules `snapshot_key`, `legacy_read`, `source_label` and `field_module_import` in `tests/provider_coupling.py:OWNER_READ_ALLOWLIST`. No value read remains in the consumer packages (#1416): plan zones read canonical thresholds, equipment reads canonical gear items and links (a gear-listed Garmin activity links the rows of its canonical session; the sync no longer computes or reads `activity_matches`), and the energy views take a day's presence after a targeted refresh from its canonical Garmin totals; the stored snapshot is read there only for sync status (`provider_sync`, Garmin state).

Evidence: `tests/provider_coupling.py:scan_owner_reads`, `backend/sync/garmin_performance_history.py:current_garmin_metrics`, `backend/sync/garmin_performance_history.py:append_garmin_performance_history`; `tests/test_provider_coupling_guard.py:OwnerReadGuardTests.test_consumers_cannot_read_raw_provider_views`, `tests/test_provider_coupling_guard.py:OwnerReadGuardTests.test_allowlisted_raw_view_owner_passes_and_a_stale_entry_fails`, `tests/test_provider_coupling_guard.py:OwnerReadGuardTests.test_source_tree_reads_only_through_allowlisted_owners`.

### Requirement: Athlete-preferred source per metric group
The system SHALL let the athlete choose Garmin or the default (the newest measurement) as preferred source for weight and body fat, as a local profile setting with receipt and undo (also through the Coach's profile update); a stored `intervals` value is ignored. Every consumer SHALL apply it in the same read. The settings SHALL show only source controls that change an outcome (#2084).

#### Scenario: Preferred body source
- **WHEN** the athlete prefers Garmin for weight and body fat and a local entry is newer than Garmin's measurement
- **THEN** Garmin's value wins and the local entry stays an alternative; with the default the newer entry wins.

#### Scenario: Groups without a real choice
- **WHEN** the metric is a threshold, HRV, resting HR or sleep, where Garmin already leads (behind a locally confirmed zone configuration) or is the only source
- **THEN** the settings show no source control for it and a stored preference value is kept but changes nothing (athlete decision 2026-11-11).

#### Scenario: A stored Intervals.icu preference
- **WHEN** a stored profile holds `intervals` as a preferred source, and the athlete saves the profile with that value
- **THEN** the stored value is read as the default order and the save is rejected as an unknown source; stored profiles are not rewritten by reads.

Evidence: `backend/performance/source_policy.py:preferences_from_profile`, `backend/performance/source_policy.py:source_order`, `backend/athlete/profile.py:normalize_profile`, `backend/performance/canonical_inputs.py:CanonicalPerformanceSource`; `tests/test_source_policy.py:PreferredSourceTests`, `tests/test_source_policy.py:PreferredSourceTests.test_the_settings_show_one_control_per_effective_group`, `tests/test_performance_display_sources.py:PreferredDisplayTests`, `tests/test_athlete_profile.py:test_preferred_sources_accept_known_providers_only`, `tests/test_change_history.py:test_preferred_sources_are_audited_and_older_rows_stay_matchable`, `tests/test_performance_recovery_context.py:IntervalsIsNeverASourceTests.test_a_stored_intervals_preference_is_ignored`.

### Requirement: Activity purpose
The system SHALL classify why an activity was done as training, race, commute, warm-up or cool-down from Garmin's activity event type and stored competitions, never from Intervals.icu fields, and carry it with its source label on the session summary and the Coach activity list.

#### Scenario: Garmin event types name race and commute
- **WHEN** a Garmin activity list entry (unofficial SDK or Personal API) has `eventType.typeKey` `race` or `transportation`
- **THEN** its record has purpose race or commute; any other event type, a missing event type or a missing key leaves the purpose unset, and a key that is not text is one mapping issue.

#### Scenario: A race in any record wins
- **WHEN** the records of one session report different purposes
- **THEN** the session purpose is race if any record says race, else the first purpose in derived order, and `sources.purpose` names that record's provider.

#### Scenario: Intervals.icu classification is not read
- **WHEN** an Intervals.icu activity carries `sub_type`, `race` or `commute`
- **THEN** its record has no purpose.

#### Scenario: Commutes, warm-ups and cool-downs are never maximal efforts or plan completions
- **WHEN** a session has purpose commute, warm-up or cool-down
- **THEN** it stays out of the power and speed best values, mean-max curves, CP/CS fits and session comparisons, never completes a planned workout (a workout the provider paired with it stays open instead of matching another session by date), and a commute still counts in weekly volume, named again as `commute_sessions` and `commute_duration_s`.

#### Scenario: Races are flagged for analysis
- **WHEN** a session has purpose race
- **THEN** its curve record and CP/CS efforts carry `effort_context` "race", the activity detail session carries `purpose`, `competition_id` and `purpose_source`, and the session-analysis playbook judges pacing, fade and finish instead of interval execution.

Detailed contract: the purpose is stored in the record details (`purpose`), so no migration is needed; an unknown stored value is ignored on read. The Garmin activity mapper version 17 replays stored payloads. The Coach activity list adds `purpose_label` (Training, Wettkampf, Pendeln, Einfahren, Ausfahren). Warm-up and cool-down are reserved for the athlete's own marking, which is not yet implemented.

Evidence: `backend/canonical/vocabulary.py:ActivityPurpose`, `backend/providers/garmin_activity_mapping.py:_purpose`, `backend/activities/session_purpose.py:session_purpose`, `backend/db/canonical_store.py:activity_summary_values`, `backend/coach/context.py:compact_coach_activity`, `backend/performance/report_service.py:curve_records`, `backend/performance/critical_power.py:_select_efforts`, `backend/activities/matching.py:match_planned_workouts`, `backend/performance/progress_report.py:_bucket`, `backend/performance/activity_read_service.py:_add_purpose`, `backend/coach/playbooks.py`; `tests/test_session_purpose.py`, `tests/test_coach_activity_summary_parity.py`, `tests/test_activity_purpose_consumers.py`, `tests/test_mean_max_curve.py:test_commutes_stay_out_and_races_are_flagged`, `tests/test_critical_power.py:EffortContextTests`, `tests/test_activity_matching.py:test_commutes_and_warmups_never_complete_a_planned_workout`.

### Requirement: Observation identity, ownership and write rules
The system SHALL store one observation row per natural key `provider|metric|sport|series|(observed_at or observed_on)`, with empty text for absent parts. A write SHALL insert, update in place or leave the row unchanged, and SHALL make a retired row active again. Each provider row SHALL name the raw record that emitted it as its owner. Domain rows (sleep periods, statuses, zone configurations, gear) SHALL be replaced per source record.

#### Scenario: Two values with one key in one payload
- **WHEN** one ingest plan maps two observations to the same natural key
- **THEN** the first is written, the later one is skipped and counted as `skipped_invalid`.

#### Scenario: History value beside a dedicated section
- **WHEN** a fill-only observation (Garmin `performance_history`) meets an active row that another source record wrote at the same or a newer mapper version
- **THEN** the stored row stays; the fill-only value only inserts, updates its own row, revives a retired row or replaces a row left at an older mapper version.

#### Scenario: Local per-session value
- **WHEN** a locally derived per-session kind (session load, intensity factor, efficiency factor, variability index, mechanical work, aerobic decoupling, the five activity weather kinds) is stored without a provider
- **THEN** its series is `session:<session id>`, so two sessions with the same sport and start keep separate rows.

#### Scenario: Domain rows of a corrected record
- **WHEN** a raw record is projected again
- **THEN** the rows it emits are written or updated, active rows of that source record it no longer emits are retired, a row that another source record of the same provider now emits moves to that record, and local zone configurations are untouched.

#### Scenario: Domain batch without its raw record
- **WHEN** an ingest or re-projection plan carries domain rows for a source record that the same plan does not carry as a raw record
- **THEN** the plan is rejected and nothing of it is written.

#### Scenario: Deleted raw record at re-projection
- **WHEN** a mapper version bump re-projects the stored records
- **THEN** a raw record marked deleted is not re-projected and its domain rows stay as they are.

Detailed contract: retirement of observations that an owner no longer emits runs before the writes of an ingest, so a value that another record still emits is written again instead of staying retired. The plausibility bounds of the current-value rules are in "Metric-specific source priority and local authority"; the stored columns are in `docs/schema-reference.md`.

Evidence:
- `backend/db/canonical_domain_store.py:replace_source_rows`
- `backend/db/canonical_store.py:observation_natural_key`
- `backend/db/canonical_store.py:upsert_observation`
- `backend/sync/canonical_ingest.py:ingest_plan`
- `tests/test_canonical_domain_ingest.py:test_a_batch_without_its_raw_record_is_rejected`
- `tests/test_canonical_domain_ingest.py:test_deleted_raw_records_keep_their_rows`
- `tests/test_canonical_domain_store.py:test_a_provider_replace_keeps_local_configurations`
- `tests/test_canonical_domain_store.py:test_a_row_another_source_record_emits_moves_to_that_record`
- `tests/test_canonical_ingest.py:test_duplicate_natural_keys_keep_the_first_and_count_the_rest`
- `tests/test_canonical_store.py:test_natural_key_uses_provider_metric_sport_and_observation_time`
- `tests/test_garmin_performance_history_canonical.py:test_history_refills_a_day_whose_dedicated_row_is_outdated`
- `tests/test_garmin_performance_history_canonical.py:test_the_dedicated_ftp_of_a_day_survives_the_next_sync`

### Requirement: Resumable canonical backfill worker
One background worker SHALL re-project stored raw records in batches of at most 200 plan items (configurable 100 to 250) that start no new raw record after 2 seconds, each batch in one writer transaction that also stores the cursor and content-free counters. It SHALL run inside the maintenance gate, stop between batches, yield the writer to waiting foreground requests, and run its follow-up stages in a fixed order only after the canonical stage completed.

#### Scenario: Batch fails
- **WHEN** a batch raises
- **THEN** the batch rolls back, the status `failed` is stored in its own transaction and a content-free log line names the stage and error class; a failed canonical stage is retried after 60 seconds from the last committed cursor without a restart, a failed follow-up ends the pass and is retried by the next one.

#### Scenario: Writer busy or maintenance
- **WHEN** the writer is held by another transaction or the maintenance gate refuses the operation
- **THEN** the worker waits 5 seconds and repeats the same batch; the run is not marked failed.

#### Scenario: Start while a pass runs
- **WHEN** the worker is started again while its thread runs a pass (for example after a restore)
- **THEN** no second thread starts; one more pass runs after the current one.

#### Scenario: Record changes during a partial run
- **WHEN** the mapper version, the zone, the stored payload or the dedicated Garmin training-load row of the record at the cursor changes between two batches
- **THEN** that record restarts at its first item; a mapper version change also restarts the scan from the first raw record.

#### Scenario: Follow-up stage fails
- **WHEN** a follow-up stage fails
- **THEN** only that stage is marked failed, later stages of the pass do not run, and the canonical backfill stays complete.

Detailed contract: the state is the key-value record `canonical_backfill_state` with the status `pending`, `running`, `complete` or `failed`, the cursor, the mapper versions and zone of the run, `batches`, `completed_once` and per-provider counters `skipped_invalid`, `duplicates`, `reprojected` and `retired`. Record-level counters are added when the record completes, so an interrupted run reports the same totals. Raw records are visited in row-id order; deleted records, records without a mapper and records already at the current version are passed over, except in a zone-change pass. The follow-up order is local session load, session metrics, activity routes, session analysis, activity weather (when configured), then the one-time stages that `server.py` composes (session rebundle among them). The thread is the daemon thread `canonical-backfill`.

Evidence:
- `backend/sync/canonical_backfill.py:CanonicalBackfill.run_batch`
- `backend/sync/canonical_backfill_worker.py:CanonicalBackfillWorker`
- `backend/sync/canonical_wiring.py:build_canonical_backfill`
- `tests/test_canonical_backfill.py:test_batch_size_must_stay_within_the_documented_bounds`
- `tests/test_canonical_backfill.py:test_batches_yield_the_writer_to_a_waiting_foreground_request`
- `tests/test_canonical_backfill.py:test_failed_batch_is_retried_without_restart`
- `tests/test_canonical_backfill.py:test_followup_failure_marks_only_that_followup`
- `tests/test_canonical_backfill.py:test_maintenance_refusal_waits_and_retries`
- `tests/test_canonical_backfill.py:test_start_during_a_followup_reruns_the_canonical_stage`
- `tests/test_canonical_backfill.py:test_version_bump_during_a_partial_run_restarts_the_record_from_its_first_item`
- `tests/test_canonical_backfill.py:test_writer_contention_waits_and_retries_without_failing_the_backfill`

### Requirement: Exact source label strings
Source labels SHALL be these exact strings: `Garmin Connect`, `Wahoo` and `Intervals.icu` for providers, `Garmin Connect, Wahoo` for the session sources of analyses, and `Garmin` in the duplicate view. Performance notes SHALL refine a Garmin value by kind, sport and section. An observation without a provider SHALL have an empty provider label.

#### Scenario: Garmin performance notes
- **WHEN** a Garmin observation is labelled for a performance note
- **THEN** the label is `Garmin Connect Herzfrequenzzonen` (maximum heart rate from `heart_rate_zones`), `Garmin Connect max metrics` (VO2max from `max_metrics`), `Garmin Connect Körpergewicht` (weight), `Garmin Connect FTP` (ride FTP), `Garmin Connect Lauf-Schwellenleistung` (run FTP), `Garmin Connect Lauf-Schwellenpace`, `Garmin Connect Lauf-Schwellenpuls` or `Garmin Connect Rad-Schwellenpuls`, else `Garmin Connect`.

#### Scenario: German vocabulary labels
- **WHEN** a sport or purpose is shown
- **THEN** sports read Radfahren, Laufen, Schwimmen, Gehen, Wandern, Krafttraining, Rudern, Langlauf, Alpinski, Yoga, Sonstiges and purposes Training, Wettkampf, Pendeln, Einfahren, Ausfahren.

Evidence:
- `backend/canonical/labels.py:SPORT_LABELS_DE`
- `backend/providers/source_labels.py:observation_source_label`
- `backend/providers/source_labels.py:provider_label`
- `tests/test_source_label_consumers.py`
- `tests/test_source_labels.py`

### Requirement: Persisted provider coverage summary
Each Garmin and Wahoo ingest SHALL store, in the transaction of that ingest, a content-free coverage summary under `canonical_coverage:<provider>`: activity and observation totals of the tables, the counts of the last fetch, mapping issue counts per reason, the observed date range, the fetch times, the mapper versions and the zone it was computed for. It SHALL hold no record reference, field name or athlete text.

#### Scenario: Summary computed for other mappers or another zone
- **WHEN** the stored summary's mapper versions or zone differ from the current ones
- **THEN** it reads as not stored before the first completed backfill and is reported unchanged afterwards until the next ingest replaces it.

#### Scenario: Activity fetch time
- **WHEN** a Garmin write stores a complete activity list read whose window reaches the local day of the fetch
- **THEN** the summary's activity fetch time moves to that fetch; a historical chunk, a partial read or a write without an activity read keeps the previous time.

Evidence:
- `backend/canonical/coverage.py:ProviderCoverage`
- `backend/sync/canonical_coverage_store.py:CanonicalCoverageStore`
- `backend/sync/garmin_snapshot_writer.py:_current_activity_read`
- `tests/test_canonical_rollback_prerequisites.py:test_outdated_or_corrupt_summaries_are_ignored`
- `tests/test_canonical_rollback_prerequisites.py:test_persisted_value_holds_counts_only`
- `tests/test_garmin_snapshot_writer.py:test_a_historical_chunk_or_partial_read_keeps_the_last_time`

### Requirement: Garmin element pruning distinguishes deletion from history
Garmin sections SHALL be stored as one raw record per element (`<section>/<key>`), written only when it changed. A complete read of a day window SHALL delete the stored elements of that window that the answer no longer holds and retire their domain rows and the observations they own on the window's days. A replacing write without a window SHALL delete missing elements and retire their domain rows, but keep their observations as history.

#### Scenario: Empty answer
- **WHEN** a replacing write carries no element
- **THEN** the stored section is unchanged; only a gear inventory, which exists only after a successful read, is cleared by an empty list.

#### Scenario: Rolling section drops an old day
- **WHEN** a rolling section such as max metrics or readiness no longer returns an older day
- **THEN** that day's observation stays active.

#### Scenario: Element without a day in a windowed prune
- **WHEN** a windowed prune meets a stored element without a day
- **THEN** the element is kept, unless it is the weight envelope that the kept elements replace.

Evidence:
- `backend/db/garmin_store.py:prune_section`
- `backend/db/garmin_store.py:put_section`
- `backend/sync/garmin_snapshot_writer.py:GarminSnapshotWriter.write_refresh`
- `tests/test_garmin_snapshot_writer.py:test_sections_are_stored_per_element_and_state_stays_small`
- `tests/test_observation_retirement.py:test_a_garmin_element_pruned_from_a_complete_window_is_retired`
- `tests/test_observation_retirement.py:test_a_replace_prune_keeps_the_history_of_a_rolling_section`

### Requirement: Text fallback for unknown activity types
A Garmin activity whose type key is outside the type table SHALL be classified from the space-joined type key and activity name by ordered, case-insensitive substring terms; the first matching group wins and no match is `other`.

#### Scenario: Environment from text
- **WHEN** the type table gives no environment and the text contains `virtual` or `zwift`, or `indoor`, `trainer`, `treadmill` or `laufband`
- **THEN** the environment is virtual, respectively indoor; outdoor is never inferred from text.

#### Scenario: Inherited substring matches
- **WHEN** the text is "Run/Ride", "Langlauf" or "stride"
- **THEN** it is a ride, a run and a ride: an earlier term group wins and substrings match.

Detailed contract: the groups in order are ride (`ride`, `bike`, `cycling`, `rad`, `velo`, `bicycle`), run (`run`, `lauf`, `jog`), swim (`swim`, `schwimm`), strength (`strength`, `kraft`, `weight`, `gym`), walk (`walk`, `geh`), hike (`hike`, `wander`), row (`row`, `ruder`), nordic ski (`nordic`, `langlauf`, `cross_country`), alpine ski (`alpine`, `resort_ski`) and yoga (`yoga`). A known type whose table environment is unknown takes the environment from the same text.

Evidence:
- `backend/canonical/sports.py:classify_environment_text`
- `backend/canonical/sports.py:classify_sport_text`
- `backend/providers/garmin_activity_mapping.py:map_garmin_activities`
- `tests/test_canonical_sports.py`
- `tests/test_garmin_activity_mapping.py`

### Requirement: Stored sport translation
Equipment, competitions, workouts and planned units SHALL store a canonical sport and environment. Legacy tokens and listed free-text aliases SHALL be translated through fixed tables; text that is not listed SHALL never be guessed from substrings: for a workout it is kept losslessly as `sport_detail` with sport `other`, for a competition or equipment it is unsupported. A blank workout sport SHALL be `ride` with unknown environment.

#### Scenario: Token that the pair cannot reproduce
- **WHEN** a workout carries a legacy token such as `GravelRide`, whose canonical pair is the same as that of `Ride`
- **THEN** the pair is stored and the token is kept in `sport_detail`.

#### Scenario: Supported sports
- **WHEN** a competition or a piece of equipment is saved
- **THEN** a competition accepts `ride`, `run` and `strength`, equipment `ride`, `run`, `swim`, `strength` and `other`.

#### Scenario: Explicit environment
- **WHEN** a legacy token arrives with an explicit environment
- **THEN** the environment only refines a token whose own environment is unknown.

Detailed contract: the tables are `LEGACY_EQUIPMENT_TOKENS`, `LEGACY_COMPETITION_TOKENS`, `LEGACY_COMPETITION_ALIASES`, `WORKOUT_SPORT_ALIASES`, `WORKOUT_SPORT_TOKENS` and `PRIMARY_WORKOUT_TOKENS` of `backend/canonical/stored_sports.py`; aliases match case-folded with whitespace, `_` and `-` collapsed to one space.

Evidence:
- `backend/canonical/stored_sports.py:resolve_competition_sport`
- `backend/canonical/stored_sports.py:resolve_equipment_sport`
- `backend/canonical/stored_sports.py:resolve_workout_sport`
- `backend/canonical/stored_sports.py:workout_sport_from_record`
- `tests/test_canonical_stored_sports.py:test_a_record_without_sport_uses_the_default`
- `tests/test_canonical_stored_sports.py:test_specific_token_survives_as_detail`
- `tests/test_canonical_stored_sports.py:test_unresolvable_text_is_kept_losslessly`
- `tests/test_canonical_stored_sports.py:test_unsupported_competition_text_is_kept_losslessly`
