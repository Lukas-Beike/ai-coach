# performance-and-readiness Specification

## Purpose

Describe deterministic local performance, training-load, readiness, recovery, body, history, and report projections. Provider forecasts and derived observations retain their evidence limits; these requirements do not claim medical or physiological validation. Intervals.icu is an output target only; scenarios that name stored Intervals.icu data describe rows of a database restored from a release before 2.0.0, which are not read.

## Requirements

### Requirement: Current performance metrics with explicit fallback
The system SHALL compose current body, cycling/running thresholds, VO2max, maximum HR, Zone-2 pace and running predictions from supported local provider/profile inputs with source and unit metadata. It SHALL use metric-specific local/Garmin/Wahoo/manual precedence, never reading Intervals.icu values (athlete decision 2026-11-07), preserve sport scope, and reject implausible values. Canonical and compatibility inputs SHALL preserve the same supported public metric shape without mutating callers.

#### Scenario: Garmin thresholds available
- **WHEN** plausible Garmin cycling FTP or running threshold values coexist with stored Intervals settings
- **THEN** current composition uses Garmin's for those supported metrics and exposes its source/unit/date metadata; the Intervals value is not an alternative.

#### Scenario: Fallback and no value
- **WHEN** Garmin has no value
- **THEN** the implemented manual or Wahoo fallback may supply that metric; if no eligible source exists its value remains unknown.

#### Scenario: Intervals.icu eFTP is not a current metric
- **WHEN** the current performance metrics are composed while ride or run eFTP observations or activity eFTP values are stored
- **THEN** no `cycling_eftp_watts` metric is composed and no stored Intervals.icu eFTP feeds a current value, W/kg, comparison or report; the stored observations stay unchanged as history.

#### Scenario: Intervals.icu settings are never current values
- **WHEN** only stored Intervals.icu data holds FTP, run threshold power, threshold or Zone-2 pace, threshold or maximum HR, VO2max, athlete weight, body fat, height, W′ or wellness weight
- **THEN** each of these current metrics is unknown (`w_prime_j` and the Zone-2 pace are not composed) and no current input carries an Intervals.icu field; a stored `intervals` source preference is ignored.

#### Scenario: Metric entries
- **WHEN** the current metrics are composed
- **THEN** each is `{value, unit, source, source_provider, note}`, with `source`, `source_provider` and `note` set only with a value and `alternatives` and `conflict` when another source holds a current value; the keys are `weight_kg`, `body_fat_pct`, `height_cm`, `cycling_ftp_watts`, `run_threshold_watts`, `run_threshold_pace_seconds_per_km`, `bike_threshold_hr_bpm`, `run_threshold_hr_bpm`, `cycling_max_hr_bpm`, `running_max_hr_bpm`, `max_hr_bpm`, `cycling_vo2max_ml_kg_min`, `running_vo2max_ml_kg_min` and the race predictions `run_5k_seconds`, `run_10k_seconds`, `run_half_marathon_seconds` and `run_marathon_seconds`; the performance context adds the 7-day totals `steps_7d`, `floors_7d` and `calories_7d`.

#### Scenario: Garmin read order
- **WHEN** several Garmin observations of one kind exist
- **THEN** the latest observed day wins; on one day a timed record beats an untimed one and the later time wins; the running VO2max is the newest running or sport-less value, the running one when the days are equal; the profile maximum heart rate of a sport is the highest value of that sport's latest day, so a lowered value wins.

#### Scenario: Local and profile labels
- **WHEN** a value comes from a locally confirmed zone configuration or from the profile
- **THEN** its source reads "Lokal" or "Manuell" and carries no provider id, and height comes only from the profile.

Evidence: `backend/performance/current_metrics.py:current_performance_metrics`, `backend/performance/canonical_current.py:read_current_inputs`; `tests/test_performance_current_metrics.py:test_garmin_priority_and_metric_shape`, `tests/test_performance_current_metrics.py:test_invalid_values_and_inputs_are_not_mutated`. The eFTP scenario is verified by `tests/test_performance_current_metrics.py:test_stored_eftp_is_not_a_current_metric` and `tests/test_performance_canonical_load_metrics.py:EftpTests`. The Intervals.icu scenario is verified by `tests/test_performance_canonical_current_metrics.py:IntervalsValuesAreNotCurrentTests`. Added evidence: `tests/test_characterization_current_metrics.py:test_result_keys_and_units_are_stable`, `tests/test_garmin_canonical_reads.py:test_max_hr_comes_from_the_latest_day_of_each_category`, `tests/test_garmin_canonical_reads.py:test_newer_generic_vo2max_replaces_an_older_running_value`.

