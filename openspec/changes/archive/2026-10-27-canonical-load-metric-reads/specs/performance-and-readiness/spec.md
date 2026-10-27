## MODIFIED Requirements

### Requirement: Current performance metrics with explicit fallback
The system SHALL compose current body, cycling/running thresholds, VO2max, maximum HR, Zone-2 pace, eFTP, and running predictions from supported local provider/profile inputs with source and unit metadata. It SHALL use metric-specific Garmin/Intervals/Wahoo/manual precedence, preserve sport scope, and reject implausible values. Canonical and compatibility inputs SHALL preserve the same supported public metric shape without mutating callers.

#### Scenario: Garmin thresholds available
- **WHEN** plausible Garmin cycling FTP or running threshold values coexist with Intervals settings
- **THEN** current composition prefers Garmin for those supported metrics and exposes its source/unit/date metadata.

#### Scenario: Fallback and no value
- **WHEN** a preferred source is missing
- **THEN** the implemented sport, wellness, athlete, manual, or Wahoo fallback may supply that metric; if no eligible source exists its value remains unknown.

#### Scenario: Current cycling eFTP comes from canonical observations
- **WHEN** the current performance metrics are composed
- **THEN** `cycling_eftp_watts` is the ride eFTP observation of the latest Intervals sync's athlete record, else the ride eFTP observation of the latest wellness day, else the latest ride activity's eFTP, with the unchanged Intervals source label; the snapshot's athlete `sport_settings` and wellness `sportInfo` are not read for it.

#### Scenario: No canonical eFTP input
- **WHEN** no canonical current inputs exist, there is no usable wellness day, or no athlete-record or wellness-day ride eFTP observation is stored
- **THEN** the athlete-record and wellness steps contribute nothing and only the latest ride activity's eFTP can supply the value; otherwise it remains unknown.

#### Scenario: Run and other sports do not feed cycling eFTP
- **WHEN** Run and Ride eFTP observations coexist
- **THEN** only ride-scoped observations feed `cycling_eftp_watts`.

Evidence: `backend/performance/current_metrics.py:current_performance_metrics`, `backend/performance/canonical_current.py:read_current_inputs`; `tests/test_performance_current_metrics.py:test_garmin_priority_and_metric_shape`, `tests/test_performance_current_metrics.py:test_intervals_wellness_athlete_profile_fallbacks_and_eftp`, `tests/test_performance_current_metrics.py:test_invalid_values_and_inputs_are_not_mutated`. The canonical eFTP scenarios are verified by `tests/test_performance_canonical_current_metrics.py:CanonicalEftpInputTests`, `tests/test_performance_current_metrics.py:test_eftp_follows_the_canonical_chain_then_the_latest_ride_activity`, `tests/test_characterization_current_metrics.py:test_eftp_athlete_then_wellness_then_latest_ride_activity` and `tests/test_performance_canonical_load_metrics.py:EftpTests`.

### Requirement: Load rollups and actual-load reconstruction
The system SHALL calculate explicit current/previous 7- and 30-day completed-activity rollups and supported actual ATL reconstruction using known completed loads. It SHALL sum multiple known loads on the same day, decay the reconstructed series across gaps using its implemented model, and keep Intervals CTL/ATL/form separate from Garmin measured acute load. Activity-derived load SHALL not be presented as Garmin's device-reported acute load.

#### Scenario: Multiple sessions and rest days
- **WHEN** a day contains several completed loads and later days have no activity
- **THEN** rollups sum known contributions and actual ATL evolves through the implemented decay rather than copying a future planned load.

#### Scenario: Missing or conflicting Garmin acute load
- **WHEN** no dated valid measured acute-load value exists or device values conflict
- **THEN** Garmin acute-load history leaves the date unknown instead of reconstructing it from daily/chronic activity totals.

#### Scenario: Form comes from canonical observations
- **WHEN** the current load block is composed
- **THEN** `tsb` is the form observation of the latest wellness day (reported or derived as mapped); `tsb`, `form` and `freshness` of the snapshot wellness row are not read and the consumer does not derive CTL minus ATL itself.

