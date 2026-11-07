# provider-normalization-and-provenance Specification

## Purpose

Describe canonical interpretation of provider fields, units, dates, origins, source precedence, corrections, and the limits of current canonical coverage.

## Requirements

### Requirement: Validated canonical values and provenance
The system SHALL map provider data into validated activity records and observations with provider, source kind, source-record identity, retrieval time, metric unit, optional observation time, sport, and recording origin. Invalid required identity or time SHALL drop a record with a structured issue; invalid optional measurements SHALL remain absent with an issue. Mapping issues SHALL identify the field and reason without echoing raw values.

#### Scenario: Sparse activity
- **WHEN** an activity has a usable identity and start but lacks an optional metric
- **THEN** it remains available with that metric absent instead of a fabricated zero.

#### Scenario: Invalid provider measurement
- **WHEN** a provider sends a nonfinite, invalid-type, or out-of-range measurement
- **THEN** normalization reports a content-free issue and excludes the invalid measurement.

Detailed contract: Unknown provider fields SHALL not automatically enter public canonical records.

Evidence: `backend/canonical/records.py:Provenance`, `backend/canonical/records.py:Observation`, `backend/canonical/mapping.py:MappingIssue`, `backend/providers/wahoo_activity_mapping.py:map_wahoo_activities`; `tests/test_garmin_health_mapping.py:test_issues_never_echo_raw_values`, `tests/test_intervals_activity_mapping.py:test_private_free_text_is_not_carried_into_records`.

### Requirement: Provider-aware time and sport normalization
The system SHALL preserve explicit instants, date each activity on the day it was lived using the UTC offset the provider reports for it and otherwise the active athlete timezone, normalize supported sports and indoor/outdoor/virtual environments, and apply the implemented wall-time DST rules to local timestamps. Intervals SHALL prefer an aware `start_date` over local wall time, while a naive absolute start alone is insufficient.

#### Scenario: DST overlap or gap
- **WHEN** provider local wall time lies in a DST overlap or spring gap
- **THEN** canonical localization uses the first overlap occurrence or the implemented forward-gap interpretation and retains a valid aware instant.

#### Scenario: Unknown workout type
- **WHEN** a Wahoo workout has an unrecognized type identifier
- **THEN** it maps to other sport and unknown environment rather than claiming a known activity type.

#### Scenario: Activity recorded abroad
- **WHEN** an athlete with profile zone Europe/Berlin records a run at 06:30 in Tokyo, reported by Garmin (`startTimeLocal` nine hours after `startTimeGMT`), by Intervals.icu (`timezone` Asia/Tokyo with an exact `start_date`) or by Wahoo (`time_zone` Asia/Tokyo)
- **THEN** the activity, its session, `started_at_local` and every week or plan read are dated on the Tokyo day at 06:30, not on the previous Berlin day.

#### Scenario: Profile zone change
- **WHEN** the athlete changes the profile zone and stored records are reprojected
- **THEN** activities with their own offset keep their date and wall time, and only activities without one follow the new zone.

#### Scenario: No provider offset
- **WHEN** a provider reports no usable offset (no exact start, a non-IANA zone name, or an offset beyond +-14 hours or off the quarter hour)
- **THEN** the activity is dated in the athlete zone as before.

Detailed contract: Wahoo's naive `starts` SHALL be interpreted as UTC. The offset is stored as `local_offset_minutes` in the activity record's details; a session uses its primary record's offset, else that of the first record reporting one. A summary carrying an offset keeps its own `started_at_local` date even when a reader converts to the athlete zone.

Evidence: `backend/canonical/local_time.py:localize_wall_time`, `backend/canonical/local_time.py:wall_time`, `backend/canonical/local_time.py:wall_clock_offset_minutes`, `backend/canonical/local_time.py:zone_offset_minutes`, `backend/providers/intervals_activity_mapping.py:map_intervals_activities`, `backend/providers/garmin_activity_mapping.py:map_garmin_activities`, `backend/providers/wahoo_activity_mapping.py:WAHOO_WORKOUT_TYPES`, `backend/providers/garmin_activity_mapping.py:GARMIN_ACTIVITY_TYPES`, `backend/activities/detail_contract.py:session_local_start`, `backend/canonical/activity_summary.py:summary_local_date`, `backend/performance/analysis_input.py:analysis_sport`, `backend/performance/pace_at_hr.py:pace_at_heart_rate`; `tests/test_activity_local_offset.py`, `tests/test_garmin_activity_mapping.py:test_only_off_road_runs_are_outdoor_runs`, `tests/test_pace_at_hr.py:test_indoor_and_virtual_runs_ignore_course_altitude`, `tests/test_analysis_input.py:test_a_trail_terrain_marks_a_trail_run_for_every_provider`, `tests/test_pace_at_hr.py:test_outdoor_run_without_terrain_is_unknown_but_indoor_is_flat`, `tests/test_intervals_activity_mapping.py:test_aware_start_date_wins_over_local_wall_time`, `tests/test_intervals_activity_mapping.py:test_naive_start_date_alone_drops_the_record`, `tests/test_wahoo_activity_mapping.py:test_start_without_an_offset_is_read_as_utc`, `tests/test_wahoo_activity_mapping.py:test_local_date_follows_the_athlete_zone`, `tests/test_wahoo_activity_mapping.py:test_the_workouts_own_time_zone_dates_it_where_it_was_recorded`.

