# performance-and-readiness Specification

## Purpose

Describe deterministic local performance, training-load, readiness, recovery, body, history, and report projections. Provider forecasts and derived observations retain their evidence limits; these requirements do not claim medical or physiological validation.

## Requirements

### Requirement: Current performance metrics with explicit fallback
The system SHALL compose current body, cycling/running thresholds, VO2max, maximum HR, Zone-2 pace, eFTP, and running predictions from supported local provider/profile inputs with source and unit metadata. It SHALL use metric-specific Garmin/Intervals/Wahoo/manual precedence, preserve sport scope, and reject implausible values. Canonical and compatibility inputs SHALL preserve the same supported public metric shape without mutating callers.

#### Scenario: Garmin thresholds available
- **WHEN** plausible Garmin cycling FTP or running threshold values coexist with Intervals settings
- **THEN** current composition prefers Garmin for those supported metrics and exposes its source/unit/date metadata.

#### Scenario: Fallback and no value
- **WHEN** a preferred source is missing
- **THEN** the implemented sport, wellness, athlete, manual, or Wahoo fallback may supply that metric; if no eligible source exists its value remains unknown.

Evidence: `backend/performance/current_metrics.py:current_performance_metrics`, `backend/performance/canonical_current.py:read_current_inputs`; `tests/test_performance_current_metrics.py:test_garmin_priority_and_metric_shape`, `tests/test_performance_current_metrics.py:test_intervals_wellness_athlete_profile_fallbacks_and_eftp`, `tests/test_performance_current_metrics.py:test_invalid_values_and_inputs_are_not_mutated`.

### Requirement: Load rollups and actual-load reconstruction
The system SHALL calculate explicit current/previous 7- and 30-day completed-activity rollups and supported actual ATL reconstruction using known completed loads. It SHALL sum multiple known loads on the same day, decay the reconstructed series across gaps using its implemented model, and keep Intervals CTL/ATL/form separate from Garmin measured acute load. Activity-derived load SHALL not be presented as Garmin's device-reported acute load.

#### Scenario: Multiple sessions and rest days
- **WHEN** a day contains several completed loads and later days have no activity
- **THEN** rollups sum known contributions and actual ATL evolves through the implemented decay rather than copying a future planned load.

#### Scenario: Missing or conflicting Garmin acute load
- **WHEN** no dated valid measured acute-load value exists or device values conflict
- **THEN** Garmin acute-load history leaves the date unknown instead of reconstructing it from daily/chronic activity totals.

Evidence: `backend/performance/load.py:activity_rollup`, `backend/performance/load.py:actual_atl_series`, `backend/performance/load_context.py:performance_load_context`, `backend/performance/garmin_load.py:acute_load_value`; `tests/test_performance_load.py:test_actual_atl_decays_across_missing_days_and_is_sorted`, `tests/test_performance_chart_history.py:test_garmin_acute_load_is_dated_and_never_derived_from_daily_or_chronic_load`, `tests/test_performance_chart_history.py:test_acute_load_rejects_invalid_and_conflicting_device_values`.

### Requirement: Training reports retain coverage and actual execution
The system SHALL build local period reports from deduplicated activity rows using athlete-local dates, exclude future completed data, and expose measured-session coverage for duration, distance, and load. Reports SHALL include supported period comparisons, daily/cumulative load, eight calendar weeks of load, sports, key sessions, feedback, and plan-execution context with a common period. Unknown values SHALL stay unknown while valid zero load remains measured.

#### Scenario: Partial current week
- **WHEN** a report includes the current calendar week with measured, zero, and missing load rows
- **THEN** it reports the partial period and measured/total-session counts, deduplicates copies, and includes valid zero contributions.

#### Scenario: Timezone boundary or future record
- **WHEN** an absolute start crosses an athlete-local midnight or an activity is dated in the future
- **THEN** grouping uses the athlete-local date and future completed evidence does not inflate historical totals.

Evidence: `backend/performance/training_report.py:training_report`, `backend/performance/training_report.py:activity_day`, `backend/performance/report_service.py:TrainingReportReadService`; `tests/test_training_report.py:test_eight_week_load_totals_keep_missing_zero_duplicates_and_boundaries`, `tests/test_training_report.py:test_sport_filter_and_plan_execution_use_the_same_period`, `tests/test_training_report.py:test_timezone_boundary_and_future_records_are_handled_without_provider_reads`.

### Requirement: Training focus and recorded sensor zones
The system SHALL summarize the supported 28-day training focus from recorded heart-rate and power zones and Garmin activity training-effect categories with source freshness and classification coverage. Heart-rate and power zones SHALL remain separate and bounded by session coverage. Unknown categories, missing identities/load, and unsupported strength classification SHALL remain unclassified rather than becoming assumed endurance training.