### Requirement: LT1 per sport with the origin of each value
The current performance thresholds SHALL carry `first_thresholds`: LT1 of running and cycling, each value with its origin (`measured`, `estimated` for the adopted DFA-α1 value, `own_sessions`, `zone_2`, `fixed_share`), the same in the public state and for the Coach. A measured or adopted share, then own sessions (pace and power only, M9), then the top of zone 2 SHALL win over the fixed shares the athlete decided (2026-11-12, #2427).

#### Scenario: No measured or adopted value and no zones
- **WHEN** the profile holds no first threshold and the sport has no pace or power zones
- **THEN** the heart rate is 85 % of the threshold HR, run pace 88 % of the threshold speed and ride power 75 % of the FTP, all `fixed_share` (LTHR 172 bpm, 4:30 /km and 280 W give 146 bpm, 5:07 /km and 210 W); a value with neither its LT2 nor a zone 2 is left out, and a sport without any LT2 value has no LT1.

#### Scenario: Measured value and zone 2
- **WHEN** a measured or adopted share is stored, or heart-rate, pace or power zones are in effect
- **THEN** the heart rate uses that share with its origin, else the top of the heart-rate zone 2, and the pace or power the top of their zone 2 (`zone_2`); the other values keep the fixed share.

#### Scenario: Own steady sessions at the LT1 heart rate
- **WHEN** at least three ride or run sessions of the last 60 days hold at least 10 steady minutes (coefficient of variation at most 0.15) in the 10 bpm band of 5 bpm bins nearest to the sport's LT1 heart rate
- **THEN** LT1 run pace is 1000 s divided by the median of their speeds in the band (outdoor sessions before indoor ones for both sports), and LT1 ride power the median of their power, each paired with the mean power of the minute before the heart rate; the origin is `own_sessions`, shown as an estimate; with fewer sessions the zone 2 top or the fixed share applies.

Evidence: `backend/performance/pace_at_hr.py:output_at_heart_rate`, `backend/performance/pace_at_hr.py:power_at_heart_rate`, `backend/performance/current_metrics.py:first_thresholds`, `backend/activities/zone_settings.py:zone_two_top`, `backend/performance/context.py:current_performance_context`, `backend/coach/context.py:CoachPerformanceContextReader`; `tests/test_current_thresholds.py:FirstThresholdTests`, `tests/test_pace_at_hr.py:OutputAtHeartRateTests`, `tests/test_characterization_coach_context.py:test_lt1_power_is_the_configured_zone_two_or_else_a_share_of_the_ftp`, `tests/test_coach_domain_sections.py:test_source_policy_texts_are_built_from_labels`.

### Requirement: Load rollups and the local current load
The system SHALL calculate current/previous 7- and 30-day completed-activity rollups from known completed loads. The current load block (`current_load` `ctl`, `atl`, `tsb`) SHALL be the latest valued day of the local fitness, fatigue and form (M7); stored Intervals.icu CTL, ATL and form SHALL NOT be shown. Activity-derived load SHALL not be presented as Garmin's device-reported acute load.

#### Scenario: Multiple sessions and rest days
- **WHEN** a day contains several completed loads and later days have no activity
- **THEN** rollups sum known contributions and the local curve decays over the rest days instead of copying a future planned load.

#### Scenario: Sessions without a TSS-scale load
- **WHEN** a rollup window holds sessions without a stored local TSS-scale load (M6), such as a strength session or a session without power, pace or heart-rate inputs
- **THEN** the rollup reports how many sessions were left out of the load sum, and the rollup reports their known session-RPE load in AU beside the sum, with the labels of its RPE sources, never added to it.

#### Scenario: Provider loads are not summed
- **WHEN** a session carries an Intervals.icu training load, a Wahoo TSS or a Garmin load
- **THEN** the rollup sums only the session's local load; the provider value stays on the summary as `provider_training_load` for cross-checking.

#### Scenario: Missing or conflicting Garmin acute load
- **WHEN** no dated valid measured acute-load value exists or device values conflict
- **THEN** Garmin acute-load history leaves the date unknown instead of reconstructing it from daily/chronic activity totals.

#### Scenario: Stored Intervals.icu form is not shown
- **WHEN** the latest wellness day holds Intervals.icu CTL, ATL or form observations
- **THEN** the performance context has no `intervals_load_history` and `current_load` never takes these values.

#### Scenario: No local load
- **WHEN** no local load is stored, or only warm-up days exist
- **THEN** `current_load` `ctl`, `atl` and `tsb` are unknown with the M7 status and reason, whatever Intervals.icu holds.

#### Scenario: Rollup windows and fields
- **WHEN** the performance load context is built
- **THEN** it rolls up `last_7`, `previous_7` (ending 7 days ago), `last_30`, `previous_30` (ending 30 days ago) and `base_30_before_7` (the 30 days ending 7 days ago, the base of the volume comparison) over inclusive athlete-local days, and the context serves them as `rolling_training.last_7_days`, `previous_7_days`, `last_30_days`, `previous_30_days` and `last_28_days`; a rollup reports `days`, `sessions`, `duration_hours` (the sessions' leading duration, one decimal), `training_load` (the sum of local loads, one decimal), `electric_assist_hours` when an e-bike session is in the window and, for sessions without a local load, `load_missing_sessions`, `load_missing_session_rpe_au` (one decimal) and `load_missing_session_rpe_source` (the sorted source labels, comma-separated).

Detailed contract: rollups sum multiple known loads on the same day. `current_load` carries the source `Lokal berechnet (M7)`, the method id and version, status and reason, the count of incomplete days and `averages_7d`; no ATL is reconstructed from Intervals.icu ATL.

Evidence: `backend/performance/load.py:activity_rollup`, `tests/test_performance_load.py:test_sessions_without_a_tss_scale_load_are_counted_with_their_rpe_load`, `tests/test_local_load_store.py`, `backend/performance/load_context.py:performance_load_context`, `backend/performance/garmin_load.py:acute_load_value`; `tests/test_performance_load_context.py`, `tests/test_performance_chart_history.py:test_garmin_acute_load_is_dated_and_never_derived_from_daily_or_chronic_load`, `tests/test_performance_chart_history.py:test_acute_load_rejects_invalid_and_conflicting_device_values`. The history and local-load scenarios are verified by `tests/test_performance_canonical_load_metrics.py:FormTests`, `tests/test_performance_load_context.py:test_the_inputs_hold_no_intervals_load_and_the_context_no_history` and `tests/test_characterization_load_focus.py:CharacterizationLoadContextTests`. Added evidence: `tests/test_performance_load_context.py:test_rollup_windows_include_boundaries_and_have_previous_windows`, `tests/test_performance_load_context.py:test_volume_base_window_edges`.

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

#### Scenario: Report request limits
- **WHEN** a report (method `local-training-report-v1`) is requested through `get_training_report`
- **THEN** the period is 7 or 28 days from a start between 2010-01-01 and today (default the Monday of the current week and 7 days) and the sport filter is `all` or a canonical sport, a former provider token such as `VirtualRide` resolving to its canonical sport; a start that is not a date, lies in the future or before 2010, other days, or an unknown sport or one longer than 40 characters fail with 400 "Ungültiger Berichtszeitraum." or "Ungültiger Berichtszeitraum oder Sportfilter.".

#### Scenario: Report content limits
- **WHEN** a report lists sessions, check-ins and feedback
- **THEN** `key_sessions` are the three sessions with the highest local load, names are cut at 200 characters, check-in notes at 400, feedback notes and deviation reasons at 500 and at most 100 feedback rows are listed; only all-sport reports carry the M5 and M7 curves.

Detailed contract: The report `observed_at` SHALL be the activity sync time defined in activity-ingestion-and-storage (Garmin and Wahoo coverage), or null when none is stored. Totals are named `moving_duration_s`, `distance_m` and `training_load`; `sports` and sport filters use canonical sports (`ride`, `run`, ...).

Evidence: `backend/performance/training_report.py:training_report`; `tests/test_training_report.py`. Added evidence: `backend/performance/report_service.py:TrainingReportReadService.read`, `backend/performance/report_service.py:report_sport`, `tests/test_report_sport_filter.py`.

### Requirement: Training focus and recorded sensor zones
The system SHALL summarize the supported 28-day training focus from recorded heart-rate and power zones and Garmin activity training-effect categories with source freshness and classification coverage. Heart-rate and power zones SHALL remain separate and bounded by session coverage. Unknown categories, missing identities/load, and unsupported strength classification SHALL remain unclassified rather than becoming assumed endurance training.

#### Scenario: Known Garmin category and load
- **WHEN** an identified activity has a supported recorded primary-effect category and usable load
- **THEN** its contribution enters the corresponding low-aerobic, high-aerobic, or anaerobic category with source coverage.

#### Scenario: Sensor or category gap
- **WHEN** a session has only one sensor's zone times or lacks a supported category
- **THEN** that sensor remains separate and missing category evidence increases unknown coverage rather than being inferred from another sensor.

#### Scenario: Categories from canonical sessions
- **WHEN** the training focus is composed
- **THEN** the categories come only from the canonical activity summaries: each session with a Garmin Connect record in the window counts once, dated in the profile zone like the zone distribution and classified by its `training_effect_label` and `training_effect_load` (Garmin activity mapper version 8; at ingest and at re-projection the stored, accumulated dedicated training-load row of the activity is merged in, the same payload's rows winning, so the values do not depend on which sections a sync fetched); the Garmin sync status supplies only the category freshness and whether dedicated training-load rows are stored, and the raw Garmin view is not read.

#### Scenario: Category map and periods
- **WHEN** a session's `training_effect_label` is read
- **THEN** `RECOVERY`, `AEROBIC_BASE` and `LOW_AEROBIC` count as `low_aerobic`; `TEMPO`, `THRESHOLD`, `LACTATE_THRESHOLD`, `VO2_MAX`, `VO2MAX` and `HIGH_AEROBIC` as `high_aerobic`; `ANAEROBIC_CAPACITY`, `SPEED` and `ANAEROBIC` as `anaerobic`; any other label, or a missing load, stays unclassified; the focus is served for 28 days in the performance context and for 14 and 84 days in `/api/performance` as `training_focus_periods.fortnight` and `.twelveWeeks`.

Evidence: `backend/performance/training_focus.py:training_focus`, `backend/performance/training_report.py:zone_distribution`; `tests/test_training_focus.py:test_recorded_hr_and_power_zones_remain_separate_and_bounded`, `tests/test_training_focus.py:test_activity_without_identity_is_not_a_session`, `tests/test_training_report.py:test_sensor_zones_stay_separate_and_strength_is_not_classified_as_endurance`. Added evidence: `tests/test_training_focus.py:test_focus_uses_exactly_four_weeks_including_today`.

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

#### Scenario: No eFTP history
- **WHEN** the analysis performance charts, the body W/kg history or the 30-day comparisons are composed while Intervals.icu eFTP observations are stored
- **THEN** no eFTP series or `cycling_eftp_30d` comparison is composed, and the W/kg series divides only Garmin's dated FTP.

#### Scenario: Form comparison reads canonical form days
- **WHEN** the 7-day form comparison is composed
- **THEN** it averages the form observations of the inclusive seven days ending on the current day, and the average is unknown when no day has an observation.

#### Scenario: History, charts and comparisons read canonical inputs only
- **WHEN** the analysis charts, the Garmin load, training-load projection and Garmin 30-day comparisons (including weight) are composed
- **THEN** they read the canonical activity rows and the canonical Garmin day history only (the weight trend uses the body history's per-day Garmin weights); the Garmin sync status supplies Garmin sync times and a cached provider chart's fetch outcome (stale, failed or unsupported; never its points), and without canonical inputs (`EMPTY_PERFORMANCE_INPUTS`) every such value is unknown.

#### Scenario: Daily steps and floors come from canonical Garmin days
- **WHEN** the analysis history is composed
- **THEN** `daily_activity` lists the 90 days with the canonical Garmin steps and floors climbed of each day, labelled with the Garmin source and provider; a real zero stays zero and a day without an observation is a gap.

#### Scenario: Power profile reads only the local curve
- **WHEN** the analysis cycling power profile is shown while Intervals.icu power curve rows are stored
- **THEN** its best power per duration comes only from the local mean-maximal curve of the last 90 days; the analysis history has no `cycling_power_profile` and the stored Intervals.icu power curve feeds no view.

#### Scenario: History payload
- **WHEN** the analysis history is composed
- **THEN** `performance.history` covers the 90 days ending today (`start`, `end`, `days`) and carries `load` (Garmin's acute load per day), `daily_activity`, `training_time` (per day the hours of the sessions' leading durations, each above 0 and at most 86400 s, two decimals, source "Garmin Connect, Wahoo"), `metrics` (one Garmin series each for `cycling_ftp_watts`, `run_threshold_pace_seconds_per_km`, both VO2max keys and the four race predictions, a value outside its kind's plausibility bounds left as a gap), `provider_metrics`, `body` and `preferred_providers`; a day without a value is a point with value null.

#### Scenario: Provider charts
- **WHEN** `provider_metrics` is composed
- **THEN** it holds `endurance_score`, `running_tolerance` and `training_readiness_history` with aggregation `daily` and `weekly_training_status` with `weekly`; a day with an endurance group value shows only the group values; the status is `current` with points, else `unavailable`, unless the cached fetch outcome is `stale`, `failed` or `unsupported`, and `observed_at` is the newest point's day.

Detailed contract: race predictions, endurance scores, running tolerance, readiness history, and weekly training status SHALL retain their supported observation dates and aggregation metadata.

Evidence:
- `backend/performance/chart_history.py:_canonical_provider_metrics`
- `backend/performance/chart_history.py:analysis_history`
- `backend/performance/comparisons.py:performance_comparisons`
- `backend/performance/report_service.py:TrainingProfileSelectionService`
- `tests/test_characterization_body_history.py:test_provider_metrics_keep_cached_status_or_fall_back_to_unavailable`
- `tests/test_characterization_body_history.py:test_training_time_value_bounds_and_missing_fields`
- `tests/test_performance_chart_history.py:test_sources_remain_separate_with_no_backdating_of_current_settings`
- `tests/test_performance_chart_history.py:test_race_prediction_history_does_not_backfill_current_estimates`
- `tests/test_performance_chart_history.py:test_steps_and_floors_come_from_canonical_garmin_days`
- `tests/test_training_report.py:test_running_speed_selects_fastest_effort_and_distance_selects_shortest`. The canonical-inputs scenario is verified by `tests/test_chart_history_canonical_parity.py`
- `tests/test_garmin_training_load_canonical_parity.py`
- `tests/test_performance_comparisons.py` and `tests/test_performance_canonical_parity.py:test_empty_performance_inputs_stand_for_no_canonical_values`. The power profile scenario is verified by `tests/test_performance_chart_history.py:test_history_has_no_intervals_power_curve` and `tests/analysis-presentation.test.cjs`. The eFTP and form scenarios are verified by `tests/test_performance_comparisons.py:test_eftp_is_not_compared_and_form_compares_the_local_values`
- `tests/test_characterization_body_history.py` and `tests/test_performance_canonical_load_metrics.py:test_chart_and_body_history_have_no_eftp_series`.

### Requirement: Current and planning recovery sources
The system SHALL compose sleep, resting HR, HRV, readiness, averages and planning day recovery with explicit source/date. Sleep, HRV and resting HR SHALL keep one method family, Garmin's night values by default; readiness is Garmin's; Intervals.icu is never a source. Per-day planning values SHALL use their date-specific source priority and the current rules' bounds, preserve absent days, and include morning Body Battery. Source freshness SHALL distinguish measurement date from fetch time.

#### Scenario: Readiness is Garmin's
- **WHEN** Intervals readiness and Garmin readiness coexist for the supported current/day context
- **THEN** the Garmin readiness is used; with only Intervals readiness it is unknown.

#### Scenario: Recently fetched old measurement
- **WHEN** a source was fetched recently but its latest measurement is old or missing
- **THEN** source metadata reports measurement age/unknown status rather than treating the fetch time as proof of a current reading.

#### Scenario: Current recovery values come from canonical observations only
- **WHEN** the current performance context is composed
- **THEN** sleep duration/hours, sleep score, resting HR, HRV and readiness, their 7-day averages, source labels and Garmin measurement dates are derived only from canonical observations; values present only in the raw Garmin view or only in snapshot wellness carrier fields are not shown, and without canonical inputs these values are absent rather than read from provider data.

#### Scenario: Averages use Garmin days only
- **WHEN** a current sleep, HRV, resting HR or readiness value is selected
- **THEN** its 7-day average uses only the daily Garmin values in the seven days ending on the current day.

#### Scenario: Intervals.icu never fills Garmin gaps
- **WHEN** Garmin night HRV, sleep or resting HR exists and Intervals.icu holds values of the same kind, equal to Garmin's or not
- **THEN** neither the current value nor any planning day takes the Intervals.icu value, and with only Intervals.icu values the metric is unknown.

#### Scenario: Garmin-only recovery
- **WHEN** only Garmin recovery observations exist
- **THEN** the Garmin values are still selected for the current recovery context and personal baselines.

#### Scenario: Freshness fields and notes
- **WHEN** a Garmin metric is shown
- **THEN** it carries `freshness`, `fetched_at`, `observed_at`, `measurement_status` (`today`, `earlier`, `future` or `unknown`) and `measurement_age_days`; a measurement older than today adds the note "Messung ist N Tage alt; das Abrufdatum ist keine neue Messung.", a stale source with a value "Letzter guter Wert; Quelle nicht aktualisiert" and a partial one "Quelle nur teilweise aktualisiert".

#### Scenario: Freshness section of a metric
- **WHEN** the freshness of a Garmin metric is read
- **THEN** it follows the sync section `weight` for weight, `cycling_ftp` for the cycling FTP, `heart_rate_zones` or `activities` for a maximum heart rate (by whether a profile value exists), `max_metrics` for VO2max, `race_predictions` for the predictions, `daily_stats` for the daily totals and `running_threshold` for every other threshold, the cycling threshold heart rate included.

Evidence: `backend/performance/source_policy.py:select_daily`, `backend/performance/recovery_context.py:performance_recovery_context`, `backend/performance/planning_recovery.py:planning_recovery_view`, `backend/performance/freshness.py:garmin_source_freshness`; `tests/test_source_policy.py:CurrentSelectionTests`, `tests/test_planning_canonical_recovery.py:CanonicalPlanningRecoveryTests.test_an_intervals_series_fills_no_garmin_gap`, `tests/test_performance_planning_recovery.py:test_saved_and_current_morning_body_battery`, `tests/test_performance_freshness.py:test_current_stale_partial_unknown_and_notes`, `tests/test_performance_recovery_context.py`, `tests/test_characterization_recovery.py`.

### Requirement: Personal recovery comparison and sleep goal shortfall
The system SHALL form personal recovery distributions separately by provider and measurement method, exclude the current reading from its comparison distribution, require at least 14 prior matching nights for provisional classification and 28 for full classification, and leave stale/future evidence unclassified. Only Garmin's sleep duration, resting HR and RMSSD form series; SDNN nights are never classified.

#### Scenario: Baseline coverage thresholds
- **WHEN** a current reading has 13, 14, or 28 prior matching nights
- **THEN** its classification is insufficient, provisional, or fully supported respectively, and the current reading does not shift the comparison median.

#### Scenario: Missing nights or sleep target
- **WHEN** fewer than seven recent nights are known or no explicit valid sleep target exists
- **THEN** shortfall coverage is partial or no target-based shortfall is produced; missing nights are not imputed.

#### Scenario: Baselines read daily canonical observations
- **WHEN** personal comparisons and the sleep goal shortfall are computed, with or without a stored snapshot
- **THEN** Garmin's daily sleep duration, resting HR and RMSSD observations form the series, with the existing bounds and measurement labels; raw provider views are not read, and without canonical inputs no comparison is produced.

#### Scenario: Gap or stale value
- **WHEN** a day is missing or the newest value is older than yesterday
- **THEN** missing days are not filled from another source, and stale or insufficient series report the same insufficient/stale status as before.

#### Scenario: Series, window and bounds
- **WHEN** the comparisons are built
- **THEN** Garmin sleep duration (hours), resting heart rate and nightly RMSSD each form one series from the daily observations of the last 84 days; a value that is not positive, a sleep duration above 24 hours or a resting heart rate outside 20 to 230 bpm is left out; quartiles use the inclusive method; a series is current when its newest value is from today or yesterday.

#### Scenario: Seven-day ln(RMSSD) comparison
- **WHEN** the RMSSD series has at least 3 nights in the 7 days ending with its latest night and at least 14 nights from 48 to 7 days before it, all since the latest measurement change
- **THEN** `rolling` reports `mean_ms` (the exponential of the window's mean ln), `lower_ms` and `upper_ms` (the exponential of the baseline's mean ln minus and plus 0.5 SD), each to 0.1 ms, `position` (`below`, `within`, `above`) and `cv_pct` (the SD of the window's ln values over their mean, to 0.1, null when that mean is not positive), with status `ok` from 5 window and 28 baseline nights, else `provisional`.

#### Scenario: Seven-day comparison withheld
- **WHEN** the latest value is stale or a night count is too low
- **THEN** `rolling` has status `insufficient_data`, the night counts and the reason "Messung veraltet.", "Mindestens 3 Nächte in den letzten 7 Tagen erforderlich.", "Mindestens 14 frühere passende Nächte vor den letzten 7 Tagen erforderlich." or, after a measurement change, "Messkontext geändert; mindestens 14 passende Nächte vor den letzten 7 Tagen seitdem erforderlich.".

#### Scenario: Measurement change restarts the comparison
- **WHEN** the method, aggregation or measurement context (device model, firmware, algorithm, sensor, window, protocol) of an HRV or resting HR provider series changes inside the 42-day window, including a switch between unknown and known metadata
- **THEN** only values since the latest change form the comparison distribution, older values stay in the history, the baseline reports the change day as `context_changed_on`, and below 14 values since the change it has no position and the reason names the change; a series without a reported device model reports `continuity` `unknown`, which the recovery info shows as "Messkontext unbekannt"; API, UI and Coach read the same baseline fields, but the Coach does not receive the provider-reported `measurement_context` text.

#### Scenario: Quartile position is a comparison, not a norm
- **WHEN** a recovery value lies below or above the quartile range of the athlete's earlier values
- **THEN** every API, UI and Coach text describes it as a position relative to the athlete's own earlier values, states that the middle two quartiles hold about half of the values, and derives no diagnosis, training clearance or training change from it.

#### Scenario: Product rules are not validity claims
- **WHEN** a comparison is provisional, `ok`, insufficient or stale
- **THEN** the displayed state names the coverage or reason (for example fewer than 14 earlier nights or an outdated measurement) and the recovery UI shows no "confirmed" or equivalent validity wording for it.

#### Scenario: Shortfall is not sleep debt
- **WHEN** the sleep goal shortfall is reported or summarized
- **THEN** it is worded as the sum of known shortfalls against the athlete's own sleep goal over known nights, with missing nights and unrecorded naps noted as limits, and no output uses the term sleep debt or states a needed number of hours of recovery sleep.

Detailed contract: The quartile range (method `personal-quartiles-v1`) SHALL be described only as a comparison with the athlete's own earlier values and SHALL not be described as a normal, healthy, abnormal or clinical range, and a position below or above it SHALL not be described as an alarm or deficiency. The 14/28-night thresholds, the 42-day window and the status `ok` are product rules and SHALL not be presented as validity, confirmation or a health standard. The sleep goal shortfall SHALL require an explicit valid sleep target, sum only known-night shortfalls against that target, and never offset them with excess sleep on another night; it SHALL not be called sleep debt or presented as a recovery need. Sleep duration SHALL be described as the provider's device estimate, not as measured sleep need. The seven-day ln(RMSSD) comparison (method `rolling-lnrmssd-v1`, #1772) SHALL follow the same wording limits: its range is the mean ± 0.5 SD of the athlete's own earlier nights, a seven-day mean below it SHALL not be called a recovery deficit, and its coefficient of variation SHALL be shown without rating.

Evidence:
- `backend/performance/personal_recovery.py:_add_record`
- `backend/performance/personal_recovery.py:personal_recovery`
- `public/analysis.js:recoveryReferenceLabel`
- `backend/performance/rolling_hrv.py:rolling_lnrmssd`
- `public/analysis.js:recoveryRollingNote`
- `tests/test_rolling_hrv.py`
- `tests/test_personal_recovery.py:test_coverage_and_excluding_current_value_from_baseline`
- `tests/test_personal_recovery.py:test_future_stale_and_sdnn_nights_are_not_classified`
- `tests/test_personal_recovery.py:test_deficit_uses_known_nights_and_never_offsets_with_long_sleep`
- `tests/test_personal_recovery.py:test_device_change_restarts_the_comparison`
- `tests/test_personal_recovery.py:test_unknown_metadata_is_its_own_context_with_unknown_continuity`
- `tests/test_personal_recovery.py:test_a_change_before_the_window_is_not_reported`; wording and Coach cases, including the M3 sleep cases `SleepCoachCases`, in `tests/test_performance_claim_wording.py` and `tests/test_personal_recovery_coach_cases.py`
- `e2e/analysis-info.spec.js` recovery scenarios. Claim lists: `docs/performance-methods/m2-hrv-resting-hr.md`
- `m3-sleep-duration-timing.md`.

### Requirement: Sleep timing and tagged-day associations
The system SHALL derive sleep timing variability (method `sleep-timing-variability-v3`) from validated dated onset/wake intervals with timezone/DST-aware duration and separate source/method series, and SHALL keep insufficient coverage explicit. Tagged-day analysis SHALL use only explicit boolean answers paired with the following provider-dated night, require ten measured days per comparison group, and label results as observed associations rather than causal effects or inferred answers.

#### Scenario: Sleep across midnight or DST
- **WHEN** valid sleep intervals cross midnight or a clock change
- **THEN** local timing comparisons use circular timing logic and actual interval duration while source/method series remain separate.

#### Scenario: Unanswered tag
- **WHEN** a day has no explicit tag answer or no measured following night
- **THEN** it is excluded from both groups rather than treated as a negative answer; insufficient groups expose no confident association statistic.

#### Scenario: Fewer than 14 earlier intervals
- **WHEN** a timing series has fewer than 14 earlier intervals in the 42-day window
- **THEN** its status is `insufficient_data` with the reason and count, and its onset/wake medians and every per-night deviation are null (#1429).

#### Scenario: Source without canonical sleep periods
- **WHEN** sleep timing variability is computed from a source that stores no canonical sleep periods
- **THEN** the result is `insufficient_data`; the stored provider sleep and wellness records are not read (#1416).

#### Scenario: Timing variability is not the Sleep Regularity Index
- **WHEN** the timing variability result, its Coach report section or any description of it is produced
- **THEN** the method id and section name are `sleep-timing-variability-v3` and `sleep_timing_variability`, and the Sleep Regularity Index or SRI appears only in a sentence that denies the equivalence.

#### Scenario: Dating of nights
- **WHEN** Garmin sleep periods are read
- **THEN** each period is dated by its end in the profile time zone, the latest period of a day is kept (a night read in the profile zone is never displaced by one read elsewhere) and the last 84 days count; the overall status is the best status of the series.

#### Scenario: Circular median and deviation
- **WHEN** at least 14 earlier nights of the last 42 days exist
- **THEN** the onset and wake medians are the observed clock minutes (hour × 60 + minute) that minimise the summed circular distance on a 1440-minute day, and each night's deviation is its circular distance to that median, rounded to 0.1 minute; the series is `provisional` from 14 and `ok` from 28 earlier nights.

#### Scenario: Tagged-day result
- **WHEN** the tagged-day analysis (`explicit-tags-next-night-v1`) runs
- **THEN** each check-in day of the last 84 days before today with an explicit boolean answer for a tag is paired with the value of the following night, per recovery series and tag; with at least 10 paired days in both groups the status is `observed_association` and each group shows `days`, `median`, the inclusive lower and upper quartile, `load_median` and `load_known_days` (days with sessions that all have a local load), `co_tag_days` and at most 50 evidence rows; otherwise the status is `insufficient_data` and median and quartiles are null.

Detailed contract: Sleep timing variability compares each night's clock times circularly with the athlete's own earlier nights; it is not the Sleep Regularity Index and SHALL NOT be named, labelled or described as such, and no output SHALL share that name.

Detailed contract: the timing result carries per series `status`, `reason`, `coverage` (`baseline_nights`, `valid_nights_42_days`, `required_nights` 14, `provisional_until_nights` 27), `baseline` (the onset and wake medians and the medians of their deviations over all 84 days of points), `points`, `points_14` and `points_84` (one entry per day, with null fields for a day without a night).

Evidence: `backend/performance/personal_recovery.py:sleep_timing_variability`, `backend/performance/tag_impact.py:tag_impact`; `tests/test_personal_recovery.py:test_sleep_timing_variability_circular_midnight_median_and_sources`, `tests/test_personal_recovery.py:test_sleep_intervals_reject_future_missing_and_reversed_and_keep_dst_duration`, `tests/test_performance_method_inputs.py:M3SleepInputs`, `tests/test_training_record_features.py:test_tag_impact_requires_ten_measured_days_in_each_explicit_group`, `tests/test_performance_claim_wording.py`. Added evidence: `tests/test_sleep_timing_timezone.py`, `tests/test_sleep_timing_variability_canonical_parity.py`.

### Requirement: Morning Body Battery sample recovery
The system SHALL derive a morning reading from validated Garmin samples around actual sleep, retain date/attempt/status metadata, and use bounded retry/cache decisions. Automatic morning refresh SHALL start no earlier than 05:00 athlete-local time, use at most three attempts with fifteen-minute retry spacing, and stop repeating a ready reading; with a Garmin Personal API key it SHALL wait for the stored night or 12:00 instead of polling.

#### Scenario: Sleep bounds and both samples available
- **WHEN** a valid before-sleep and first post-sleep sample exist in the allowed windows
- **THEN** the stored day becomes ready with both measurement timestamps and Garmin source, and subsequent cache reads report already loaded.

#### Scenario: Missing samples or failed request
- **WHEN** sleep bounds/samples are unavailable or the provider fails
- **THEN** the day retains a safe unavailable/error outcome and attempt metadata, retries respect spacing/count, and no Body Battery level is inferred from charged/drained totals.

#### Scenario: Stored as derived observations
- **WHEN** a canonical morning refresh derives the night's levels
- **THEN** the before-sleep and morning levels are stored as local derived observations of the night (`body_battery_before_sleep`, `morning_body_battery`, method `morning_body_battery`, at their sample time), a later or failed refresh of that night retires its earlier rows, the Garmin state view keeps the refresh bookkeeping and the sleep bounds but no levels, and readers get the record assembled from both; a record stored before this keeps its inline values until its night is refreshed.

#### Scenario: Retry decisions
- **WHEN** a refresh finds the stored record of the night
- **THEN** the decision is `already_loaded` for a ready record, `attempts_exhausted` after three counted attempts and `retry_wait` while the last attempt is under 900 seconds old; a refresh that finds no night yet is not counted as an attempt and, from 12:00 athlete-local time of the check-in day on, the decision is `attempts_exhausted`.

#### Scenario: Samples
- **WHEN** Body Battery samples are read
- **THEN** only levels of 0 to 100 with a valid timestamp count, rounded to whole numbers, one per timestamp; the sleep bounds of a raw payload are the first valid start and end pair found breadth-first, `dailySleepDTO` first, within 100 visited nodes and the first 50 items of each list; the record is ready only with both a before-sleep and a morning level.

#### Scenario: Refresh results
- **WHEN** a morning refresh runs
- **THEN** it answers `cancelled` when its cancel signal is set before the provider request, `already_running` when the shared lock is not free within the wait and `not_configured` without Garmin access; a stored result is `{status, sleep_date, records}` with `failed: true` after a provider error; with an explicit check-in day the 05:00 gate does not apply, without one a refresh before 05:00 athlete-local time does nothing.

#### Scenario: Provider event
- **WHEN** a result is stored
- **THEN** a `provider` event for Garmin, area `performance`, is published with status `ready` or `degraded`, and stored Body Battery errors are cleared.

Detailed contract: Before-sleep samples SHALL be limited to four hours before sleep; morning samples SHALL fall between sleep end and at most one hour later, bounded by the attempt instant.

Evidence: `backend/performance/morning_battery.py:morning_body_battery_record`, `backend/performance/morning_battery.py:cached_result`, `backend/performance/morning_battery_service.py:MorningBodyBatteryService.refresh`, `backend/performance/morning_battery_service.py:MorningBatteryStore.current_in`; `tests/test_morning_battery_canonical.py:test_values_are_derived_observations_not_view_entries`, `tests/test_morning_battery_canonical.py:test_a_later_refresh_retires_the_nights_earlier_values`, `tests/test_morning_battery_service.py:test_refresh_before_five_is_noop_and_logs_failure_after_five`, `tests/test_morning_battery_service.py:test_cache_decisions_short_circuit_without_lock_or_remote`, `tests/test_morning_battery_service.py:test_remote_success_uses_injected_transport_and_persists_ready_values`. Added evidence: `tests/test_morning_battery.py:test_missing_night_is_not_an_attempt_and_waits_until_cutoff`, `tests/test_morning_battery.py:test_retry_wait_is_strictly_less_than_nine_hundred_seconds`, `tests/test_morning_battery.py:test_search_stops_after_one_hundred_nodes`, `tests/test_morning_battery_service.py:test_cancelled_refresh_skips_lock_and_provider`, `tests/test_morning_battery_service.py:test_not_configured_and_lock_contention_keep_status_and_lock_semantics`.

### Requirement: Body history, power-to-weight, and daily health
The system SHALL retain dated weight/body-fat histories and daily energy/count measurements with valid units, source freshness, and gaps. Historical power-to-weight SHALL use eligible dated FTP and sufficiently recent measured weight rather than current manual profile values projected backward. Supported daily energy SHALL distinguish total/active components. Provider projections SHALL keep unsupported optional values unknown instead of assuming zero or inventing a derived measurement.

#### Scenario: Same-day body measurements
- **WHEN** multiple valid provider weigh-ins occur on a day
- **THEN** supported timestamp ordering selects the daily measurement while weight/body-fat unit handling remains independent.

#### Scenario: Missing historical weight or FTP
- **WHEN** historical FTP lacks an eligible recent measured weight or only current profile weight is available
- **THEN** historical power-to-weight remains unknown and no manual current value is backfilled into the series.

#### Scenario: Body history reads canonical inputs only
- **WHEN** the body history is composed for the performance view or the state bootstrap
- **THEN** Garmin weight, body fat and FTP come from the canonical Garmin observations read with the performance inputs; Garmin values present only in the stored view are not shown.

#### Scenario: Daily totals come from canonical observations only
- **WHEN** the 7-day steps, floors and energy averages are composed
- **THEN** they average the canonical daily observations only; Garmin daily stats in the stored view supply freshness, never values.

#### Scenario: Body history windows and series
- **WHEN** `body` is composed
- **THEN** it has `version` 1, `default_window` `12w` and the windows `14d` and `12w` (84 days), each with `weight_kg`, `body_fat_pct` and `cycling_w_per_kg` as lists of series; a series has daily `points` and `weekly` rows over fixed 7-day buckets from the window start (the bucket's latest value to two decimals, `count`, `dates`); per day the last Garmin reading inside its bounds counts, a timed reading after an untimed one (a time without a zone is read as UTC), weight within 30 to 300 kg and body fat within 2 to 70 % to two decimals, and a future day never counts.

#### Scenario: Power-to-weight point
- **WHEN** a day holds a Garmin FTP
- **THEN** the point divides it by the newest weight from the seven days before the day up to the day (the preferred body source's own newest weight first; three decimals) and names `ftp_watts`, `weight_kg`, `weight_source`, both observation and sync times and `weight_age_days`; without such a weight it carries only the FTP.

#### Scenario: Daily-total averages end yesterday
- **WHEN** `steps_7d`, `floors_7d` and `calories_7d` are composed
- **THEN** they average the seven days ending yesterday and today's running total is not part of them; steps and floors are whole numbers and energy has two decimals, with the units "Schritte/Tag", "Stockwerke/Tag" and "kcal/Tag" and the note "Durchschnitt der letzten 7 Tage".

Evidence: `backend/performance/body.py:body_history`, `backend/performance/canonical_body.py:read_body_inputs`, `backend/performance/daily_health.py:read_daily_health_by_date`; `tests/test_performance_canonical_body_history.py:test_snapshot_garmin_values_are_ignored_without_canonical_values`, `tests/test_performance_body.py:test_ftp_sources_and_weight_age_limit`, `tests/test_performance_body.py:test_manual_profile_values_are_not_historical_and_invalid_garmin_values_drop`, `tests/test_performance_daily_health.py:CanonicalDailyHealthParityTests.test_metrics_window_ignores_the_snapshot_daily_stats`. Added evidence: `tests/test_characterization_body_history.py:test_w_per_kg_weight_window_is_seven_days_inclusive_and_never_looks_forward`, `tests/test_performance_canonical_body_history.py:test_last_in_bounds_observation_wins_per_day`, `tests/test_performance_context.py:test_garmin_source_freshness_and_daily_health_window_are_explicit`.

### Requirement: Observed season preparation
The system SHALL separate observed competition preparation from calendar phase, expose supported 12-week sport-specific training/long-session evidence and nullable target context, and keep absent evidence unknown.

#### Scenario: Past competition evidence
- **WHEN** preparation for a past competition is read
- **THEN** the evidence window ends at that competition's date rather than borrowing later training; future competitions retain current evidence through today without claiming race readiness or a race-time prediction.

Evidence: `backend/performance/report_service.py:TrainingSeasonReadService.season`, `backend/planning/season_preparation.py:season_preparation`; `tests/test_season_preparation.py:test_past_competition_window_is_anchored_at_event_date`.

### Requirement: Versioned method evidence cards
Every local performance or recovery method with a planned or offered physiological interpretation SHALL have a versioned evidence card in `docs/performance-methods/`. Each card SHALL record construct, formula, sources, population, protocol, exclusion and stop rules, deviations, classification, claim list and review state. Every numeric rule SHALL be tagged `source` or `product assumption` with a rationale. No numeric evidence confidence SHALL be invented.

#### Scenario: Card is incomplete
- **WHEN** a card lacks a required section, has a numeric rule without a valid tag or rationale, or cites an evidence ID missing from the register
- **THEN** the repository card check fails.

#### Scenario: Deferred method
- **WHEN** a method family is recorded as deferred in the register (passive CP/CS, other TRIMP uses, further threshold or VO2max estimates, W′ balance, HRV-based recommendations)
- **THEN** it has no card and produces no output until its own work package adds one.

Evidence: `docs/performance-methods/README.md` and the ten method cards M1 to M10; `tests/test_performance_method_cards.py`.

### Requirement: Claim lists bound physiological statements
API, UI and Coach output SHALL NOT make statements that the method's card forbids. A physiological interpretation SHALL stay blocked until the independent review recorded on its card releases it; descriptive statements that the card allows MAY be shown before that review.

#### Scenario: Interpretation not yet reviewed
- **WHEN** a card records the interpretation as `blocked`
- **THEN** the method is limited to the card's descriptive statements, and no training clearance, diagnosis or model-based recommendation is derived from it.

#### Scenario: Reviewed interpretation
- **WHEN** the card records `released` with date and reviewer for an interpretation
- **THEN** implementations may present exactly the allowed statements for it, with the card's limits and status.

#### Scenario: Recovery wording is enforced at runtime
- **WHEN** the runtime sources and outputs of the personal recovery comparison, sleep goal shortfall and sleep timing variability are scanned
- **THEN** none contains a term the M2 or M3 card forbids (sleep debt, normal range, abnormal or clinical quartile positions, the Sleep Regularity Index as a name), and the scan fails with the file, line and term otherwise.

Evidence: claim lists in `docs/performance-methods/m1-session-rpe-load.md` to `m8-local-session-metrics.md`. Runtime enforcement for M2 and M3 wording: `tests/test_performance_claim_wording.py`; the remaining methods are enforced by their work packages (#1427–#1431, #1725, #1726, #1680).

### Requirement: Method input fixtures
Every method of the input trace (cards M1 to M4) SHALL have synthetic input fixtures for one complete, one incomplete and one contradictory input set, each with a defined outcome: a value, no value with a status or reason, or an exclusion. The fixtures SHALL keep transport provider, recording origin and local method apart and SHALL count an activity imported from several providers once.

#### Scenario: Incomplete input
- **WHEN** a required input is missing for a method (for example no session RPE, too few earlier nights, or only a downsampled stream)
- **THEN** the fixture asserts that no value is produced or that the input is excluded, with the status or reason the current code gives; where current code still produces a value from that input, the fixture pins it as a known gap naming the owning issue.

#### Scenario: Contradictory providers
- **WHEN** two providers report different values for the same input
- **THEN** the fixture asserts that the values stay separate per provider and method and are not averaged.

#### Scenario: Canonical provider RPE
- **WHEN** an Intervals.icu activity reports `icu_rpe` beside a local session RPE
- **THEN** the canonical activity record keeps the provider RPE with its provenance and the M1 result uses the local rating.

#### Scenario: Garmin watch RPE without a local rating
- **WHEN** a session has a Garmin Connect RPE from the single-activity read and an Intervals.icu copy with another RPE, and no local rating
- **THEN** the summary and M1 use the Garmin RPE labelled "Garmin Connect" on its 1-10 scale, no RPE conflict is raised between the two providers, and a local rating would still win.

Evidence: `tests/test_performance_method_inputs.py`, `tests/test_garmin_activity_ratings.py:PrecedenceTests`.

### Requirement: Method input trace and gaps
A document SHALL trace each method's inputs from canonical storage to its HTTP, UI and Coach consumers and SHALL map each data gap to an owning issue. A reader that bypasses an available canonical input SHALL be pinned by a fixture assertion naming that issue.

#### Scenario: Gap closed by later work
- **WHEN** a later change makes a reader use a canonical input that it bypasses today
- **THEN** the pinned gap assertion fails with a message naming the owning issue, and the fixture and trace are updated in that change.

Evidence: `docs/performance-methods/inputs.md`, `tests/test_performance_method_inputs.py`.

### Requirement: Weekly HRV is a labelled fallback
The system SHALL show a Garmin weekly HRV average as the current HRV only when no last-night RMSSD is selected, with a source label that names the weekly average and without a 7-day average. It SHALL never pool weekly and last-night values in one series.

#### Scenario: Only a weekly HRV average exists
- **WHEN** Garmin provides a weekly HRV average and no provider has a selectable last-night RMSSD
- **THEN** the HRV value is the weekly average, its source label states that it is a weekly average, and the HRV average is absent.

#### Scenario: Last-night RMSSD exists
- **WHEN** a last-night RMSSD is selectable
- **THEN** it is shown and the weekly average is not used.

Evidence: `backend/performance/recovery_context.py:performance_recovery_context`, `backend/performance/context.py:current_performance_context`; `tests/test_performance_recovery_context.py:test_weekly_hrv_is_a_labelled_fallback_without_average`, `tests/test_performance_recovery_context.py:test_the_weekly_average_is_not_replaced_by_an_intervals_rmssd`, `tests/test_garmin_health_mapping.py` (`test_hrv_prefers_last_night_and_ignores_weekly_average`), `tests/test_performance_context.py:test_weekly_hrv_fallback_keeps_its_garmin_freshness`.

### Requirement: Morning sleep readiness reads canonical sleep days
The manual morning check-in SHALL decide whether today's Garmin sleep is available from the latest canonical Garmin sleep observation day, combined with the Garmin source freshness, and SHALL not read sleep days from the raw Garmin view.

#### Scenario: Sleep observation for today exists
- **WHEN** a Garmin sleep duration or score observation exists for the check-in day and the sleep source is current or partial
- **THEN** the check-in proceeds.

#### Scenario: Only raw data has today's sleep
- **WHEN** the raw Garmin view has today's sleep but no canonical sleep observation exists for today
- **THEN** the check-in waits for sleep data.

#### Scenario: Stored sleep freshness decides the day
- **WHEN** a Garmin sleep freshness with an `observed_at` is stored
- **THEN** its date is the sleep day, also when it cannot be read as a date (the check-in waits then), and only without one the latest canonical Garmin sleep observation day; with a freshness entry the check-in proceeds only when it is `current` or `partial`, without one when the sleep day is the check-in day.

#### Scenario: Freshness and observation disagree
- **WHEN** the stored freshness names yesterday and a canonical sleep observation exists for today
- **THEN** the check-in waits.

Evidence: `backend/coach/morning.py:ManualMorningCheckinService`, `backend/performance/garmin_observations.py:garmin_sleep_ready_for_checkin`; `tests/test_coach_manual_morning.py:test_missing_or_stale_sleep_raises_without_refreshing_battery`, `tests/test_garmin_observations.py:test_sleep_day_comes_from_the_observation_never_from_raw_sleep`. Added evidence: `tests/test_garmin_observations.py:test_freshness_date_has_priority_over_raw_sleep`, `tests/test_garmin_observations.py:test_malformed_freshness_value_is_authoritative_without_raw_fallback`.

### Requirement: Canonical sleep timing variability parity
Sleep timing variability SHALL read canonical periods without traversing raw provider payloads. Equivalent synthetic periods SHALL preserve the sleep-timing-variability-v1 results, source separation and coverage; v2 differs only by withholding medians and deviations below 14 earlier intervals. Nightly bounds SHALL not be labelled as a complete sleep/wake series or the Sleep Regularity Index.

#### Scenario: Equivalent stored nights
- **WHEN** equivalent synthetic nights are supplied through canonical periods rather than the previous provider aliases
- **THEN** timing variability values and coverage match the earlier provider-row method.

#### Scenario: Sparse coverage
- **WHEN** missing nights or overlapping provider periods exist
- **THEN** those distinctions remain explicit and the result does not claim the Sleep Regularity Index or fabricate full-day coverage.

#### Scenario: Night read outside the profile time zone
- **WHEN** a canonical period has no timezone, so its provider day differs from the local end date (`sleep-timing-variability-v3`)
- **THEN** the night is marked `other_timezone`, shows no deviation and is left out of the median, the deviation medians, the earlier-interval count and the status.

### Requirement: Canonical retained provider performance reads
Affected history, recovery, nutrition and Coach reads SHALL obtain retained provider status, load balance, tolerance, score details, performance history, Body Battery and resting energy from canonical data. Provider labels, dates and missing-value semantics SHALL survive without a snapshot dependency in these paths. Garmin stress and the subjective ratings are stored but no read path uses them.

#### Scenario: Canonical data without snapshot
- **WHEN** retained canonical provider data is available and provider views/snapshots are absent
- **THEN** affected read surfaces remain available with their supported values, dates and source labels.

#### Scenario: Proprietary score absent
- **WHEN** a proprietary provider score is not recorded
- **THEN** it remains unknown and no local recreation is substituted.

#### Scenario: Garmin training status is shown only for today
- **WHEN** the Garmin training-load projection is composed
- **THEN** `daily_status` (acute load, chronic load, acute-to-chronic ratio) and `four_week_balance` (aerobic low, aerobic high and anaerobic with their target minimum and maximum) are each dated by the latest day of their kinds and show their values only while that section's sync freshness is `current` or `partial` and that day is today.

#### Scenario: Older or stale values
- **WHEN** the latest day is before today or the section is stale
- **THEN** the section keeps its `date`, source "Garmin Connect" and freshness, `daily_status` shows its three fields as null and `four_week_balance` shows no value field; a section without any observation of its kinds is absent.

Evidence baseline: `backend/performance/personal_recovery.py`, `backend/performance/chart_history.py`, `backend/performance/garmin_projection.py`; `tests/test_personal_recovery.py`, `tests/test_performance_chart_history.py`. Canonical-only reads and parity require new regression evidence. Added evidence: `tests/test_garmin_training_load_canonical_parity.py:test_fresh_values_of_today`, `tests/test_garmin_training_load_canonical_parity.py:test_stale_or_older_values_are_dated_but_hidden`, `tests/test_garmin_training_load_canonical_parity.py:test_without_values_there_is_no_section`.

### Requirement: Garmin current performance metrics are read from canonical data only
The current Garmin performance metrics (weight, thresholds, VO2max, maximum heart rate and race predictions) SHALL be read from canonical Garmin data only. The Garmin sync status SHALL supply only source freshness on these read paths. Only the sync's performance-history merge SHALL parse a fetched Garmin payload, before it is stored.

#### Scenario: Activity maximum heart rate
- **WHEN** a sport has neither its own nor a generic canonical Garmin profile maximum heart rate
- **THEN** its maximum heart rate is the highest 80–260 bpm maximum heart rate of that sport's active canonical Garmin activity records outside deleted sessions, read from the same source as the observations and dated on the athlete-local start day of the newest activity with that value; its note names the activities, while a sport with a profile value keeps the heart rate zone note.

#### Scenario: Equivalent stored payload and canonical data
- **WHEN** a Garmin payload is stored and projected into canonical observations and activity records
- **THEN** the Garmin performance metrics read from the canonical data equal the metrics the payload parser gives for that payload, except the activity maximum heart rate: only the canonical read derives it, and the payload parser keeps no activity maximum.

#### Scenario: Activity maximum across providers
- **WHEN** a sport's current maximum heart rate has no resolved threshold
- **THEN** the highest stored Garmin or Wahoo activity maximum over the whole history is used, dated on its newest start day, with Garmin winning a tie; only without either, the highest Garmin or Wahoo session summary value is used, and Intervals.icu summaries never are. The overall maximum heart rate ranks every activity maximum after the thresholds.

#### Scenario: No canonical Garmin data
- **WHEN** the stored Garmin view has performance sections but no canonical Garmin observation or activity record exists
- **THEN** the Garmin performance metrics are absent and no value is read from the view.

#### Scenario: Profile maximum heart rate present
- **WHEN** a canonical Garmin profile maximum heart rate exists for both sports or as a generic value
- **THEN** it is shown and the activity records are not read.

#### Scenario: Daily VO2max readings
- **WHEN** Garmin's daily maxmet range dates each sport object (`generic` for running, `cycling`) and leaves the row undated
- **THEN** every reading is stored on its own day, the current day's included with its precise value, running and cycling stay separate values each dated by its own reading in the canonical and the payload-parsed metrics, and an already stored range re-projects with Garmin health mapper 23.

Detailed contract: activity records exist only from the first canonical ingest or backfill onward, so a maximum the stored view retained from activities older than that is not kept (accepted by #1415's decision to derive the value from canonical records). The current maximum heart rate fallback has no day history; no comparison or chart reads one.

Evidence:
- `backend/db/canonical_store.py:activity_max_hr_rows`
- `backend/performance/garmin_canonical.py:read_garmin_state`
- `backend/performance/garmin_metrics.py:garmin_performance_metrics`
- `backend/providers/garmin.py:_dated_max_metrics`
- `backend/providers/garmin_health_mapping.py:_map_max_metrics`
- `backend/sync/garmin_payload_metrics.py:garmin_payload_performance_metrics`
- `tests/test_garmin_canonical_reads.py:GarminCanonicalReaderUnitTests.test_activity_max_hr_is_read_from_the_same_source`
- `tests/test_garmin_canonical_reads.py:GarminCanonicalReaderUnitTests.test_only_the_sport_without_a_profile_value_is_labelled_activities`
- `tests/test_garmin_canonical_reads.py:GarminCanonicalReaderUnitTests.test_profile_max_hr_skips_the_activity_read`
- `tests/test_garmin_canonical_reads.py:GarminStateEqualityTests.test_activity_max_hr_skips_deleted_sessions`
- `tests/test_garmin_canonical_reads.py:GarminStateEqualityTests.test_state_has_the_flags_and_values_of_the_snapshot_sections`
- `tests/test_garmin_canonical_reads.py:GarminStateEqualityTests.test_table_observations_give_the_payload_state`
- `tests/test_garmin_health_mapping.py:test_maxmet_daily_rows_date_each_sport_object`
- `tests/test_performance_canonical_current_metrics.py:CanonicalCurrentFromTablesTests.test_populated_tables_serve_the_current_metrics`
- `tests/test_performance_garmin_metrics.py:test_canonical_vo2max_is_dated_by_each_sport_reading`
- `tests/test_performance_garmin_metrics.py:test_maxmet_daily_rows_date_each_vo2max_by_its_own_reading`
- `tests/test_provider_garmin_metric_history.py:test_maxmet_daily_rows_take_their_sport_objects_day`

### Requirement: No ramp rate is derived
The system SHALL NOT derive or show a ramp rate: card M7 forbids ramp, ratio and ACWR outputs from the load curves, and Intervals.icu's own `rampRate` is not read.

#### Scenario: CTL days a week apart
- **WHEN** Intervals.icu CTL observations exist for the latest wellness day and seven days earlier, or a snapshot row carries `rampRate`
- **THEN** `current_load` has no `ramp_rate` or `ramp_rate_source` key.

Evidence: `backend/performance/load_context.py:performance_load_context`; `tests/test_performance_canonical_load_metrics.py:FormTests.test_intervals_form_never_feeds_the_current_load_or_comparison`, `tests/test_performance_canonical_parity.py`.

### Requirement: Intervals.icu load and form are not read
The system SHALL NOT read Intervals.icu CTL, ATL, form or eFTP observations in any performance view; whatever rows exist stay unshown. Output keys follow the provider-neutral output key requirement.

#### Scenario: Stored load and form
- **WHEN** canonical Intervals.icu CTL, ATL and form observations exist
- **THEN** the performance inputs hold no load day, `current_load.tsb` and `comparisons.form_tsb` come from the local curve (M7) only, and no kind of them is read.

#### Scenario: Carrier fields are ignored
- **WHEN** snapshot wellness rows still carry `tsb`, `rampRate` and `sportInfo`
- **THEN** none of them influences these values.

Evidence: `tests/test_performance_canonical_parity.py`. The strict-read scenarios are verified by `tests/test_performance_canonical_load_metrics.py` (carrier rows are stripped or contradicting), `tests/test_performance_canonical_parity.py:CanonicalInputEdgeTests` and `tests/test_server_performance.py`.

### Requirement: Report-family reads use canonical activity rows only
The system SHALL read the activities of period reports, the training-record observation list, tag impact, training focus, load rollups and season preparation from the canonical activity summary port only, and SHALL NOT fall back to the stored snapshot's `raw_provider_data.activities` or `recent_activities`.

#### Scenario: Canonical rows with an empty snapshot
- **WHEN** any of these reads runs with canonical activity summaries and a snapshot without activity sections
- **THEN** it computes from the summaries exactly as it would with the rows in the snapshot.

#### Scenario: No activity rows
- **WHEN** the canonical summary port returns no summaries
- **THEN** the read returns its existing empty-data result (no sessions, insufficient data) instead of an error or snapshot data.

#### Scenario: Copies stored by two providers
- **WHEN** the canonical tables hold copies of one activity from two providers
- **THEN** session linking has joined them into one session, so these reads count the activity once.

Detailed contract: The services that run these reads require their canonical source at construction. Duplicates are merged by canonical session linking, not by row de-duplication; only the raw-row equipment read keeps the Wahoo/Garmin row de-duplication.

Evidence: `backend/performance/training_report.py`, `backend/performance/report_service.py:TrainingRecordsService.observations`, `backend/performance/tag_impact.py`, `backend/performance/training_focus.py:training_focus`, `backend/performance/canonical_inputs.py:activity_summaries_for`, `backend/sync/canonical_backfill.py:_link_work_sessions`; `tests/test_training_report.py`, `tests/test_training_focus.py`, `tests/test_season_canonical_reads.py`, `tests/test_canonical_table_reader.py:ActivitySessionReadTests`.

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

Evidence:
- observed defect from athlete diagnostics 2026-10-24 (`garmin.source_freshness.endurance_score.observed_at` = 2026-10-23 while the chart's latest point stayed at 2026-10-18)
- `backend/providers/garmin.py:_collect_historic_metrics`
- `backend/providers/garmin.py:targeted_analysis_sources`
- `backend/sync/garmin_metric_history.py:_records`
- `backend/performance/chart_history.py:_canonical_provider_metrics`
- `backend/sync/garmin_performance_history.py:_provider_metrics`
- `public/analysis.js:analysisWeeklyPerformancePoints`
- `tests/test_provider_garmin_metric_history.py:test_known_sdk_methods_get_bounded_dates_and_explicit_aggregation`
- `tests/test_performance_chart_history.py:test_saved_endurance_group_map_repairs_previously_empty_projection`
- `tests/test_performance_chart_history.py:test_daily_weekly_view_metrics_reach_the_newest_measurement`
- `tests/test_garmin_analysis_refresh.py:test_targeted_weekly_view_metrics_request_daily_readings`; running tolerance shares the weekly grouping in `public/analysis.js`. Gap: the exact daily `groupMap` key shape is inferred from the SDK docstring and existing weekly handling, not from a captured live payload.

### Requirement: Profile body fat is shown in the Body overview
The Body overview SHALL show a valid saved body-fat profile value labelled as profile data, without projecting it into dated measurement history.

#### Scenario: Profile value exists
- **WHEN** the saved profile contains valid body fat
- **THEN** the overview shows that value and labels it as profile data.

#### Scenario: No profile value exists
- **WHEN** the profile has no valid body-fat value
- **THEN** the overview shows the latest eligible Garmin body-fat reading when available.

Evidence: `public/analysis.js`; `tests/analysis-presentation.test.cjs::body overview uses profile body fat without creating a dated measurement`, `tests/analysis-presentation.test.cjs::body overview falls back to Garmin when the profile fat is absent`.

### Requirement: Performance inputs come from canonical observations only
The system SHALL read the performance inputs only from canonical observations and activity summaries; the body history carries Garmin weight and body fat. Performance readers SHALL NOT read snapshot wellness rows or stored Intervals.icu wellness days. Without canonical inputs these values SHALL be absent.

#### Scenario: No canonical inputs
- **WHEN** the performance context is composed without canonical inputs, or without any provider value in the canonical inputs (activities, daily totals, Wahoo settings, Garmin or recovery observations, Garmin body values), also when a stored snapshot exists or only the athlete's manual profile holds values
- **THEN** the context is unavailable: weight and body fat and the body history are unknown instead of read from the snapshot.

#### Scenario: Availability follows canonical data, not the snapshot
- **WHEN** canonical observations or activities exist without a stored snapshot, for example a Garmin-only setup after the backfill completed
- **THEN** the context is available with its full metrics. `as_of` is the activity sync time of the active providers, or null without one, and the source names the stored provider data. The stored snapshot is never read for either.

#### Scenario: Narrow Garmin sync status
- **WHEN** the current context, the analysis history, the training focus, the body history, `/api/performance` or the Coach performance and recovery sections need Garmin freshness, fetch or sync times, read windows or a cached chart's fetch outcome
- **THEN** they read one typed Garmin sync status built from the stored Garmin state and the names of the stored sections (no measured value), and never the Garmin view. While the canonical source is pending, the Garmin card gets the empty status, so it shows no freshness, source or pagination, only its connection status.

#### Scenario: Pending state shows no partial values
- **WHEN** the first canonical backfill has not completed and `/api/performance` is read
- **THEN** history and training focus are built from empty inputs, without the stored snapshot or the raw Garmin view; the Garmin connection status stays, and the server's `status` text is the only status the PWA shows.

#### Scenario: Canonical data is still being prepared
- **WHEN** the first canonical backfill has not completed
- **THEN** the context is unavailable with reason `canonical_pending`, shows no values and reports "Daten werden vorbereitet" while pending or running; after a failed batch it reports the failure and upcoming retry. The Coach context also marks canonical data unavailable, including when only activity or planning sections are selected.

Detailed contract: CTL, ATL, form and the subjective ratings are not read. The snapshot rows not read are `recent_wellness` and `raw_provider_data.wellness`. The body history shows one series per metric, from Garmin.

Evidence: `backend/performance/canonical_inputs.py:read_performance_inputs`, `backend/performance/body.py:body_history`; `tests/test_performance_no_eftp_series.py:NoEftpSeriesTests`, `tests/test_performance_body.py:BodyHistoryTests`, `tests/test_performance_canonical_parity.py:CanonicalInputEdgeTests`, `tests/test_performance_context.py:PerformanceContextTests`, `tests/test_performance_canonical_parity.py:CanonicalReadStatusEndToEndTests`, and `tests/test_performance_canonical_body_history.py:CanonicalBodyLedgerCaseTests`.

### Requirement: Performance state route
`GET /api/performance` SHALL require a valid session and answer `performance` and `garmin` from one read-only database snapshot without a provider request; its contract is in `docs/api-routes.md`.

#### Scenario: Body
- **WHEN** the canonical backfill has completed
- **THEN** `performance` is the current performance context plus `history` (the 90-day analysis history and, for the 84 days ending today, `session_rpe_load` without its session list, `smoothed_session_load` and `local_fitness_fatigue`) and `training_focus_periods` (`fortnight` of 14 and `twelveWeeks` of 84 days), and `garmin` is the public Garmin projection.

#### Scenario: Inputs
- **WHEN** the performance inputs are read
- **THEN** they hold the activity summaries of the last 365 days and the daily totals of 7 days; older sessions stay reachable through the activity detail read.

Detailed contract: while the first canonical backfill is pending, the pending scenarios of "Performance inputs come from canonical observations only" apply and the three load results are null.

Evidence:
- `backend/http_api/public_performance.py:PublicPerformanceStateService`
- `backend/performance/canonical_inputs.py:read_performance_inputs`
- `tests/test_http_public_performance.py`
- `tests/test_server_performance.py`

### Requirement: Wellness `sportInfo` threshold fallbacks are not read
The system SHALL NOT read cycling or running FTP, LTHR, maximum heart rate, VO2max, threshold pace or Zone-2 pace from Intervals.icu wellness `sportInfo` entries. These values SHALL come only from their remaining sources: Garmin, athlete sport settings, the athlete record, Wahoo and the manual profile. The 30-day `run_threshold_watts` average SHALL read only Garmin's run threshold power history and SHALL be unknown when the current value has another source.

#### Scenario: `sportInfo` carries threshold keys
- **WHEN** a stored wellness row's `sportInfo` entry carries `ftp`, `lthr`, a maximum heart rate, `vo2max`, `threshold_pace` or a Zone-2 pace
- **THEN** none of them supplies a current metric or a 30-day average.

#### Scenario: Run eFTP is not a threshold power average
- **WHEN** run eFTP wellness-day observations exist in the 30 days ending on the current day and the current `run_threshold_watts` has a source other than Garmin
- **THEN** `comparisons.run_threshold_watts_30d` has no average; the run eFTP observations are not read.

Detailed contract: the Intervals.icu wellness `sportInfo` entry provides the sport type, CTL, ATL, eFTP, W′ and Pmax (`tests/fixtures/providers/intervals/wellness.json`); the removed keys are not part of it. No live payload was inspected (evidence gap).

Evidence: `backend/performance/current_metrics.py:current_performance_metrics`, `backend/performance/trends.py:garmin_history_average`; `tests/test_characterization_current_metrics.py:CurrentThresholdTests.test_intervals_ftp_in_every_form_gives_no_cycling_ftp`, `tests/test_characterization_current_metrics.py:CurrentMaxHrTests.test_out_of_range_setting_does_not_read_wellness_sport_info`, `tests/test_performance_no_eftp_series.py:NoEftpSeriesTests.test_eftp_observations_feed_no_series`.

### Requirement: Performance context output keys are provider-neutral
The current performance context returned to the Coach and through HTTP SHALL name its recovery, comparison, load and threshold values with provider-neutral keys and SHALL NOT emit the former provider-shaped keys. Values, units and source labels SHALL stay unchanged.

#### Scenario: Same data before and after
- **WHEN** the same synthetic canonical data is projected before and after this change
- **THEN** every renamed key holds the value and source label of its former key, and every other key of the context is unchanged.

#### Scenario: Coach context
- **WHEN** the Coach context includes the current performance section
- **THEN** it carries the neutral keys and none of the former keys.

Detailed contract: the neutral keys are
- `recovery.resting_hr_bpm`, `recovery.hrv_ms` and `recovery.sleep_score`, each with a matching `*_source` key and matching `recovery.source_freshness` keys;
- `comparisons.resting_hr_bpm` and `comparisons.hrv_ms`;
- `thresholds.ftp_w` (no `w_prime_j`, no `intervals_load_history`, no ramp rate).

They replace `restingHR`, `hrv`, `sleepScore`, `rampRate`, `rampRate_source` and `icu_ftp`.

Evidence: `backend/performance/context.py:current_performance_context`, `backend/performance/comparisons.py:performance_comparisons`, `backend/performance/load_context.py:performance_load_context`; `tests/test_performance_context.py:PerformanceContextTests.test_composed_context_has_only_neutral_performance_keys`, `tests/test_characterization_coach_context.py`, `tests/test_server_performance.py`.

### Requirement: Current performance context sections and comparisons
The current performance context SHALL carry fixed sections and SHALL express every comparison as one entry of the current value, its reference average, the difference and a direction; the Coach and `GET /api/performance` receive the same context.

#### Scenario: Sections
- **WHEN** the context is available
- **THEN** it has `available`, `source` ("Gespeicherte Provider-Daten"), `as_of` (the activity sync time), `metrics`, `thresholds`, `current_load`, `recovery`, `rolling_training`, `comparisons`, `activity_validation`, `personal_recovery`, `garmin_training_load` and `training_focus`; `thresholds` holds `ftp_w`, `ftp_source`, `max_hr`, `lthr`, `run_lthr`, `weight`, `run_hr_caps`, `first_thresholds` and, when another source has a current FTP, `ftp_alternatives` and `ftp_conflict`.

#### Scenario: Comparison entry
- **WHEN** a current value and its average are both known
- **THEN** the entry is `{current, average, delta, unit, days, direction, color, label}` with `delta` to two decimals, `direction` `up`, `down` or `flat`, `color` `good`, `bad` or `neutral` and the label "<days>-Tage-Durchschnitt" unless stated otherwise; with either value unknown the entry is null.

#### Scenario: References
- **WHEN** the comparisons are composed
- **THEN** sleep, readiness, resting heart rate (lower is better), HRV, fitness and form compare with their 7-day average and fatigue carries no verdict; `training_load_7d` compares the last with the previous 7 days ("vorherigen 7 Tagen") and, when either week holds a session without a local load, keeps its sums and `load_missing_sessions` per week but has no delta, direction or colour; `training_volume_7d` compares the hours of the last 7 days with the hours of the 30 days before them times 7/30 ("Schnitt der 30 Tage davor"); the `*_30d` entries compare with the 30-day average of Garmin's day history and exist only for a value whose current source is Garmin.

Evidence:
- `backend/performance/comparisons.py:performance_comparisons`
- `backend/performance/context.py:current_performance_context`
- `backend/performance/current_metrics.py:coach_thresholds`
- `backend/performance/trends.py:garmin_history_average`
- `backend/performance/wellness.py:comparison_value`
- `tests/test_performance_comparisons.py`
- `tests/test_performance_context.py:test_rolling_training_and_input_nonmutation`
- `tests/test_performance_wellness.py:test_all_direction_and_color_paths`

### Requirement: Personal recovery measurement labels name the method
Personal recovery baselines, sleep goal shortfalls and tag-impact reports SHALL label their measurement with a provider-neutral method name: `duration` for sleep duration, `resting` for resting heart rate, and `RMSSD` for HRV. They SHALL NOT use a provider field name such as `lastNightAvg`, `sleepSecs`, `sleepTimeSeconds`, `restingHR` or `restingHeartRate`. Series SHALL remain separated by provider and method; only Garmin series exist.

#### Scenario: Garmin HRV
- **WHEN** Garmin nightly HRV and stored Intervals.icu RMSSD observations both exist
- **THEN** the baseline is the one Garmin series labelled `RMSSD`, the Intervals.icu rows give no baseline, and the HRV chart heading shows `RMSSD` after the source.

Evidence: `backend/performance/personal_recovery.py:_SERIES`, `backend/performance/personal_recovery.py:personal_recovery`, `backend/performance/tag_impact.py:tag_impact`; `tests/test_rolling_hrv.py`, `tests/test_personal_recovery.py:PersonalRecoveryTests`, `tests/test_characterization_recovery.py`, `tests/test_training_record_features.py`, `e2e/analysis-info.spec.js`.

### Requirement: Session-RPE load is a descriptive local method
The system SHALL compute the M1 session-RPE load (`session-rpe-load` v2) as elapsed minutes × whole-session RPE in AU for each canonical session and sum it per athlete-local day, ISO week and sport. AU SHALL never be added to or converted into TSS, provider load or TRIMP.

#### Scenario: Acceptance values
- **WHEN** a session of 60 minutes has local RPE 5, one of 30 minutes has RPE 0 and one has no RPE
- **THEN** they give 300 AU, 0 AU and no value with reason `no_rating`.

#### Scenario: Partial sum
- **WHEN** two rated sessions of 300 and 120 AU and one unrated session fall in a period
- **THEN** the period reports 420 AU known load with 2 of 3 sessions rated and the counts of its RPE sources.

#### Scenario: Long interruption
- **WHEN** a session's elapsed time exceeds its moving time by more than 15 minutes or 20 % of the elapsed time
- **THEN** its value stays elapsed minutes × RPE and is marked `deviating_duration` with its moving minutes, except for strength and yoga sessions, which are never marked.

#### Scenario: Provider fallback
- **WHEN** a session has no local RPE and its provider record reports RPE 6 over 50 minutes
- **THEN** it gives 300 AU labelled with that provider (an Intervals.icu rating stored earlier or Garmin Connect); a local RPE 5 of the same session would win instead.

#### Scenario: No valid input
- **WHEN** the session's provider records disagree on RPE without a local one, it has only a moving time, or its duration is not positive
- **THEN** it gives no value with reason `conflicting_provider_ratings`, `no_elapsed_duration` or `invalid_duration` and stays an open session in the sums.

#### Scenario: Ambiguous feedback assignment
- **WHEN** a local rating is stored under an id that matches activities of several sessions, so it has no session
- **THEN** it is not used as any session's rating; the session uses its provider fallback or stays open.

#### Scenario: Duplicate imports and edits
- **WHEN** one session is imported from two providers, or its RPE is edited, cleared or the edit undone
- **THEN** it counts once, and the next read reflects the effective feedback or the provider fallback.

#### Scenario: Fields of a listed session
- **WHEN** a session of the period is listed
- **THEN** sessions are ordered newest first by local day and then id, at most 100, and an entry carries `activity_id`, `date`, `name` (at most 200 characters), `sport`, `value`, `rpe`, `rpe_source` (`athlete_feedback` or `provider`), `rpe_source_label`, `rpe_scale`, `duration_min`, `rated_minutes_after_end` (whole minutes, only for a local rating with a recorded rating time), `duration_flag`, `moving_duration_min`, `status` and `reason`.

#### Scenario: Weeks and sports
- **WHEN** a Monday-to-Sunday week starts before the period or ends after it
- **THEN** it carries `partial_period: true`; sessions without a sport are summed under `unknown`, and the public performance history serves the result with an empty `sessions` list.

Detailed contract: each result names `metric_id`, `method_id`, `method_version`, unit, status (`descriptive` or `insufficient_data`), period with timezone, computation time, method note, limits and the evidence card `docs/performance-methods/m1-session-rpe-load.md`. Per session it lists RPE, source and label, duration in minutes and, for a local rating with a recorded rating time, `rated_minutes_after_end`. Values are rounded to one decimal only for output. The Coach training report carries it for the report period, the public performance history for the load tab's 84 days, where the PWA draws a separate AU chart with its coverage. The Coach SHALL name the inputs and source and SHALL NOT derive injury risk, readiness or ramp statements from AU.

Evidence: `backend/performance/session_rpe_load.py`, `backend/performance/training_report.py:training_report`, `backend/performance/report_service.py:TrainingReportReadService`, `backend/http_api/public_performance.py:PublicPerformanceStateService`, `backend/coach/prompt.py`, `public/analysis.js:appendSessionRpeLoadChart`; `tests/test_session_rpe_load.py`, `e2e/activity-details.spec.js`.

### Requirement: Smoothed session-RPE load is a labelled model estimate
The system SHALL compute the M5 short- and long-term load (`smoothed-session-load` v1) as the exponentially smoothed M1 daily AU with τ 7 and 42 days, starting at 0 AU, never seeded from provider CTL, ATL or load, and without ratio, difference, risk, ramp or readiness output.

#### Scenario: Reference values
- **WHEN** sessions of 300 AU fall on every second day for 100 days
- **THEN** the last day shows the recursion values of both curves, rounded to 0.1 AU.

#### Scenario: Warm-up and gaps
- **WHEN** the first session is 10 days old, or a day has an unrated session
- **THEN** the short-term curve has no value until day 14 and the long-term curve until day 84, and the gap day shows no value while later days continue from the held state.

#### Scenario: Missing sessions are not zero
- **WHEN** a past day has no session, the day of the last sync or later has none, or a day has an unrated session
- **THEN** the past day counts 0 AU, the other days are open or gaps with no value and an unchanged state.

#### Scenario: Provider load does not seed
- **WHEN** activity records carry provider load or CTL values
- **THEN** the curves are identical to those without them.

#### Scenario: Coach report and load tab agree
- **WHEN** the same date is read through an 84-day period and through a 7-day period
- **THEN** both recursions start on the first recorded session of the same history window, rated or not, and show the same value.

#### Scenario: Sync time
- **WHEN** the last activity sync time is missing, has no UTC offset or cannot be parsed
- **THEN** the first open day is today; otherwise it is the earlier of today and the date of the sync instant in the profile time zone; the local fitness curve (M7) uses the same first open day.

Detailed contract: values appear 2τ days after the first session of the history window, which starts 168 days before the period and never later than 251 days before today. Each result names `metric_id` `smoothed_session_load`, `method_id`, `method_version`, unit AU, status `estimate` or `insufficient_data` with reason `warmup` or `no_sessions`, period, parameters, per-state day coverage, the latest valued day, per-day `state`, `load`, `short` and `long`, method note, limits and the card `docs/performance-methods/m5-smoothed-session-load.md`. The Coach training report carries it for all-sport reports, the public performance history for the load tab's 84 days, where the PWA draws one AU chart of both curves. The Coach SHALL name the AU basis and coverage.

Evidence: `backend/performance/smoothed_load.py:ewma_walk`, `backend/performance/training_report.py:training_report`, `backend/http_api/public_performance.py:PublicPerformanceStateService`; `tests/test_smoothed_load.py`, `tests/test_performance_coach_ui_parity.py`

### Requirement: Released local methods are registered and shown the same in Coach and UI
Each Epic S local method SHALL be listed in the register below with its method id and version, statuses, limits and card. The Coach SHALL receive the value, status, method and period the UI shows for the same inputs; it MAY omit display-only arrays such as per-day history or chart points, but SHALL NOT recompute, round differently or relabel a value.

#### Scenario: Same inputs on both paths
- **WHEN** one set of canonical sessions, feedback, recovery observations and sleep periods is read by the public performance state, the analysis route, the Coach context and `get_training_report`
- **THEN** a full ISO week's session-RPE load, each recovery baseline, the sleep timing summary and the best-effort curve carry the same value, status, method and period on both paths.

#### Scenario: Large sleep timing history
- **WHEN** the sleep timing variability spans many nights
- **THEN** `get_training_report` returns the Coach context's summary plus each series' last 14 nights as the UI shows them, without the 84-night chart points, and reports the section as complete.

Detailed contract:

| Metric | Method id, version | Statuses | Limits | Card, review |
| --- | --- | --- | --- | --- |
| Session-RPE load (AU) | `session-rpe-load` v2 | `descriptive`, `insufficient_data` | AU is not TSS, provider load or TRIMP; no injury, readiness or ramp statement | M1, released |
| HRV, resting HR and sleep duration comparison | `personal-quartiles-v1` | `ok`, `provisional`, `insufficient_data` | own earlier values only, not a normal or clinical range | M2, M3, released |
| Seven-day ln(RMSSD) mean against the 42 days before (Garmin RMSSD, inside each HRV baseline as `rolling`) | `rolling-lnrmssd-v1` | `ok`, `provisional`, `insufficient_data` | mean ± 0.5 SD of the athlete's own earlier nights, not a normal range or Garmin's HRV status; CV without rating | M2, released |
| Sleep goal shortfall (last 7 nights) | inside the `personal-quartiles-v1` result, no own id | `ok`, `partial`; none without a 4–12 h goal | no sleep debt | M3, released |
| Sleep timing variability | `sleep-timing-variability-v3` | `ok`, `provisional`, `insufficient_data` | not the Sleep Regularity Index; no median or deviation below 14 earlier intervals | M3, released |
| Power and running best-effort curve | `mean-max-curve` v2 | `ok`, `insufficient_data`; per running point also `unknown` | observed bests only, no FTP, CP or pace estimate; an outdoor running window counts only with a net altitude change of at most 1 % of its distance | M4, released |
| Critical Power and Critical Speed | `critical-power-speed` v2 | method `experimental`; per fit `ok`, `insufficient_data`, `withheld` | model estimate from the best 3/7/12/20-min efforts (cycling) or 3/7/12-min efforts (running) of 28 days; never FTP, threshold or zones | M4, released |
| Short- and long-term session-RPE load (AU) | `smoothed-session-load` v1 | `estimate`, `insufficient_data` | smoothed subjective load; no fitness, form, ratio, risk or provider comparison | M5, released |
| Session load and intensity factor (TSS scale) | `local-tss-load` v7 | stored per session with `load_branch` `power`, `pace`, `heart_rate` or `session_rpe` (strength); none without inputs | branches are not equivalent; strength TSS is a personal sRPE scaling; no fatigue, readiness or injury statement; IF = 1 is not a physiological threshold | M6, released |
| Local fitness, fatigue and form (TSS/d) | `local-fitness-fatigue` v1 | `estimate`, `insufficient_data` | model estimate from the local load; never mixed with Intervals.icu CTL/ATL/form; no performance, risk or readiness prediction | M7, released |
| Efficiency factor, variability index, work and aerobic decoupling | `local-session-metrics` v4 | stored per ride or run; none without inputs or full-resolution streams (work, decoupling) | descriptive; no fixed decoupling limit, no fitness, durability or threshold verdict; run and ride values never compared; work is not energy expenditure | M8, released |
| LT1 pace and power from own steady sessions | `pace-at-heart-rate-v2`, `power-at-heart-rate-v1` | LT1 origin `own_sessions`; none with fewer than 3 steady sessions in the band | read at the LT1 heart rate in effect, never an LT1 heart rate; estimate, not a laboratory LT1; no zone change | M9, released |
| First threshold heart rate from chest-strap RR intervals (DFA-α1) | `dfa-alpha1-first-threshold` v2 | per recording quality `good` or `low`, none without a crossing; for the athlete the same, none below 3 good run sessions of 60 days | research-grade estimate for the athlete to review, not a laboratory VT1 or lactate threshold; no anaerobic threshold, fitness or readiness statement; only the athlete adopts it | M10, review blocked |

The first threshold from chest-strap RR intervals (M10) is implemented as a labelled estimate; passive CP/CS, other TRIMP uses, further threshold or VO2max estimates, W′ balance and HRV-based recommendations stay deferred. No observation phase has run.

Evidence: `docs/performance-methods/README.md`, `backend/coach/context.py:coach_performance_projection`, `backend/coach/context.py:coach_sleep_timing_projection`, `backend/coach/activity_read_tools.py:CoachActivityReadToolService.execute`; `tests/test_performance_coach_ui_parity.py`.

### Requirement: Local TSS-scale session load is a labelled model estimate
The system SHALL compute each canonical session's load with M6 `local-tss-load` v7 from its summary and the thresholds valid on its local day: power (NP/FTP, ride and run), then run pace, then heart rate (Banister TRIMP, 60 min at threshold HR = 100). A strength session SHALL take its session-RPE AU times a personal TSS-per-AU factor. It SHALL store the load, and the power IF, as derived observations owned by the session and SHALL NOT use a provider load or intensity.

#### Scenario: Garmin-only session with power
- **WHEN** a Garmin-only ride reports NP 230 W for 70 minutes and the FTP valid that day is 250 W
- **THEN** its summary serves `training_load` 98.75, `intensity` 92 and `load_branch` `power` with the source label `derived`, and the rollup sums it.

#### Scenario: Heart-rate branch
- **WHEN** a session without power or pace has an average heart rate and consistent resting, threshold and maximum heart rates
- **THEN** its TRIMP uses the constants of the profile sex (male, marked `sex_assumed`, when none is saved); it is summed over the stored heart-rate distribution (`hr_basis` `distribution`) when that covers at least 80 % of the TSS duration, otherwise taken from the average heart rate (`hr_basis` `average`).

#### Scenario: Strength from the session RPE
- **WHEN** a 45-minute strength session is rated RPE 6 on the Garmin device and 20 Garmin-rated rides of the last 365 days with an RPE within 1 of it each give 100 TSS for 300 AU
- **THEN** it gets 90 TSS with `load_branch` `session_rpe`, its factor and pair count; the factor is the median TSS per AU of the pairs within 1 RPE, widened to 2 when fewer than 20 qualify; with fewer than 20 pairs in both bands or only Intervals.icu-relayed ratings it gets none (`not_calibrated`), and unrated it gets none (`no_rating`).

#### Scenario: Threshold valid only after the session
- **WHEN** no threshold is valid on the session day but a later one, observed at most 90 days after it, exists
- **THEN** the earliest later threshold is used and the value is flagged `threshold_after_session`; a threshold observed later than 90 days after the session day does not stand in.

#### Scenario: Changed input or method
- **WHEN** a session's inputs, its dated thresholds or the method version change, or the session is gone
- **THEN** the next stage pass rewrites only the values whose fingerprint changed and retires the values of gone sessions.

#### Scenario: Reason of a session without a load
- **WHEN** no branch gives a value
- **THEN** the session carries the reason of the first failing branch and is never served as zero: `sport_without_load`, `no_duration`, `no_inputs`, `no_ftp`, `no_threshold_pace`, `implausible_intensity`, `no_resting_hr`, `no_threshold_hr`, `no_max_hr`, `inconsistent_heart_rate_thresholds`, `heart_rate_outside_reserve`, `no_rating`, `not_calibrated`, `no_date`, or `invalid_value` for a load outside the canonical bounds, which never stops the pass; a strength session whose only rating is relayed by Intervals.icu has `no_rating`.

#### Scenario: Served fields
- **WHEN** a summary carries a stored load
- **THEN** it serves `training_load` (stored to 4 decimals), `load_method`, `load_method_version`, `load_branch`, `load_threshold_after_session` when flagged, `load_assumption` ("Geschlecht nicht gesetzt, männliche Konstanten angenommen") when the sex is assumed and, for strength, `load_calibration` with `tss_per_au`, `pairs`, `session_rpe_au`, `rpe_band`, `pairs_by_rating_source` and `tss_per_au_by_rpe` (RPE 1 to 10, a factor only from 20 pairs, three decimals).

#### Scenario: Stored heart-rate distribution
- **WHEN** the session analysis computes a session with a heart-rate stream
- **THEN** it stores the seconds at each whole bpm (`version` 2, `covered_s`, seconds to 0.001), counting a sample's time to the next sample when the sample is moving (or no moving stream exists), its reading lies within 30 to 240 bpm and its step is at most `max(30 s, 3 × the median step)`; the heart-rate branch records `hr_coverage` (4 decimals) and the distribution hash whenever one exists, and takes the average heart rate (`hr_basis` `average`) below 80 % coverage.

Detailed contract: thresholds follow `resolve_current_thresholds` per day with the policy's age limits, and an indoor or virtual ride uses a local indoor power zone of the day first; resting HR comes from the session day or up to 7 days earlier, Garmin first, else the earliest later value within 90 days, flagged. The heart-rate branch takes the threshold HR of the local zone configuration of the day, else of the dated Garmin watch zone set, else the stored observation (v6); Garmin's max HR of the default zone set carries no sport and applies to all sports, a sport-specific value of the day winning (v6). The session duration is the positive moving duration, else the elapsed duration, and a strength rating counts only when local or Garmin (v7). The strength factor uses the locally or Garmin-rated ride and run sessions with a local load in the 365 days up to the session day; each pair's AU uses the duration of its TSS. Yoga and alpine ski get no value, walking takes the heart-rate branch; an IF above 2.0 is rejected. The pass runs as the first canonical backfill follow-up, triggered by worker start, completed Garmin and Wahoo jobs, local zone changes, session corrections and their undo, a changed session RPE and its undo, a changed profile sex or time zone and a changed preferred threshold source; one invalid session value never stops the pass. It keeps content-free counts that diagnostics and the log (`local_load_reconciled`) report.

Evidence: `backend/performance/local_tss.py`, `backend/sync/local_load.py`, `backend/sync/canonical_backfill_assembly.py`, `backend/sync/executor.py:SyncJobExecutor.run`, `backend/athlete/zones.py:ZoneConfigurationService`, `backend/activities/feedback.py:ActivityFeedbackService`; `tests/test_local_tss.py`, `tests/test_activity_feedback.py`, `tests/test_local_load_store.py`, `tests/test_sync_executor.py`, `tests/test_zone_configuration_canonical.py`, `docs/performance-methods/m6-local-tss-load.md`. Added evidence: `backend/performance/session_analysis.py:heart_rate_histogram`, `backend/sync/local_load.py:_load_fields`, `tests/test_local_load_store.py:test_a_newly_stored_histogram_recomputes_on_the_next_pass`, `tests/test_local_load_store.py:test_served_strength_load_names_its_rpe_band_and_slope`, `tests/test_local_tss.py:test_reasons_for_missing_inputs`, `tests/test_local_tss.py:test_strength_ignores_a_relayed_intervals_rating`.

### Requirement: Local session metrics are stored descriptive values
The system SHALL compute M8 `local-session-metrics` v4 for each canonical ride and run: efficiency factor (EF), variability index (VI), mechanical work and aerobic decoupling. It SHALL store each value as a derived observation owned by the session with method version and input fingerprint, and SHALL NOT use a provider EF, VI, decoupling or work.

#### Scenario: Definitions
- **WHEN** a ride or run has the inputs of a metric
- **THEN** EF is ride NP / average HR in W/bpm and run grade-adjusted, else average, speed × 60 / average HR in (m/min)/bpm; VI is ride NP / average power; work is the device work total, else the integrated full-resolution power stream with at least 85 % coverage of the moving duration, counting only moving samples when a moving stream exists and falling back to the elapsed duration when the moving duration is 0 (v4); decoupling is the drift of the session analysis `aerobic_analysis`, on Minetti 2002 grade-adjusted speed for outdoor runs and none for an outdoor run without grade or altitude.

#### Scenario: Ride with stored streams
- **WHEN** a Garmin ride with NP 210 W, average power 200 W and average HR 142 bpm has 50 minutes of steady full-resolution power and heart-rate streams
- **THEN** its summary serves `efficiency_factor`, `variability_index` 1.05, `work_kj` from the stream and `decoupling_pct`, each labelled `derived`, and the detail document shows the same values.

#### Scenario: Unchanged inputs
- **WHEN** a pass finds every stored fingerprint equal to the current one
- **THEN** it decodes no stream and writes nothing.

#### Scenario: Guards
- **WHEN** EF, VI and work are computed
- **THEN** EF needs an average heart rate of 30 to 240 bpm and VI is kept only within 0.5 to 5.0; stream work sums `power × step / 1000` kJ over samples with a step of 5 s or less and a power of 0 or more (when a moving stream exists, only moving ones) and needs the covered time to be at least 85 % of the positive moving duration, else of the positive elapsed duration; a value whose guard fails is withheld, not zeroed.

#### Scenario: Grade-adjusted speed
- **WHEN** an outdoor run is analysed
- **THEN** each speed sample is multiplied by `C(g) / C(0)` with `C(g) = 155.4 g⁵ − 30.4 g⁴ − 43.3 g³ + 46.3 g² + 19.5 g + 3.6` (Minetti 2002), `g` the fractional grade clamped to ±0.45, taken from the grade stream, else from the altitude change over the next 200 m of distance; without either there is no decoupling.

Detailed contract: the fingerprint covers the method version, the session-analysis method, the summary inputs (start, local day, recording origin, sport, environment, durations, HR, power, speeds, device work), the content hashes of the full-resolution stream sets and the session's records in merge order. The pass runs as a canonical backfill follow-up after the local load, at most 100 recomputed sessions per transaction and no longer than the backfill batch time, and keeps the fingerprint of sessions computed without a value so they are not decoded again. Missing streams are not fetched by this stage. Diagnostics report content-free counts (`session_metrics`); the log event is `session_metrics_reconciled`. The device energy estimate is mapped separately as `energy_kcal` (Garmin `calories`, Wahoo `calories_accum`).

Evidence: `backend/performance/session_metrics.py`, `backend/performance/session_metrics_reads.py`, `backend/sync/session_metrics.py`, `backend/sync/canonical_backfill_assembly.py`, `backend/performance/canonical_detail.py`; `tests/test_session_metrics.py`, `docs/performance-methods/m8-local-session-metrics.md`. Added evidence: `backend/performance/grade_adjustment.py:grade_adjusted`, `tests/test_session_metrics.py:test_a_zero_moving_duration_uses_the_elapsed_duration_for_work`, `tests/test_session_metrics.py:test_work_counts_moving_samples_only`.

### Requirement: Local fitness, fatigue and form are a labelled model estimate
The system SHALL compute M7 `local-fitness-fatigue` v1 on read as the exponentially smoothed stored M6 load per local day with τ 42 days (fitness) and 7 days (fatigue), and form as fitness minus fatigue of the same day. The curves SHALL start at 0 before the first day with a stored local load of the whole history and SHALL NOT be stored, seeded, corrected or mixed with Intervals.icu CTL, ATL or form.

#### Scenario: Reference values
- **WHEN** 80 TSS fall on every second day for 120 days
- **THEN** the last day shows the recursion values of both curves and their difference, rounded to 0.1.

#### Scenario: Session without a local load
- **WHEN** a day holds an unrated or uncalibrated strength session, a yoga session, or another session without a stored local load
- **THEN** the session adds nothing, the day is `incomplete` with the number of such sessions and their rated session-RPE AU, and the curve values equal those without the session.

#### Scenario: Mixed day and incomplete share
- **WHEN** a day holds one session with a local load and one without
- **THEN** the loaded session's load enters the recursion, the day is `incomplete` and keeps its curve values also on or after the first open day; the result reports `incomplete_days`, `incomplete_share` (0 to 1, three decimals) and per such day `sessions_without_load` and `session_rpe_au_without_load`.

#### Scenario: Chart note
- **WHEN** the load tab shows the curve
- **THEN** it notes "N Einheiten ohne TSS" (or "1 Einheit ohne TSS") and, above 0, "N % der Tage unvollständig", computed over the visible days.

#### Scenario: Warm-up and open days
- **WHEN** the first load day is less than 84 days old, or a day from the last sync on has no session
- **THEN** fatigue has no value before day 14, fitness and form none before day 84, and the open day has no value while the state is held.

Detailed contract: each result names `metric_id` `local_fitness_fatigue`, `method_id`, `method_version`, unit `TSS/d`, status `estimate` or `insufficient_data` with reason `warmup` or `no_load`, period, parameters with the input load method, per-state day coverage (`loaded`, `incomplete`, `rest`, `open`, `no_history`), the count of sessions without a load, the latest valued day, per-day `state`, `load`, `fitness`, `fatigue` and `form`, method note, limits and the card `docs/performance-methods/m7-local-fitness-fatigue.md`. The loads come from `LocalLoadDayReader`, summed per stored local day. The Coach training report carries it for all-sport reports, the public performance history for the load tab's 84 days, where the PWA draws one chart of the three curves labelled as locally computed.

Evidence: `backend/performance/fitness_fatigue.py:local_fitness_window`, `backend/performance/smoothed_load.py:ewma_walk`, `backend/sync/local_load.py:daily_local_loads`, `backend/performance/training_report.py:training_report`, `backend/http_api/public_performance.py:PublicPerformanceStateService`, `public/analysis.js:appendLocalFitnessChart`; `tests/test_fitness_fatigue.py`, `tests/test_local_load_store.py`, `tests/test_performance_coach_ui_parity.py`, `e2e/analysis-info.spec.js`, `docs/performance-methods/m7-local-fitness-fatigue.md`.

### Requirement: DFA-α1 first threshold is a labelled research-grade estimate
The system SHALL derive per chest-strap recording the heart rate where the regression of DFA-α1 on window heart rate reaches 0.75 (M10 `dfa-alpha1-first-threshold` v2), and for the athlete the median of the good run sessions of 60 days as percent of the run threshold HR. It SHALL give no result when a stop rule fails and SHALL label the value an estimate; the card is the numeric contract.

#### Scenario: Windows and alpha1
- **WHEN** a segment of the RR series is analysed
- **THEN** beats outside 300 to 2000 ms or more than 20 % from the last accepted beat are dropped (a level held for 5 beats is accepted), the artifact-free series is detrended with smoothness priors (λ 500), and 120 s windows every 30 s on the beat clock are used when they hold at least 100 beats, at most 5 % artifacts and a heart-rate step of at most 8 bpm between their halves; alpha1 is the slope over boxes of 4 to 16 beats.

#### Scenario: Stop rules
- **WHEN** a recording has fewer than 10 windows, a window heart-rate spread under 10 bpm, an alpha1 range that does not reach 0.65 and 0.85, a rising line, or a crossing outside the observed heart rates
- **THEN** it gives no result, and the athlete-level estimate needs at least 3 good-quality run sessions.

#### Scenario: Quality
- **WHEN** a recording has at least 20 windows, an artifact share of at most 0.03 and R² of at least 0.5
- **THEN** its quality is `good`, else `low`; the athlete-level quality is `good` with at least 5 sessions that spread at most 5 percentage points.

Evidence: `backend/canonical/dfa_alpha1.py:first_threshold`, `backend/canonical/dfa_alpha1.py:artifact_flags`, `backend/canonical/dfa_alpha1.py:alpha1`, `backend/canonical/dfa_alpha1.py:detrend`, `backend/performance/first_threshold_estimate.py:first_threshold_estimate`; `tests/test_dfa_alpha1.py:test_the_estimate_is_the_heart_rate_where_alpha1_reaches_075`, `tests/test_dfa_alpha1.py:test_a_steady_run_never_crosses_and_gives_no_estimate`, `tests/test_dfa_alpha1.py:test_too_few_windows_give_no_estimate`, `tests/test_dfa_alpha1.py:test_windows_with_a_fast_heart_rate_step_are_left_out`, `tests/test_first_threshold_estimate.py:test_five_agreeing_sessions_make_a_good_estimate`, `docs/performance-methods/m10-dfa-alpha1-first-threshold.md`.