### Requirement: Activity terrain, motor assistance and native type
The system SHALL map the terrain and motor assistance a provider activity type names into provider-neutral qualifiers, keep the provider's native type, and filter analyses by these qualifiers, never by provider identity.

#### Scenario: Trail runs carry an explicit terrain
- **WHEN** an Intervals.icu `TrailRun`, a Garmin `trail_running` or `obstacle_run`, or a Wahoo workout type 4 is mapped
- **THEN** it is an outdoor run with terrain `trail`, and the session analyses (decoupling, pace at heart rate), the critical-speed fit and the equal-effort run trend leave it out by that terrain, never by provider; treadmill and virtual runs count as flat for pace at heart rate (method `pace-at-heart-rate-v2`), never grade-adjusted by a course altitude.

#### Scenario: E-bike rides carry motor assistance
- **WHEN** an Intervals.icu `EBikeRide` or `EMountainBikeRide`, a Garmin `e_bike_fitness` or `e_bike_mountain`, or a Wahoo workout type 64 is mapped
- **THEN** it is a ride with assist `electric`; its session stays out of the power and speed best values, CP/CS fits and mean-max and equal-effort trends, and counts in time-based volume, reported again as `electric_assist_hours`.

#### Scenario: Equivalent types across providers
- **WHEN** the same activity type exists in two provider tables (for example cyclocross, mountain bike, lap or open-water swim, treadmill run)
- **THEN** each provider maps it to the same sport, environment and terrain.

Detailed contract: Terrain (road, trail, track, gravel, mountain, treadmill, pool, open water, unknown), assist (none, electric, unknown) and `native_type` (the provider type name or id, at most 64 characters) are stored in the record's details; a type a provider table knows without naming assistance is assist `none`, an unknown type is `unknown`. A session takes its primary record's terrain unless that is unknown and another record knows it; it is electric whenever any record is, since a generic type such as a plain ride maps to assist `none`. The session summary, the session analysis and the Coach activity list carry the terrain when known and `assist` only as `electric`; comparable sessions compare trail runs only with trail runs. An Intervals.icu `Swim` is a pool swim only with a positive `pool_length`.

Evidence: `backend/canonical/vocabulary.py:Terrain`, `backend/canonical/vocabulary.py:Assist`, `backend/canonical/records.py:session_terrain`, `backend/providers/intervals_activity_mapping.py:INTERVALS_ACTIVITY_QUALIFIERS`, `backend/providers/garmin_activity_mapping.py:GARMIN_ACTIVITY_QUALIFIERS`, `backend/providers/wahoo_activity_mapping.py:WAHOO_WORKOUT_QUALIFIERS`, `backend/performance/critical_power.py:critical_power_speed`, `backend/performance/load.py:activity_rollup`; `tests/test_activity_qualifiers.py`, `tests/test_mean_max_curve.py:test_e_bike_sessions_stay_out_of_the_bests_and_fits`.

### Requirement: Activity field and load semantics
The system SHALL retain distinct moving and elapsed durations from every provider, distance in metres, power in watts, heart rate in bpm, ascent in metres, speed in metres per second, cadence in rpm, energy in kJ where mapped, and provider-specific load models. Intervals SHALL prefer moving time and average-watts aliases; Wahoo SHALL use summary active duration before total duration and never use planned workout minutes as completed duration.

#### Scenario: Planned versus completed Wahoo duration
- **WHEN** a workout has planned minutes but no processed summary duration
- **THEN** actual duration remains unknown rather than using the plan as a measurement.

#### Scenario: Listed Wahoo workout without a recording
- **WHEN** Wahoo lists a workout without any measured duration, distance, heart rate, power or TSS, such as an unprocessed copy or a loaded plan that was never recorded
- **THEN** it is not stored as a completed activity and a copy stored earlier is tombstoned only when that copy holds no measured value either, so the calendar shows no extra activity; once a later sync brings its summary, the activity is stored or revived and linked as usual. A workout whose summary offers a recording file is a recording and is never withdrawn.

#### Scenario: Elapsed duration beside moving duration
- **WHEN** a Wahoo workout has both an active and a total duration, or a Garmin activity has `duration` and `movingTime`
- **THEN** the total or `duration` is stored as the elapsed duration and the moving time is not.