#### Scenario: Known Garmin category and load
- **WHEN** an identified activity has a supported recorded primary-effect category and usable load
- **THEN** its contribution enters the corresponding low-aerobic, high-aerobic, or anaerobic category with source coverage.

#### Scenario: Sensor or category gap
- **WHEN** a session has only one sensor's zone times or lacks a supported category
- **THEN** that sensor remains separate and missing category evidence increases unknown coverage rather than being inferred from another sensor.

Evidence: `backend/performance/training_focus.py:training_focus`, `backend/performance/training_report.py:zone_distribution`; `tests/test_training_focus.py:test_recorded_hr_and_power_zones_remain_separate_and_bounded`, `tests/test_training_focus.py:test_activity_without_identity_is_not_classified_from_its_category`, `tests/test_training_report.py:test_sensor_zones_stay_separate_and_strength_is_not_classified_as_endurance`.

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

Detailed contract: Intervals eFTP averages SHALL use actual Intervals estimates rather than configured FTP; race predictions, endurance scores, running tolerance, readiness history, and weekly training status SHALL retain their supported observation dates and aggregation metadata.

Evidence: `backend/performance/chart_history.py:analysis_history`, `backend/performance/comparisons.py:performance_comparisons`, `backend/performance/eftp.py:eftp_30_day_average`, `backend/performance/report_service.py:TrainingProfileSelectionService`; `tests/test_performance_chart_history.py:test_sources_remain_separate_with_no_backdating_of_current_settings`, `tests/test_performance_chart_history.py:test_race_prediction_history_does_not_backfill_current_estimates`, `tests/test_training_report.py:test_running_speed_selects_fastest_effort_and_distance_selects_shortest`.

### Requirement: Current and planning recovery sources
The system SHALL compose sleep duration/score, resting HR, HRV, readiness, supported averages, and planning day recovery with explicit source/date. Sleep/HRV/resting HR prefer supported Garmin values and readiness prefers eligible Intervals values. Per-day planning values SHALL use their date-specific source priority, preserve absent days, and include available saved/current morning Body Battery through its dedicated path. Source freshness SHALL distinguish measurement date from fetch time.

#### Scenario: Providers disagree on readiness
- **WHEN** eligible Intervals readiness and Garmin readiness coexist for the supported current/day context
- **THEN** the Intervals readiness path takes priority while Garmin remains available for its other supported recovery values.

#### Scenario: Recently fetched old measurement
- **WHEN** a source was fetched recently but its latest measurement is old or missing
- **THEN** source metadata reports measurement age/unknown status rather than treating the fetch time as proof of a current reading.

#### Scenario: Current recovery values come from canonical observations only
- **WHEN** the current performance context is composed
- **THEN** sleep duration/hours, sleep score, resting HR, HRV and readiness, their 7-day averages, source labels and Garmin measurement dates are derived only from canonical observations; values present only in the raw Garmin view or only in snapshot wellness carrier fields are not shown, and without canonical inputs these values are absent rather than read from provider data.

#### Scenario: Averages never mix providers
- **WHEN** a current recovery value is selected from one provider
- **THEN** its 7-day average uses only that provider's daily observations in the seven days ending on the current day, and a metric without a selected value averages the Intervals days.

#### Scenario: Garmin-only recovery without a wellness day
- **WHEN** no usable Intervals wellness day exists but Garmin recovery observations do
- **THEN** the Garmin values are still selected for the current recovery context and personal baselines.

Evidence: `backend/performance/recovery_context.py:performance_recovery_context`, `backend/performance/planning_recovery.py:planning_recovery_view`, `backend/performance/freshness.py:garmin_source_freshness`; `tests/test_performance_planning_recovery.py:test_intervals_values_keep_sources_and_garmin_priority`, `tests/test_performance_planning_recovery.py:test_saved_and_current_morning_body_battery`, `tests/test_performance_freshness.py:test_current_stale_partial_unknown_and_notes`, `tests/test_performance_recovery_context.py`, `tests/test_characterization_recovery.py`.

### Requirement: Personal recovery baselines and sleep deficit
The system SHALL form personal recovery distributions separately by provider and measurement method, exclude the current reading from its comparison baseline, require at least 14 prior matching nights for provisional classification and 28 for full classification, and leave stale/future evidence unclassified. RMSSD and SDNN SHALL not be pooled. Sleep deficit SHALL require an explicit valid sleep target, sum only known-night shortfalls, and never offset them with excess sleep on another night.