#### Scenario: No form observation
- **WHEN** the latest wellness day has no form observation, including a reported form value that the mapper rejected as invalid, or no canonical inputs exist
- **THEN** `tsb` is unknown instead of a snapshot value or a consumer-side derivation.

Evidence: `backend/performance/load.py:activity_rollup`, `backend/performance/load.py:actual_atl_series`, `backend/performance/load_context.py:performance_load_context`, `backend/performance/garmin_load.py:acute_load_value`; `tests/test_performance_load.py:test_actual_atl_decays_across_missing_days_and_is_sorted`, `tests/test_performance_chart_history.py:test_garmin_acute_load_is_dated_and_never_derived_from_daily_or_chronic_load`, `tests/test_performance_chart_history.py:test_acute_load_rejects_invalid_and_conflicting_device_values`. The form scenarios are verified by `tests/test_performance_canonical_load_metrics.py:FormTests`, `tests/test_performance_load_context.py:test_form_and_ramp_rate_come_from_the_canonical_inputs` and `tests/test_characterization_load_focus.py:test_carrier_form_fields_are_not_read_without_canonical_inputs`.

### Requirement: Dated history and comparisons
The system SHALL provide bounded dated performance and provider-metric histories, current-versus-previous period comparisons, and observed best-effort windows with provider/source labels. Current settings SHALL never be backdated into historical gaps.

#### Scenario: Stored history without new sync
- **WHEN** raw dated FTP or other supported provider history is already stored
- **THEN** local history projection can expose it without another provider call, within its 90-day chart window.

#### Scenario: Current estimate but no history
- **WHEN** a current race prediction or FTP exists without dated historical measurements
- **THEN** historical dates remain gaps and no trend is manufactured from the current setting.

#### Scenario: Observed best-effort selection
- **WHEN** valid original-stream profiles exist inside 28- or 90-day windows
- **THEN** records retain sport/provenance and incomplete-record coverage; future activities are excluded and running speed/distance selection uses their implemented different extrema.

#### Scenario: eFTP history reads canonical wellness days
- **WHEN** the eFTP chart, body history or 30-day eFTP comparison is composed
- **THEN** each day contributes at most one value: the ride eFTP observation of that wellness day, else the day's latest ride activity eFTP, both bounded to 20-2000 W; snapshot `sportInfo` is not read, and days without a value remain gaps.

#### Scenario: Form comparison reads canonical form days
- **WHEN** the 7-day form comparison is composed
- **THEN** it averages the form observations of the inclusive seven days ending on the current day, and the average is unknown when no day has an observation.

Detailed contract: Intervals eFTP averages SHALL use actual Intervals estimates rather than configured FTP; race predictions, endurance scores, running tolerance, readiness history, and weekly training status SHALL retain their supported observation dates and aggregation metadata.

Evidence: `backend/performance/chart_history.py:analysis_history`, `backend/performance/comparisons.py:performance_comparisons`, `backend/performance/eftp.py:eftp_30_day_average`, `backend/performance/report_service.py:TrainingProfileSelectionService`; `tests/test_performance_chart_history.py:test_sources_remain_separate_with_no_backdating_of_current_settings`, `tests/test_performance_chart_history.py:test_race_prediction_history_does_not_backfill_current_estimates`, `tests/test_training_report.py:test_running_speed_selects_fastest_effort_and_distance_selects_shortest`. The canonical eFTP and form scenarios are verified by `tests/test_performance_eftp.py`, `tests/test_performance_comparisons.py:test_eftp_and_form_comparisons_read_the_canonical_days_only`, `tests/test_performance_wellness.py:WellnessFormTests`, `tests/test_characterization_body_history.py` and `tests/test_performance_canonical_load_metrics.py:test_chart_and_body_history_read_the_canonical_series`.

## ADDED Requirements