#### Scenario: Garmin strength session duration
- **WHEN** a Garmin strength activity has an active timer `duration` and a longer `elapsedDuration`
- **THEN** `elapsedDuration` is stored as the elapsed duration, and as the activity duration, so rest between sets counts; Intervals.icu and Wahoo strength sessions follow the same rule.

#### Scenario: Provider loads differ
- **WHEN** Intervals training load and Wahoo TSS describe copies of a session
- **THEN** their canonical values retain their respective load models and provenance rather than being relabeled as interchangeable measurements.

Detailed contract: Wahoo work in joules SHALL convert to kJ; zero ascent remains measured, while zero unsupported/unmeasured summary power, cadence, energy, and TSS remain absent under its mapper rules.

Evidence: `backend/providers/intervals_activity_mapping.py:map_intervals_activities`, `backend/providers/garmin_activity_mapping.py:map_garmin_activities`, `backend/providers/wahoo_activity_mapping.py:map_wahoo_activities`; `tests/test_intervals_activity_mapping.py:test_moving_time_precedes_elapsed_time`, `tests/test_intervals_activity_mapping.py:test_zero_load_is_kept_with_the_intervals_model`, `tests/test_wahoo_activity_mapping.py:test_summary_metrics_map_from_decimal_text`, `tests/test_wahoo_activity_mapping.py:test_planned_minutes_are_never_the_duration`, `tests/test_garmin_activity_mapping.py:test_strength_duration_is_the_whole_session_not_the_active_timer`, `backend/providers/canonical_plans.py:wahoo_ingest_plan`, `backend/sync/canonical_ingest.py:ingest_plan`, `tests/test_wahoo_activity_mapping.py:test_workouts_without_a_measured_value_are_withdrawn`, `tests/test_session_linking.py:test_a_stored_placeholder_is_withdrawn_and_revived_with_its_summary`, `tests/test_session_linking.py:test_a_stored_recording_listed_without_its_summary_is_kept`, `tests/test_wahoo_activity_mapping.py:test_a_workout_with_a_recording_file_is_never_withdrawn`.

### Requirement: One activity duration and cadence meaning
The system SHALL fill the activity duration by one rule for every provider: moving time, else timer time, else elapsed time, and the elapsed time when it is longer for strength. Cadence SHALL be rpm, counting one leg per minute for runs, never steps per minute.

#### Scenario: Garmin moving time beside its timer time
- **WHEN** a Garmin activity has `movingDuration` and a longer timer `duration`
- **THEN** since Garmin activity mapper 12 the activity duration is the moving time, as for Intervals.icu and Wahoo, and session bundling compares the Garmin elapsed time with the Intervals.icu elapsed time in its elapsed pass.

#### Scenario: Strength session from any provider
- **WHEN** an Intervals.icu, Wahoo or Garmin strength session has a moving or timer time shorter than its elapsed time
- **THEN** the activity duration is the elapsed time, so rest between sets counts.

Evidence: `backend/canonical/records.py:activity_duration_s`, `backend/activities/canonical_sessions.py:_garmin_measurement_gaps`; `tests/test_canonical_records.py:ActivityDurationRuleTests`, `tests/test_intervals_activity_mapping.py:test_strength_duration_is_the_whole_session`, `tests/test_garmin_activity_mapping.py:test_moving_duration_comes_from_moving_duration_only`, `tests/test_canonical_sessions.py:test_a_wahoo_record_is_not_matched_by_the_intervals_elapsed_time`.

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
The system SHALL normalize Garmin sleep duration/score, night SpO2/respiration/sleeping HR, last-night RMSSD, weekly HRV average, resting HR, readiness, body measurements, daily counts/energy, VO2max, thresholds, predictions, and endurance score using supported aliases and plausible bounds. Weekly HRV SHALL not stand in for a last-night reading. Declared grams/pounds/kilograms SHALL convert to kg, body-fat fractions to percent, with bounded fallback magnitude interpretation only for undeclared units.

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

Evidence: `backend/providers/garmin_health_mapping.py:map_garmin_health`, `backend/providers/intervals_wellness_mapping.py:map_intervals_wellness`; `tests/test_garmin_health_mapping.py:test_weight_converts_declared_units_to_kilograms`, `tests/test_garmin_health_mapping.py:test_wake_up_reading_wins_regardless_of_list_order`, `tests/test_garmin_health_mapping.py:test_manual_weigh_in_is_provider_reported_and_recorded_by_manual`, `tests/test_garmin_health_mapping.py:test_hrv_prefers_last_night_and_ignores_weekly_average`, `tests/test_garmin_health_mapping.py:test_zero_sleep_score_is_kept`, `tests/test_garmin_health_mapping.py:SleepNightValueTests`, `tests/test_garmin_health_mapping.py:test_daily_stats_map_counts_and_energy_with_units`.