#### Scenario: Baseline coverage thresholds
- **WHEN** a current reading has 13, 14, or 28 prior matching nights
- **THEN** its classification is insufficient, provisional, or fully supported respectively, and the current reading does not shift the baseline median.

#### Scenario: Missing nights or sleep target
- **WHEN** fewer than seven recent nights are known or no explicit valid sleep target exists
- **THEN** deficit coverage is partial or no target-based deficit is produced; missing nights are not imputed.

#### Scenario: Baselines read daily canonical observations
- **WHEN** personal baselines and sleep deficits are computed, with or without an Intervals snapshot
- **THEN** each provider's daily sleep duration, resting HR, RMSSD and SDNN observations form the series, with the existing bounds and measurement labels; raw provider views are not read, and without canonical inputs no baseline is produced.

#### Scenario: Provider switch or gap
- **WHEN** the athlete's recovery data moves from one provider to another, a day is missing, or the newest value is older than yesterday
- **THEN** each provider keeps its own series, missing days are not filled from the other provider, and stale or insufficient series report the same insufficient/stale status as before.

Evidence: `backend/performance/personal_recovery.py:personal_recovery`; `tests/test_personal_recovery.py:test_coverage_and_excluding_current_value_from_baseline`, `tests/test_personal_recovery.py:test_future_stale_and_separate_hrv_methods_are_not_classified`, `tests/test_personal_recovery.py:test_deficit_uses_known_nights_and_never_offsets_with_long_sleep`.

### Requirement: Sleep timing and tagged-day associations
The system SHALL derive sleep regularity from validated dated onset/wake intervals with timezone/DST-aware duration and separate source/method series. It SHALL keep insufficient coverage explicit. Tagged-day analysis SHALL use only explicit boolean answers paired with the following provider-dated night, require ten measured days per comparison group, and label results as observed associations rather than causal effects or inferred answers.

#### Scenario: Sleep across midnight or DST
- **WHEN** valid sleep intervals cross midnight or a clock change
- **THEN** local timing comparisons use circular timing logic and actual interval duration while source/method series remain separate.

#### Scenario: Unanswered tag
- **WHEN** a day has no explicit tag answer or no measured following night
- **THEN** it is excluded from both groups rather than treated as a negative answer; insufficient groups expose no confident association statistic.

