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
The system SHALL preserve explicit instants and derive athlete-local days using the active timezone, normalize supported sports and indoor/outdoor/virtual environments, and apply the implemented wall-time DST rules to local timestamps. Intervals SHALL prefer an aware `start_date` over local wall time, while a naive absolute start alone is insufficient.

#### Scenario: DST overlap or gap
- **WHEN** provider local wall time lies in a DST overlap or spring gap
- **THEN** canonical localization uses the first overlap occurrence or the implemented forward-gap interpretation and retains a valid aware instant.

#### Scenario: Unknown workout type
- **WHEN** a Wahoo workout has an unrecognized type identifier
- **THEN** it maps to other sport and unknown environment rather than claiming a known activity type.

Detailed contract: Wahoo's naive `starts` SHALL be interpreted as UTC, and workout-local timezone metadata SHALL not replace the athlete timezone used for local dates.

Evidence: `backend/canonical/local_time.py:localize_wall_time`, `backend/providers/intervals_activity_mapping.py:map_intervals_activities`, `backend/providers/wahoo_activity_mapping.py:WAHOO_WORKOUT_TYPES`; `tests/test_intervals_activity_mapping.py:test_aware_start_date_wins_over_local_wall_time`, `tests/test_intervals_activity_mapping.py:test_naive_start_date_alone_drops_the_record`, `tests/test_wahoo_activity_mapping.py:test_start_without_an_offset_is_read_as_utc`, `tests/test_wahoo_activity_mapping.py:test_local_date_follows_the_athlete_zone`.

### Requirement: Activity field and load semantics
The system SHALL retain distinct moving and elapsed durations, distance in metres, power in watts, heart rate in bpm, ascent in metres, speed in metres per second, cadence in rpm, energy in kJ where mapped, and provider-specific load models. Intervals SHALL prefer moving time and average-watts aliases; Wahoo SHALL use summary active duration before total duration and never use planned workout minutes as completed duration.

#### Scenario: Planned versus completed Wahoo duration
- **WHEN** a workout has planned minutes but no processed summary duration
- **THEN** actual duration remains unknown rather than using the plan as a measurement.

#### Scenario: Provider loads differ
- **WHEN** Intervals training load and Wahoo TSS describe copies of a session
- **THEN** their canonical values retain their respective load models and provenance rather than being relabeled as interchangeable measurements.

Detailed contract: Wahoo work in joules SHALL convert to kJ; zero ascent remains measured, while zero unsupported/unmeasured summary power, cadence, energy, and TSS remain absent under its mapper rules.

Evidence: `backend/providers/intervals_activity_mapping.py:map_intervals_activities`, `backend/providers/garmin_activity_mapping.py:map_garmin_activities`, `backend/providers/wahoo_activity_mapping.py:map_wahoo_activities`; `tests/test_intervals_activity_mapping.py:test_moving_time_precedes_elapsed_time`, `tests/test_intervals_activity_mapping.py:test_zero_load_is_kept_with_the_intervals_model`, `tests/test_wahoo_activity_mapping.py:test_summary_metrics_map_from_decimal_text`, `tests/test_wahoo_activity_mapping.py:test_planned_minutes_are_never_the_duration`.

### Requirement: Health and body unit normalization
The system SHALL normalize Garmin sleep duration/score, last-night RMSSD, weekly HRV average, resting HR, readiness, body measurements, daily counts/energy, VO2max, thresholds, predictions, and endurance score using supported aliases and plausible bounds. Weekly HRV SHALL not stand in for a last-night reading. Declared grams/pounds/kilograms SHALL convert to kg, body-fat fractions to percent, with bounded fallback magnitude interpretation only for undeclared units.

#### Scenario: Declared weight unit
- **WHEN** a valid Garmin weigh-in explicitly declares pounds or grams
- **THEN** canonical weight is converted once to kilograms and its dated provenance is retained.

#### Scenario: Different HRV windows
- **WHEN** a payload has only a weekly HRV average and no last-night value
- **THEN** the canonical last-night observation stays absent rather than borrowing the weekly statistic, and the weekly average is stored as its own weekly HRV observation.

#### Scenario: Stored Garmin health records after the weekly HRV mapping
- **WHEN** the Garmin health mapper version changes to add the weekly HRV kind
- **THEN** stored Garmin health records are reprojected through the existing canonical backfill without a provider refetch, schema change or remote write.

Detailed contract: Zero SHALL remain valid for sleep score, steps, floors, and active energy where implemented, while absent or invalid measurements remain unknown.

Evidence: `backend/providers/garmin_health_mapping.py:map_garmin_health`, `backend/providers/intervals_wellness_mapping.py:map_intervals_wellness`; `tests/test_garmin_health_mapping.py:test_weight_converts_declared_units_to_kilograms`, `tests/test_garmin_health_mapping.py:test_hrv_prefers_last_night_and_ignores_weekly_average`, `tests/test_garmin_health_mapping.py:test_zero_sleep_score_is_kept`, `tests/test_garmin_health_mapping.py:test_daily_stats_map_counts_and_energy_with_units`.

### Requirement: Current thresholds and dated special metrics
The system SHALL keep FTP and threshold sport scope, Garmin scaled running speed conversion to canonical m/s, display conversion to seconds/km, date-bearing historical FTP, running race-prediction seconds, and endurance-score wrapper normalization. An undated current Garmin FTP, running threshold, zone maximum, or prediction may use the fetch's local day only in its implemented current-value path. Undated current FTP SHALL never invent historical FTP.

#### Scenario: Current FTP without history date
- **WHEN** Garmin returns an undated current FTP together with no dated historical FTP record
- **THEN** the current reading may be dated to the local fetch day and historical gaps remain empty.