### Requirement: Current thresholds and dated special metrics
The system SHALL keep FTP and threshold sport scope, Garmin scaled running speed conversion to canonical m/s, display conversion to seconds/km, date-bearing historical FTP, running race-prediction seconds, and endurance-score wrapper normalization. An undated current Garmin FTP, running threshold, zone maximum, or prediction may use the fetch's local day only in its implemented current-value path. Undated current FTP SHALL never invent historical FTP.

#### Scenario: Current FTP without history date
- **WHEN** Garmin returns an undated current FTP together with no dated historical FTP record
- **THEN** the current reading may be dated to the local fetch day and historical gaps remain empty.

#### Scenario: Garmin FTP history range records
- **WHEN** stored Garmin FTP history holds biometric range records with `from` and `value`
- **THEN** since Garmin health mapper version 14 each becomes a ride FTP observation on its `from` day, reprojected without a provider refetch; a bare `value` without `from` is not FTP.

#### Scenario: Running threshold power under one kind
- **WHEN** Garmin, Intervals.icu or Wahoo report a running threshold power
- **THEN** since Garmin health mapper version 17 each is FTP with sport run; Garmin rows stored earlier under the legacy run threshold power kind stay readable as the run FTP until replay re-projects them.

#### Scenario: Multiple Wahoo zone revisions
- **WHEN** Wahoo returns multiple power-zone sets for one supported family
- **THEN** the newest update time wins, later input wins an equal-time tie, and only that selected source row supplies the FTP observation.

Detailed contract: Wahoo SHALL map the newest power-zone set per cycling/running family to FTP and current profile weight to the local fetch day; it SHALL not infer zone boundaries or other profile metrics from them.

Evidence: `backend/providers/garmin_health_mapping.py:map_garmin_health`, `backend/performance/garmin_canonical.py:garmin_thresholds`, `tests/test_current_thresholds.py:test_garmin_run_power_is_one_ftp_kind_with_the_legacy_kind_readable`, `backend/providers/wahoo_threshold_mapping.py:select_power_zone_sets`, `backend/providers/wahoo_threshold_mapping.py:map_wahoo_power_zones`; `tests/test_garmin_health_mapping.py:test_latest_ftp_without_a_date_uses_the_sync_day_only_for_current`, `tests/test_garmin_health_mapping.py:test_ftp_history_reads_biometric_range_records`, `tests/test_garmin_health_mapping.py:test_scaled_running_speed_is_stored_as_metres_per_second`, `tests/test_garmin_health_mapping.py:test_wrapped_endurance_score_is_mapped`, `tests/test_wahoo_threshold_mapping.py:test_the_newest_zone_set_of_each_family_is_kept_in_input_order`, `tests/test_wahoo_threshold_mapping.py:test_the_profile_is_dated_on_the_local_day_of_the_fetch`.

### Requirement: Metric-specific source priority and local authority
The system SHALL apply per-metric source rules rather than a universal provider order. A locally confirmed zone configuration precedes every provider for thresholds. Intervals.icu is never a source (athlete decision 2026-11-07). Current ride FTP prefers Garmin, with Wahoo last; threshold and maximum heart rate, threshold pace, run power and VO2max are Garmin's. Weight and body fat take the most recent measurement of Garmin, the profile and Wahoo.

#### Scenario: Three FTP sources
- **WHEN** eligible Intervals, Garmin, and Wahoo cycling FTP values coexist and no local zone configuration applies
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

Detailed contract: Within one day of the newest weight or body fat, a device measurement precedes a provider report, which precedes a local entry; the manual profile value and Wahoo's profile weight are fallbacks in that order. Body fat follows the weight rule with a 2-percentage-point conflict tolerance; readiness, sleep, RMSSD, and resting HR are Garmin's (performance-and-readiness); CTL/ATL have no rule. Wahoo current FTP/weight older than 90 days SHALL be excluded when an as-of local day is supplied, without deleting history. The PWA display preference of weight, body fat, sleep, HRV, resting HR, threshold pace, VO2max and eFTP is the first provider of that metric's rule; FTP and W/kg charts keep Garmin, whose FTP history they draw. Local profile and competition records SHALL retain their domain authority rather than being overwritten by provider read sync.