#### Scenario: Sleep timing input before canonical sleep periods
- **WHEN** sleep regularity is computed before canonical sleep periods exist (#1419)
- **THEN** onset and wake times are still read from the stored provider sleep and wellness records, as the only recovery input not yet read from canonical observations.

Evidence: `backend/performance/personal_recovery.py:sleep_regularity`, `backend/performance/tag_impact.py:tag_impact`; `tests/test_personal_recovery.py:test_sleep_regularity_circular_midnight_median_and_source_separation`, `tests/test_personal_recovery.py:test_sleep_intervals_reject_future_missing_and_reversed_and_keep_dst_duration`, `tests/test_training_record_features.py:test_tag_impact_requires_ten_measured_days_in_each_explicit_group`.

### Requirement: Morning Body Battery sample recovery
The system SHALL derive a morning reading from validated Garmin samples around actual sleep, retain date/attempt/status metadata, and use bounded retry/cache decisions. Automatic morning refresh SHALL start no earlier than 05:00 athlete-local time, use at most three attempts with fifteen-minute retry spacing, and stop repeating a ready reading.

#### Scenario: Sleep bounds and both samples available
- **WHEN** a valid before-sleep and first post-sleep sample exist in the allowed windows
- **THEN** the stored day becomes ready with both measurement timestamps and Garmin source, and subsequent cache reads report already loaded.

#### Scenario: Missing samples or failed request
- **WHEN** sleep bounds/samples are unavailable or the provider fails
- **THEN** the day retains a safe unavailable/error outcome and attempt metadata, retries respect spacing/count, and no Body Battery level is inferred from charged/drained totals.

Detailed contract: Before-sleep samples SHALL be limited to four hours before sleep; morning samples SHALL fall between sleep end and at most one hour later, bounded by the attempt instant.

Evidence: `backend/performance/morning_battery.py:morning_body_battery_record`, `backend/performance/morning_battery.py:cached_result`, `backend/performance/morning_battery_service.py:MorningBodyBatteryService.refresh`; `tests/test_morning_battery_service.py:test_refresh_before_five_is_noop_and_logs_failure_after_five`, `tests/test_morning_battery_service.py:test_cache_decisions_short_circuit_without_lock_or_remote`, `tests/test_morning_battery_service.py:test_remote_success_uses_injected_transport_and_persists_ready_values`.

### Requirement: Body history, power-to-weight, and daily health
The system SHALL retain dated weight/body-fat histories and daily energy/count measurements with valid units, source freshness, and gaps. Historical power-to-weight SHALL use eligible dated FTP and sufficiently recent measured weight rather than current manual profile values projected backward. Supported daily energy SHALL distinguish total/active components. Provider projections SHALL keep unsupported optional values unknown instead of assuming zero or inventing a derived measurement.

#### Scenario: Same-day body measurements
- **WHEN** multiple valid provider weigh-ins occur on a day
- **THEN** supported timestamp ordering selects the daily measurement while weight/body-fat unit handling remains independent.

#### Scenario: Missing historical weight or FTP
- **WHEN** historical FTP lacks an eligible recent measured weight or only current profile weight is available
- **THEN** historical power-to-weight remains unknown and no manual current value is backfilled into the series.

Evidence: `backend/performance/body.py:body_history`, `backend/performance/garmin_weight.py:garmin_weight_daily_records`, `backend/performance/daily_health.py:read_daily_health_by_date`; `tests/test_performance_body.py:test_ftp_sources_and_weight_age_limit`, `tests/test_performance_body.py:test_manual_profile_values_are_not_historical_and_invalid_garmin_values_drop`, `tests/test_performance_body.py:test_garmin_daily_record_uses_latest_timestamp_and_converts_pounds`.

### Requirement: Observed season preparation and read-only load scenarios
The system SHALL separate observed competition preparation from calendar phase, expose supported 12-week sport-specific training/long-session evidence and nullable target context, and keep absent evidence unknown. Explicit load scenarios SHALL use dated CTL/ATL basis, labeled planned-load estimates, and fixed completed-today load, produce deterministic local curves with input identity, and leave local and remote plans unchanged.

#### Scenario: Past competition evidence
- **WHEN** preparation for a past competition is read
- **THEN** the evidence window ends at that competition's date rather than borrowing later training; future competitions retain current evidence through today without claiming race readiness or a race-time prediction.

#### Scenario: Alternative load simulation
- **WHEN** valid scenario inputs and yesterday's CTL/ATL are available
- **THEN** current/alternative curves use the declared local 42-/7-day constants, apply requested scale/taper to eligible planned loads, preserve today's completed load without scaling/double counting, and label estimates and model assumptions.

#### Scenario: Missing scenario basis
- **WHEN** CTL/ATL or a necessary planned/completed load is unavailable and no supported estimate exists
- **THEN** the simulation reports insufficient data and missing units instead of filling necessary evidence with zero; applying a changed plan remains a separate preview/approval flow.

Evidence: `backend/performance/report_service.py:TrainingSeasonReadService.season`, `backend/planning/season_preparation.py:season_preparation`, `backend/planning/season_preparation.py:load_scenarios`; `tests/test_season_preparation.py:test_past_competition_window_is_anchored_at_event_date`, `tests/test_season_preparation.py:test_scenarios_are_deterministic_nonmutating_and_taper_changes_load`, `tests/test_season_preparation.py:test_missing_basis_or_planned_load_is_not_zero_filled`, `tests/test_season_preparation.py:test_completed_today_load_is_fixed_and_not_double_counted_or_scaled`.

### Requirement: Versioned method evidence cards
Every local performance or recovery method with a planned or offered physiological interpretation SHALL have a versioned evidence card in `docs/performance-methods/`. Each card SHALL record construct, formula, sources, population, protocol, exclusion and stop rules, deviations, classification, claim list and review state. Every numeric rule SHALL be tagged `source` or `product assumption` with a rationale. No numeric evidence confidence SHALL be invented.

#### Scenario: Card is incomplete
- **WHEN** a card lacks a required section, has a numeric rule without a valid tag or rationale, or cites an evidence ID missing from the register
- **THEN** the repository card check fails.

#### Scenario: Deferred method
- **WHEN** a method family is recorded as deferred in the register (M5)
- **THEN** it has no card and produces no output until its own work package adds one.

Evidence: `docs/performance-methods/README.md` and the four method cards; `tests/test_performance_method_cards.py`.

### Requirement: Claim lists bound physiological statements
API, UI and Coach output SHALL NOT make statements that the method's card forbids. A physiological interpretation SHALL stay blocked until the independent review recorded on its card releases it; descriptive statements that the card allows MAY be shown before that review.

#### Scenario: Interpretation not yet reviewed
- **WHEN** a card records the interpretation as `blocked`
- **THEN** the method is limited to the card's descriptive statements, and no training clearance, diagnosis or model-based recommendation is derived from it.

#### Scenario: Reviewed interpretation
- **WHEN** the card records `released` with date and reviewer for an interpretation
- **THEN** implementations may present exactly the allowed statements for it, with the card's limits and status.

Evidence: claim lists in `docs/performance-methods/m1-session-rpe-load.md`, `m2-hrv-resting-hr.md`, `m3-sleep-duration-timing.md`, `m4-critical-power-speed.md`. Runtime enforcement is added by the implementing work packages (#1426–#1431); this change does not alter current runtime output.

### Requirement: Method input fixtures
Every method with an evidence card SHALL have synthetic input fixtures for one complete, one incomplete and one contradictory input set, each with a defined outcome: a value, no value with a status or reason, or an exclusion. The fixtures SHALL keep transport provider, recording origin and local method apart and SHALL count an activity imported from several providers once.

#### Scenario: Incomplete input
- **WHEN** a required input is missing for a method (for example no session RPE, too few earlier nights, or only a downsampled stream)
- **THEN** the fixture asserts that no value is produced or that the input is excluded, with the status or reason the current code gives; where current code still produces a value from that input, the fixture pins it as a known gap naming the owning issue.

#### Scenario: Contradictory providers
- **WHEN** two providers report different values for the same input
- **THEN** the fixture asserts that the values stay separate per provider and method and are not averaged.

Evidence: `tests/test_performance_method_inputs.py`.

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
- **WHEN** a last-night RMSSD is selectable from any provider
- **THEN** it is shown and the weekly average is not used.

Evidence: `backend/performance/recovery_context.py:performance_recovery_context`, `backend/performance/context.py:current_performance_context`; `tests/test_performance_recovery_context.py:test_weekly_hrv_is_a_labelled_fallback_without_average`, `tests/test_performance_recovery_context.py:test_last_night_rmssd_wins_over_the_weekly_average`, `tests/test_performance_context.py:test_weekly_hrv_fallback_keeps_its_garmin_freshness`.

### Requirement: Morning sleep readiness reads canonical sleep days
The manual morning check-in SHALL decide whether today's Garmin sleep is available from the latest canonical Garmin sleep observation day, combined with the Garmin source freshness, and SHALL not read sleep days from the raw Garmin view.

#### Scenario: Sleep observation for today exists
- **WHEN** a Garmin sleep duration or score observation exists for the check-in day and the sleep source is current or partial
- **THEN** the check-in proceeds.

#### Scenario: Only raw data has today's sleep
- **WHEN** the raw Garmin view has today's sleep but no canonical sleep observation exists for today
- **THEN** the check-in waits for sleep data.

Evidence: `backend/coach/morning.py:ManualMorningCheckinService`, `backend/performance/garmin_observations.py:garmin_sleep_ready_for_checkin`; `tests/test_coach_manual_morning.py:test_missing_or_stale_sleep_raises_without_refreshing_battery`, `tests/test_garmin_observations.py:test_sleep_day_comes_from_the_observation_never_from_raw_sleep`.

### Requirement: Canonical sleep regularity parity
Sleep timing regularity SHALL read canonical periods without traversing raw provider payloads. Equivalent synthetic periods SHALL preserve the existing sleep-regularity-v1 results, source separation and coverage before any intentional method change. Nightly bounds SHALL not be labelled as a complete sleep/wake series or original SRI.

#### Scenario: Equivalent stored nights
- **WHEN** equivalent synthetic nights are supplied through canonical periods rather than the previous provider aliases
- **THEN** regularity values, method identity and coverage match the existing method.

#### Scenario: Sparse coverage
- **WHEN** missing nights or overlapping provider periods exist
- **THEN** those distinctions remain explicit and the result does not claim original SRI or fabricate full-day coverage.

### Requirement: Canonical retained provider performance reads
Affected history, recovery, nutrition and Coach reads SHALL obtain retained provider status, load balance, tolerance, score details, performance history, Body Battery, stress, resting energy and subjective wellness from canonical data. Provider labels, dates and missing-value semantics SHALL survive without a snapshot dependency in these paths.

#### Scenario: Canonical data without snapshot
- **WHEN** retained canonical provider data is available and provider views/snapshots are absent
- **THEN** affected read surfaces remain available with their supported values, dates and source labels.

#### Scenario: Proprietary score absent
- **WHEN** a proprietary provider score is not recorded
- **THEN** it remains unknown and no local recreation is substituted.

Evidence baseline: `backend/performance/personal_recovery.py`, `backend/performance/canonical_personal_recovery.py`, `backend/performance/chart_history.py`, `backend/performance/garmin_projection.py`; `tests/test_personal_recovery.py`, `tests/test_performance_chart_history.py`. Canonical-only reads and parity require new regression evidence.