#### Scenario: Multiple Wahoo zone revisions
- **WHEN** Wahoo returns multiple power-zone sets for one supported family
- **THEN** the newest update time wins, later input wins an equal-time tie, and only that selected source row supplies the FTP observation.

Detailed contract: Wahoo SHALL map the newest power-zone set per cycling/running family to FTP and current profile weight to the local fetch day; it SHALL not infer zone boundaries or other profile metrics from them.

Evidence: `backend/providers/garmin_health_mapping.py:map_garmin_health`, `backend/providers/wahoo_threshold_mapping.py:select_power_zone_sets`, `backend/providers/wahoo_threshold_mapping.py:map_wahoo_power_zones`; `tests/test_garmin_health_mapping.py:test_latest_ftp_without_a_date_uses_the_sync_day_only_for_current`, `tests/test_garmin_health_mapping.py:test_scaled_running_speed_is_stored_as_metres_per_second`, `tests/test_garmin_health_mapping.py:test_wrapped_endurance_score_is_mapped`, `tests/test_wahoo_threshold_mapping.py:test_the_newest_zone_set_of_each_family_is_kept_in_input_order`, `tests/test_wahoo_threshold_mapping.py:test_the_profile_is_dated_on_the_local_day_of_the_fetch`.

### Requirement: Metric-specific source priority and local authority
The system SHALL apply per-metric source rules rather than a universal provider order. Current weight, FTP, thresholds, and VO2max prefer supported Garmin values before Intervals, with Wahoo a last fallback for current cycling FTP and weight. Manual profile weight precedes Wahoo fallback.

#### Scenario: Three FTP sources
- **WHEN** eligible Garmin, Intervals, and Wahoo cycling FTP values coexist
- **THEN** current metric composition selects Garmin, labels its provider, and retains the other provider observations for their supported reads.

#### Scenario: Old Wahoo fallback
- **WHEN** Wahoo is the only eligible source but its dated value is older than the current-value age limit
- **THEN** the current selector returns no Wahoo value while historical storage remains intact.

Detailed contract: Body-fat current composition uses Intervals and manual profile paths; readiness prefers Intervals over Garmin; sleep, RMSSD, and resting HR prefer eligible Garmin readings; CTL/ATL remain Intervals-owned. Wahoo current FTP/weight older than 90 days SHALL be excluded when an as-of local day is supplied, without deleting history. Local profile and competition records SHALL retain their domain authority rather than being overwritten by provider read sync.

Evidence: `backend/performance/source_policy.py:CURRENT_RULES`, `backend/performance/source_policy.py:DAILY_RULES`, `backend/performance/current_metrics.py:current_performance_metrics`, `backend/sync/authority.py:PlanningAuthorityService`; `tests/test_performance_current_metrics.py:test_garmin_ftp_beats_intervals_and_wahoo_ftp`, `tests/test_performance_current_metrics.py:test_manual_profile_weight_beats_wahoo_weight`, `tests/test_sync_authority.py:test_revision_failure_rolls_back_planning_update_atomically`.

### Requirement: Correction and reprojection continuity
The system SHALL preserve provider raw-record identity and mapper version, ingest canonical data with the owning provider transaction, and reproject stored records on mapper/timezone changes. Before first successful canonical backfill, reads SHALL use legacy projection; after first completion, reads SHALL continue from tables during later reprojection/failure rather than disappearing or reverting wholesale to legacy.

#### Scenario: Mapper update after completed backfill
- **WHEN** a new mapper version requires reprojection
- **THEN** stored table values remain readable while batches create corrected observations and current versions take precedence as available.

#### Scenario: First backfill has not completed
- **WHEN** initial backfill is pending, running, or failed
- **THEN** consumers use the supported legacy source instead of claiming table coverage that has never completed.

Detailed contract: Compact-only activity snapshots retain their implemented activity-row fallback. Reprojection SHALL preserve session ownership and mark retired or invalid mapped records without deleting original provider evidence.

Evidence: `backend/sync/canonical_ingest.py:ingest_plan`, `backend/sync/canonical_backfill.py:CanonicalBackfill`, `backend/sync/canonical_read_selector.py:CanonicalReadSelector`; `tests/test_canonical_read_selector.py:test_observations_stay_available_until_the_reprojection_completes`, `tests/test_canonical_backfill.py:test_a_dropped_activity_is_invalid_and_a_later_version_restores_it`.

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

Evidence: `backend/providers/intervals_wellness_mapping.py:map_intervals_wellness`, `backend/providers/intervals_wellness_mapping.py:map_intervals_athlete_thresholds`; `tests/test_intervals_wellness_mapping.py:test_hrv_sdnn_maps_to_sdnn_in_milliseconds`, `tests/test_intervals_wellness_mapping.py:test_without_tsb_form_is_ctl_minus_atl_and_derived`, `tests/test_intervals_wellness_mapping.py:test_invalid_first_alias_is_not_replaced_by_the_later_alias`.

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
Canonical sleep periods SHALL retain aware UTC start/end, the timezone used, local wake date, night/unknown kind, reported duration and provenance. Invalid or reversed periods SHALL be rejected. Periods from different providers SHALL remain separate.

#### Scenario: Midnight and DST
- **WHEN** a valid period crosses midnight or a DST transition
- **THEN** its instants preserve actual duration and its assigned date is the wake date in the recorded timezone.

#### Scenario: Missing nights and overlapping providers
- **WHEN** nights are missing or two providers overlap
- **THEN** no missing night is fabricated and provider periods are not silently merged.

#### Scenario: Garmin main sleep during daytime
- **WHEN** Garmin identifies a period as its main daily sleep episode, including daytime sleep for a shift worker
- **THEN** its canonical kind is NIGHT, meaning main sleep rather than a clock-night classification; arbitrary periods are not classified by hour or duration.

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