Evidence: `backend/performance/source_policy.py:CURRENT_RULES`, `backend/performance/source_policy.py:resolve_candidates`, `backend/performance/current_thresholds.py:resolve_current_thresholds`, `backend/performance/display_sources.py:PREFERRED_PROVIDER`, `backend/performance/current_metrics.py:current_performance_metrics`, `backend/sync/authority.py:PlanningAuthorityService`; `tests/test_current_thresholds.py`, `tests/test_source_policy.py:RecencyResolutionTests`, `tests/test_performance_current_metrics.py:test_garmin_ftp_beats_wahoo_ftp_and_intervals_is_ignored`, `tests/test_performance_current_metrics.py:test_manual_profile_weight_beats_wahoo_weight`, `tests/test_performance_display_sources.py`, `tests/test_sync_authority.py:test_revision_failure_rolls_back_planning_update_atomically`.

### Requirement: Correction and reprojection continuity
The system SHALL preserve provider raw-record identity and mapper version, ingest canonical data with the owning provider transaction, and reproject stored records on mapper/timezone changes. Before the first successful canonical backfill, canonical reads SHALL return no values and consumers SHALL report a pending state; after first completion, reads SHALL continue from tables during later reprojection/failure rather than disappearing or becoming pending again.

#### Scenario: Mapper update after completed backfill
- **WHEN** a new mapper version requires reprojection
- **THEN** stored table values remain readable while batches create corrected observations and current versions take precedence as available.

#### Scenario: Provider clears or deletes a value
- **WHEN** a sync or reprojection maps a raw record again (an Intervals.icu wellness day or athlete record, a Garmin health element, a Wahoo threshold record) and it no longer emits an observation that record owns
- **THEN** the observation is retired: it stays stored and in backups, but no canonical read, Coach context or readiness serves it; a later projection that emits it again makes it active. A record retires only on the days it speaks for: its own day (a wellness day, a dated element) or, for a dateless snapshot (athlete profile, Wahoo profile, a whole Garmin section), its fetch day, plus the days it still emits; values of earlier days stay as history. A raw record the sync did not fetch (failed, skipped or empty section) retires nothing, and an observation another record emits or without an owner is untouched.

#### Scenario: Garmin weigh-in deleted in Garmin Connect
- **WHEN** a complete Garmin weight fetch for a day window no longer returns a stored weigh-in or daily weight summary of a window day
- **THEN** the stored weight section drops it and its observation is retired; readings of other days and undated readings stay, and an incomplete, failed or empty fetch changes nothing.

#### Scenario: First backfill has not completed
- **WHEN** initial backfill is pending, running, or failed
- **THEN** activities, activity rows and summaries, observations, metric windows and the chosen reader return nothing, coverage reports only current persisted summaries, and performance and Coach contexts mark the unavailable canonical data instead of presenting partial values. A failure is reported as such and the worker retries after a delay from the last committed cursor without requiring a restart.

#### Scenario: Compact-only Intervals.icu snapshot
- **WHEN** the stored Intervals.icu snapshot lists activities only in compact form (from a release before raw provider data) and the backfill has completed
- **THEN** activity reads come from the tables without those compact rows, and the gap is reported as `activities_need_refresh` and marked in the PWA while any stored compact row has no raw row with its id. An incremental sync keeps the older compact rows and the mark; only the full read-only Intervals.icu reload (`POST /api/intervals/full-resync`) that returns raw rows for them closes it. No remote write or implicit refetch happens.

Detailed contract: No legacy snapshot projection serves reads. Reprojection SHALL preserve session ownership and mark retired or invalid mapped records without deleting original provider evidence.

Evidence: `backend/sync/canonical_ingest.py:ingest_plan`, `backend/sync/canonical_backfill.py:CanonicalBackfill`, `backend/sync/canonical_read_selector.py:CanonicalReadSelector`; `tests/test_canonical_read_selector.py:test_observations_stay_available_until_the_reprojection_completes`, `tests/test_canonical_read_selector.py:test_first_backfill_not_complete_serves_nothing_from_filled_tables`, `tests/test_canonical_read_selector.py:test_compact_only_snapshot_reads_tables_and_needs_a_refresh`, `tests/test_canonical_backfill.py:test_a_dropped_activity_is_invalid_and_a_later_version_restores_it`, `tests/test_canonical_backfill.py:test_retry_preserves_committed_cursor_and_finishes`, `tests/test_performance_canonical_parity.py:test_failed_first_backfill_is_visible_but_completed_data_stays_available`, `tests/test_observation_retirement.py:test_cleared_intervals_wellness_value_is_retired_and_revived`, `tests/test_observation_retirement.py:test_a_failed_or_skipped_garmin_section_retires_nothing`, `tests/test_garmin_snapshot_writer.py:test_a_complete_window_retires_the_deleted_weigh_in_only`.

### Requirement: Provenance and incomplete coverage remain visible
The system SHALL expose source labels, observation dates, retrieval freshness, and missing or unsupported coverage without synthesizing measurements. Canonically mapped Garmin status, load balance and Body Battery SHALL retain provider-estimate labels, their supported measurement windows and explicit partial coverage.