### Requirement: Ramp rate is a labelled local derivation
The system SHALL derive the ramp rate of the current load block as the latest wellness day's CTL minus the CTL of exactly seven days earlier, rounded to two decimals, from canonical Intervals.icu wellness-day CTL observations, and SHALL label it as derived through `current_load.rampRate_source`. Intervals.icu's own `rampRate` is not read and can differ from the derived number.

#### Scenario: Both days present
- **WHEN** CTL observations exist for the latest wellness day (58.4) and for seven days earlier (54.1)
- **THEN** `current_load.rampRate` is 4.3 and `current_load.rampRate_source` is `Intervals.icu CTL (berechnet)`.

#### Scenario: A day is missing
- **WHEN** either CTL day is absent, even though a neighbouring day exists
- **THEN** `rampRate` and `rampRate_source` are unknown; exact days only, no neighbouring day is substituted and nothing is interpolated.

#### Scenario: Snapshot ramp rate present
- **WHEN** the snapshot wellness row carries its own `rampRate` while the derivation inputs are present or absent
- **THEN** the snapshot value is ignored and only the derived value, or unknown, is shown.

#### Scenario: No wellness day or no canonical inputs
- **WHEN** the latest wellness row has no usable date or no canonical performance inputs exist
- **THEN** `rampRate` and `rampRate_source` are unknown and the other load keys keep their behaviour.

Evidence: none for existing behavior (the legacy path passes the snapshot `rampRate` through: `backend/performance/load_context.py:performance_load_context`). Verified by `tests/test_performance_canonical_load_metrics.py:RampRateTests`, `tests/test_performance_load_context.py` and `tests/test_performance_canonical_parity.py`.

### Requirement: Cycling eFTP and form are read from canonical observations only
The system SHALL read cycling eFTP and form only from canonical Intervals.icu observations (ride-scoped eFTP of the athlete record and of wellness days; wellness-day form) plus activity rows for the activity eFTP step. Without canonical inputs these values SHALL be absent rather than read from snapshot wellness rows or sport settings. Output keys and source labels stay unchanged apart from the ramp-rate label.

#### Scenario: No snapshot rows
- **WHEN** the snapshot has no wellness rows and no athlete sport settings but canonical observations exist
- **THEN** `metrics.cycling_eftp_watts`, `comparisons.cycling_eftp_30d`, `current_load.tsb` and `comparisons.form_tsb` equal the values computed from equivalent snapshot rows, apart from the known limits below.

#### Scenario: Carrier fields are ignored
- **WHEN** snapshot wellness rows still carry `tsb`, `rampRate` and `sportInfo`
- **THEN** none of them influences these values.

#### Scenario: Stale and multi-sport data
- **WHEN** the newest wellness day has no eFTP observation, or Run settings coexist with Ride settings
- **THEN** the current eFTP falls to the next step of its chain and the history keeps the older dated values; Run values never feed cycling eFTP.

Detailed contract (known limits, not requirements; tracked by a follow-up issue; the wellness mapper version 7 of Epic B did not change them): the mapper stores the last of two ride sport settings (the legacy reader took the first); a setting or `sportInfo` entry is classified by `types[0]` or `type` only, so entries identified solely by `sport` or `sport_type`, or by a later `types` entry, yield no eFTP; a reported form value that is not a number yields no form for that day.

Evidence: `backend/providers/intervals_wellness_mapping.py:map_intervals_wellness`, `backend/providers/intervals_wellness_mapping.py:map_intervals_athlete_thresholds`, `backend/performance/canonical_sections.py:read_wellness_observations`; `tests/test_intervals_wellness_mapping.py` (EFTP and FORM mapping), `tests/test_performance_canonical_parity.py`. The strict-read scenarios are verified by `tests/test_performance_canonical_load_metrics.py` (carrier rows are stripped or contradicting), `tests/test_performance_canonical_parity.py:_assert_load_metric_split` and `tests/test_server_performance.py`.