#### Scenario: Source not canonically supported
- **WHEN** a stored Garmin section contains an unsupported field
- **THEN** coverage records the limitation and consumers do not advertise complete support for that field.

#### Scenario: Derived value displayed
- **WHEN** a detail average is calculated from samples or a load value carries a provider calculation
- **THEN** its public document includes the corresponding source and kind/model rather than presenting it as an athlete-entered measurement.

Detailed contract: Public metric names SHALL be provider-neutral while source labels identify origin, derived values, and AI estimates when present.

Evidence baseline: `backend/canonical/records.py`, `backend/db/canonical_store.py`, `backend/providers/canonical_plans.py`, `backend/sync/canonical_table_reader.py`, `backend/activities/zone_settings.py`; tests in `tests/test_canonical_records.py`, `tests/test_canonical_store.py`, `tests/test_garmin_health_mapping.py`. The added behavior requires new implementation and regression evidence.

### Requirement: Intervals wellness and athlete threshold mapping
The system SHALL map dated Intervals wellness body, HRV, sleep, readiness, VO2max, load/form, and sport eFTP observations. It SHALL derive form from valid CTL minus ATL only when no reported form alias is present, label derivation, and preserve athlete versus wellness series. Sport settings SHALL keep threshold/HR/pace/VO2max scope and supported unset-zero semantics; invalid first-present aliases SHALL not silently fall through.

#### Scenario: Derived form versus reported zero
- **WHEN** a wellness row contains valid CTL/ATL without a reported form field
- **THEN** form can be derived and labeled derived; an explicitly reported valid zero form remains the reported value.

#### Scenario: HRV methods and alias precedence
- **WHEN** RMSSD and SDNN are both present or an earlier alias is invalid while a later alias is numeric
- **THEN** HRV methods remain separate observations, and the rejected first-present value is reported rather than replaced by the later alias. Supported wellness kinds include weight/body fat, resting HR, RMSSD/SDNN, sleep duration/score, readiness, VO2max, CTL/ATL/form, and sport-scoped eFTP.

#### Scenario: Subjective wellness ratings
- **WHEN** a wellness row carries fatigue, soreness, stress or mood
- **THEN** each is stored as entered, provider-reported with `recorded_by` manual so the Intervals.icu provenance stays, on the Intervals.icu 1–4 scale where 1 is good and 4 bad (mood 1 super … 4 mies); the scale is resolved at read time, not stored.

#### Scenario: Rejected reported form stays absent
- **WHEN** a wellness row reports a form value that is not a valid number while CTL and ATL are valid
- **THEN** the value is reported as a mapping issue and no form observation is stored for that day, so readers show no form instead of a consumer-side CTL minus ATL.

#### Scenario: eFTP observations and their classification
- **WHEN** wellness `sportInfo` entries and athlete sport settings carry eFTP
- **THEN** each sport's first `sportInfo` entry yields one wellness-day eFTP observation, and each sport's first sport setting yields the athlete-record eFTP observation; every sport that a `types` text classifies to counts, as for the zone configurations (or, for a `sportInfo` entry without a `types` list, its `type`, `sport` and `sport_type`), with OTHER only when no text names a known sport, `mmp_model` eFTP wins over the entry's own eFTP, and zero means unset.

#### Scenario: Indoor FTP since mapper version 10
- **WHEN** a sport setting carries `indoor_ftp`
- **THEN** it is stored as that sport's INDOOR_FTP observation, which only the plan zones of indoor and virtual workouts read; the sport FTP stays the setting's `ftp`, and only a setting whose `ftp` is absent or null also stores its `indoor_ftp` as FTP (the current-metrics fallback); a zero `indoor_ftp` stores nothing; stored athlete records are reprojected without a provider refetch.

#### Scenario: Athlete settings since mapper version 9
- **WHEN** the athlete record carries W′, height, body fat or a generic VO2max, a Run setting carries a Zone-2 pace, or the athlete record carries a sport VO2max for a sport whose setting has none
- **THEN** they are stored as athlete-record observations: W′ in J, height in cm (1.2–2.5 is read as metres), body fat in % and the generic VO2max without a sport; the Zone-2 pace in m/s for Run; the sport VO2max for that sport. The athlete body fat and generic VO2max keep their own athlete series next to the same day's wellness values, as weight and eFTP do, so neither replaces the other. Re-projection applies this to stored records without a refetch.

Detailed contract: since mapper version 8 the classification and the first-setting rule match the legacy readers and apply to every sport-setting threshold; reprojection of stored athlete and wellness records applies them without a provider refetch. A derived form carries its method (`ctl_minus_atl`, version 1) and input fingerprint since version 7; readers use its value and unchanged DERIVED source kind only.

Evidence: `backend/providers/intervals_wellness_mapping.py:map_intervals_wellness`, `backend/providers/intervals_wellness_mapping.py:map_intervals_athlete_thresholds`; `tests/test_intervals_wellness_mapping.py:test_hrv_sdnn_maps_to_sdnn_in_milliseconds`, `tests/test_intervals_wellness_mapping.py:test_without_tsb_form_is_ctl_minus_atl_and_derived`, `tests/test_intervals_wellness_mapping.py:test_invalid_first_alias_is_not_replaced_by_the_later_alias`, `tests/test_intervals_wellness_mapping.py:test_rejected_tsb_is_reported_and_not_derived`, `tests/test_intervals_wellness_mapping.py:test_each_sport_keeps_its_first_entry`, `tests/test_intervals_wellness_mapping.py:test_untyped_entries_are_skipped_and_malformed_lists_reported`, `tests/test_intervals_wellness_mapping.py:test_sport_setting_mmp_model_eftp_wins_and_zero_is_unset`. The legacy classification is pinned by `tests/test_intervals_wellness_mapping.py:EftpClassificationTests`, `tests/test_canonical_store.py:test_the_first_of_two_athlete_ride_settings_is_stored` and `tests/test_canonical_backfill.py:test_athlete_stored_at_the_previous_version_keeps_its_first_ride_setting`, and the version 9 athlete settings by `tests/test_intervals_wellness_mapping.py:AthleteSettingsV9Tests`, `tests/test_canonical_store.py:test_athlete_body_fat_and_sportless_vo2max_have_their_own_series` and `tests/test_canonical_ingest.py:test_athlete_and_wellness_body_fat_and_vo2max_are_both_kept`.

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

### Requirement: Canonical sleep periods
Canonical sleep periods SHALL retain aware UTC start/end, local wake date, night/unknown kind, reported duration and provenance, and the ingest timezone only when it gives that wake date. The wake date SHALL be the provider's own day (Garmin `calendarDate`, the Intervals.icu wellness day) when it lies within a day of the end's UTC date, else the end's date in the ingest zone. Invalid or reversed periods SHALL be rejected. Periods from different providers SHALL remain separate.

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

### Requirement: Canonical sport zone configuration
Canonical zone configuration SHALL retain sport, metric, boundaries in canonical units, model, source and validity date. Provider and confirmed local configurations SHALL remain separately readable. Effective selections SHALL prefer applicable confirmed local values and SHALL never promote CP/CS into FTP, lactate threshold or zone-2 boundaries automatically.

#### Scenario: Canonical-only calendar and plan
- **WHEN** canonical zones exist without a provider snapshot
- **THEN** calendar, plan and affected time-in-zone calculations use those boundaries and retain source labels.

#### Scenario: Local configuration and provider refresh
- **WHEN** provider zones are refreshed after a confirmed local edit
- **THEN** local values retain authority and the refreshed provider alternative remains available separately.

#### Scenario: Thresholds without a zone configuration
- **WHEN** a planned workout's sport has no configuration for a metric
- **THEN** its FTP, threshold HR and maximum HR come from the source-policy provider winners (Garmin, Wahoo) with the default limits, never from Intervals.icu or the stored snapshot, and nothing is served before the first completed backfill.

Detailed contract (#1416): indoor and virtual workouts use the INDOOR power configuration's threshold, else the sport's FTP (no provider indoor FTP is read); the Ride FTP falls back to the athlete's configured FTP as the canonical current metrics do; zone lists and values the mappers reject leave the default limits or no threshold.

Evidence: `backend/performance/canonical_current.py:read_sport_thresholds`, `backend/activities/zone_settings.py:ZoneSettings.from_thresholds`, `backend/planning/calendar_read_model.py:project_planning_calendar`; `tests/test_plan_zone_canonical_parity.py`, `tests/test_zone_configuration_canonical.py:EffectiveZoneTests`, `tests/test_zone_settings.py`.

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

### Requirement: Metric vocabulary accountability
Every metric kind SHALL have an implemented provider producer or a documented local method and a consumer or explicit export-only retention purpose. Retiring a kind SHALL preserve or migrate stored observations. Provider load-model vocabulary SHALL remain separate from local session-RPE methods.

#### Scenario: Unsupported vocabulary addition
- **WHEN** a kind is added without a producer/method or consumer/retention purpose
- **THEN** the vocabulary consistency check fails.

### Requirement: Provider-neutral activity summary per session
The system SHALL give activity consumers one provider-neutral summary per live canonical session, built from the active records of every provider in it. Each value SHALL come from the best-ranked record that has it (measured values from the recording platform's own copy first, derived values by provider rank) and name its source label. Consumers outside the provider adapters, sync and canonical owners SHALL NOT read provider activity field names.

#### Scenario: Copies of one session
- **WHEN** Intervals.icu and Garmin Connect both report a session that canonical linking bundled
- **THEN** consumers receive one summary with the local session id, the canonical sport and environment, and each value's source label.

#### Scenario: Recording relayed through Garmin Connect
- **WHEN** a Garmin Connect activity names a Wahoo or Zwift manufacturer
- **THEN** its origin is that manufacturer (any other manufacturer stays a Garmin recording), so the Wahoo recording, not the Garmin copy, wins the measured values; Wahoo rides that are not indoor or virtual, including such relayed copies, carry the bike computer device type, and Garmin's own recordings name none.

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

### Requirement: Consumers read canonical records, not raw provider views
Consumer packages (performance, Coach, HTTP API, planning, activities, athlete, nutrition) SHALL NOT read metric or detail values from the raw provider snapshot, its sections, the raw Garmin views or retired kv detail records; payload parsing SHALL live with its ingestion owner. An architecture guard SHALL enforce this with an explained allowlist that can only shrink.

#### Scenario: Allowlist reasons
- **WHEN** a consumer file keeps a raw read
- **THEN** its allowlist entry names an ingestion, mapping, backup/export or sync-status reason, or a reported value read that waits for its canonical switch.

#### Scenario: A consumer adds a raw view read
- **WHEN** a module in a consumer package references `recent_wellness`, `raw_provider_data`, `read_view`, `recent_view`, `recent_view_in`, an `activity_detail:` key string or `latest_snapshot`
- **THEN** the provider-coupling guard fails unless the file is allowlisted with an explained reason; docstrings and comments do not count.

#### Scenario: A raw read is removed
- **WHEN** an allowlisted file no longer makes the read
- **THEN** the guard reports its allowlist entry as stale until it is removed.

Detailed contract: rules `snapshot_key`, `legacy_read`, `source_label` and `field_module_import` in `tests/provider_coupling.py:OWNER_READ_ALLOWLIST`. No value read remains in the consumer packages (#1416): plan zones read canonical thresholds, equipment reads canonical gear items and links (a gear-listed Garmin activity links the rows of its canonical session, every Intervals.icu row whose canonical record the pairwise Garmin duplicate rule pairs with it, also when bundling kept them apart, and a row whose `external_id` is the Garmin id; the sync no longer computes or reads `activity_matches`), and the energy views take a day's presence after a targeted refresh from its canonical Garmin totals; the stored snapshot is read there only for sync status (`provider_sync`, Garmin state).

Evidence: `tests/provider_coupling.py:scan_owner_reads`, `backend/sync/garmin_payload_metrics.py:garmin_payload_performance_metrics`, `backend/sync/garmin_performance_history.py:append_garmin_performance_history`, `backend/sync/intervals_compaction.py:compact_snapshot`; `tests/test_provider_coupling_guard.py:OwnerReadGuardTests.test_consumers_cannot_read_raw_provider_views`, `tests/test_provider_coupling_guard.py:OwnerReadGuardTests.test_allowlisted_raw_view_owner_passes_and_a_stale_entry_fails`, `tests/test_provider_coupling_guard.py:OwnerReadGuardTests.test_source_tree_reads_only_through_allowlisted_owners`.

### Requirement: Athlete-preferred source per metric group
The system SHALL let the athlete choose Garmin or the default as preferred source per metric group (thresholds, weight and body fat, HRV, resting HR, sleep) as a local profile setting with receipt and undo (also through the Coach's profile update); a stored `intervals` value is ignored. Every consumer SHALL apply it in the same read, behind a locally confirmed zone configuration.

#### Scenario: Preferred threshold source
- **WHEN** the athlete prefers Garmin for thresholds and Garmin and Wahoo report different current FTPs
- **THEN** the Coach context, current metrics and plan thresholds all use Garmin's FTP, and the Wahoo value stays an alternative with its conflict flag.

#### Scenario: A stored Intervals.icu preference
- **WHEN** a stored profile holds `intervals` as a preferred source, and the athlete saves the profile with that value
- **THEN** the stored value is read as the default order and the save is rejected as an unknown source; stored profiles are not rewritten by reads.

Evidence: `backend/performance/source_policy.py:preferences_from_profile`, `backend/performance/source_policy.py:source_order`, `backend/athlete/profile.py:normalize_profile`, `backend/performance/canonical_inputs.py:CanonicalPerformanceSource`; `tests/test_source_policy.py:PreferredSourceTests`, `tests/test_current_thresholds.py:PreferredSourceTests`, `tests/test_performance_display_sources.py:PreferredDisplayTests`, `tests/test_athlete_profile.py:test_preferred_sources_accept_known_providers_only`, `tests/test_change_history.py:test_preferred_sources_are_audited_and_older_rows_stay_matchable`, `tests/test_performance_recovery_context.py:IntervalsIsNeverASourceTests.test_a_stored_intervals_preference_is_ignored`.

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
