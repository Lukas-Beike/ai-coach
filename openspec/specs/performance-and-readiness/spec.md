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

#### Scenario: Current cycling eFTP comes from canonical observations
- **WHEN** the current performance metrics are composed
- **THEN** `cycling_eftp_watts` is the ride eFTP observation of the latest Intervals sync's athlete record, else the ride eFTP observation of the latest wellness day, else the latest ride activity's eFTP, with the unchanged Intervals source label; the snapshot's athlete `sport_settings` and wellness `sportInfo` are not read for it.

#### Scenario: No canonical eFTP input
- **WHEN** no canonical current inputs exist, or no athlete-record or wellness-day ride eFTP observation is stored
- **THEN** the athlete-record and wellness steps contribute nothing and only the latest ride activity's eFTP can supply the value; otherwise it remains unknown.

#### Scenario: Athlete eFTP without a wellness day
- **WHEN** the latest Intervals sync's athlete record stores a ride eFTP but there is no usable wellness day
- **THEN** `cycling_eftp_watts` is that athlete-record eFTP and the athlete settings of that sync still apply; only the wellness-day eFTP and wellness weight steps contribute nothing.

#### Scenario: Intervals athlete settings come from canonical observations
- **WHEN** current FTP, run threshold power, threshold or Zone-2 pace, threshold or maximum HR, VO2max, athlete weight, body fat, height, W′ or the threshold context's max HR and LTHR come from Intervals.icu
- **THEN** each value is the athlete-record observation of the latest Intervals sync (sport setting, then athlete-wide value), with unchanged source labels; the snapshot's `athlete` section is never read, and a value the canonical bounds reject (such as a pace faster than 15 m/s or a height outside 30-300 cm) stays unknown. Paces are stored in m/s, so a pace given in s/km is shown rounded to whole seconds per kilometre.

#### Scenario: A later wellness-only write
- **WHEN** a newer Intervals write stores wellness rows but no athlete record
- **THEN** the athlete settings of the latest athlete record still apply, and the wellness weight is the newest stored value of the latest wellness day.

#### Scenario: Run and other sports do not feed cycling eFTP
- **WHEN** Run and Ride eFTP observations coexist
- **THEN** only ride-scoped observations feed `cycling_eftp_watts`.

Evidence: `backend/performance/current_metrics.py:current_performance_metrics`, `backend/performance/canonical_current.py:read_current_inputs`; `tests/test_performance_current_metrics.py:test_garmin_priority_and_metric_shape`, `tests/test_performance_current_metrics.py:test_intervals_wellness_athlete_profile_fallbacks_and_eftp`, `tests/test_performance_current_metrics.py:test_invalid_values_and_inputs_are_not_mutated`. The canonical eFTP scenarios are verified by `tests/test_performance_canonical_current_metrics.py:CanonicalEftpInputTests`, `tests/test_performance_current_metrics.py:test_eftp_follows_the_canonical_chain_then_the_latest_ride_activity`, `tests/test_characterization_current_metrics.py:test_eftp_athlete_then_wellness_then_latest_ride_activity` and `tests/test_performance_canonical_load_metrics.py:EftpTests` (including `test_the_athlete_record_eftp_needs_no_wellness_day`). The athlete-settings scenario is verified by `tests/test_characterization_current_metrics.py` (each synthetic snapshot through the mappers and `read_current_inputs`), `tests/test_intervals_mapping_parity.py:ThresholdParityTests` and `tests/test_intervals_wellness_mapping.py:AthleteSettingsV9Tests`; the wellness-only write by `tests/test_performance_canonical_current_metrics.py:CanonicalCurrentInputTests.test_a_later_wellness_only_write_keeps_the_athlete_settings`.

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

Detailed contract: The report `observed_at` SHALL be the Intervals.icu activity fetch time of the canonical provider coverage, or null when none is stored. Totals are named `moving_duration_s`, `distance_m` and `training_load`; `sports` and sport filters use canonical sports (`ride`, `run`, ...).

Evidence: `backend/performance/training_report.py:training_report`; `tests/test_training_report.py`.

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

#### Scenario: eFTP history reads canonical wellness days
- **WHEN** the eFTP chart, body history or 30-day eFTP comparison is composed
- **THEN** each day contributes at most one value: the ride eFTP observation of that wellness day, else the day's latest ride activity eFTP, both bounded to 20-2000 W; snapshot `sportInfo` is not read, and days without a value remain gaps.

#### Scenario: Form comparison reads canonical form days
- **WHEN** the 7-day form comparison is composed
- **THEN** it averages the form observations of the inclusive seven days ending on the current day, and the average is unknown when no day has an observation.

#### Scenario: History, charts and comparisons read canonical inputs only
- **WHEN** the analysis charts, the Garmin load, training-load projection and Garmin 30-day comparisons (including weight) are composed
- **THEN** they read the canonical activity rows and the canonical Garmin day history only (the weight trend uses the body history's per-day Garmin weights); the stored Garmin view and Intervals snapshot supply sync times, the power curve and a cached provider chart's fetch outcome (stale, failed or unsupported; never its points), and without canonical inputs (`EMPTY_PERFORMANCE_INPUTS`) every such value is unknown.

Detailed contract: Intervals eFTP averages SHALL use actual Intervals estimates rather than configured FTP; race predictions, endurance scores, running tolerance, readiness history, and weekly training status SHALL retain their supported observation dates and aggregation metadata.

Evidence: `backend/performance/chart_history.py:analysis_history`, `backend/performance/comparisons.py:performance_comparisons`, `backend/performance/eftp.py:eftp_30_day_average`, `backend/performance/report_service.py:TrainingProfileSelectionService`; `tests/test_performance_chart_history.py:test_sources_remain_separate_with_no_backdating_of_current_settings`, `tests/test_performance_chart_history.py:test_race_prediction_history_does_not_backfill_current_estimates`, `tests/test_training_report.py:test_running_speed_selects_fastest_effort_and_distance_selects_shortest`. The canonical-inputs scenario is verified by `tests/test_chart_history_canonical_parity.py`, `tests/test_garmin_training_load_canonical_parity.py`, `tests/test_performance_comparisons.py` and `tests/test_performance_canonical_parity.py:test_empty_performance_inputs_stand_for_no_canonical_values`. The canonical eFTP and form scenarios are verified by `tests/test_performance_eftp.py`, `tests/test_performance_comparisons.py:test_eftp_and_form_comparisons_read_the_canonical_days_only`, `tests/test_performance_wellness.py:WellnessFormTests`, `tests/test_characterization_body_history.py` and `tests/test_performance_canonical_load_metrics.py:test_chart_and_body_history_read_the_canonical_series`.

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

### Requirement: Personal recovery comparison and sleep goal shortfall
The system SHALL form personal recovery distributions separately by provider and measurement method, exclude the current reading from its comparison distribution, require at least 14 prior matching nights for provisional classification and 28 for full classification, and leave stale/future evidence unclassified. RMSSD and SDNN SHALL not be pooled.

#### Scenario: Baseline coverage thresholds
- **WHEN** a current reading has 13, 14, or 28 prior matching nights
- **THEN** its classification is insufficient, provisional, or fully supported respectively, and the current reading does not shift the comparison median.

#### Scenario: Missing nights or sleep target
- **WHEN** fewer than seven recent nights are known or no explicit valid sleep target exists
- **THEN** shortfall coverage is partial or no target-based shortfall is produced; missing nights are not imputed.

#### Scenario: Baselines read daily canonical observations
- **WHEN** personal comparisons and the sleep goal shortfall are computed, with or without an Intervals snapshot
- **THEN** each provider's daily sleep duration, resting HR, RMSSD and SDNN observations form the series, with the existing bounds and measurement labels; raw provider views are not read, and without canonical inputs no comparison is produced.

#### Scenario: Provider switch or gap
- **WHEN** the athlete's recovery data moves from one provider to another, a day is missing, or the newest value is older than yesterday
- **THEN** each provider keeps its own series, missing days are not filled from the other provider, and stale or insufficient series report the same insufficient/stale status as before.

#### Scenario: Quartile position is a comparison, not a norm
- **WHEN** a recovery value lies below or above the quartile range of the athlete's earlier values
- **THEN** every API, UI and Coach text describes it as a position relative to the athlete's own earlier values, states that the middle two quartiles hold about half of the values, and derives no diagnosis, training clearance or training change from it.

#### Scenario: Product rules are not validity claims
- **WHEN** a comparison is provisional, `ok`, insufficient or stale
- **THEN** the displayed state names the coverage or reason (for example fewer than 14 earlier nights or an outdated measurement) and the recovery UI shows no "confirmed" or equivalent validity wording for it.

#### Scenario: Shortfall is not sleep debt
- **WHEN** the sleep goal shortfall is reported or summarized
- **THEN** it is worded as the sum of known shortfalls against the athlete's own sleep goal over known nights, with missing nights and unrecorded naps noted as limits, and no output uses the term sleep debt or states a needed number of hours of recovery sleep.

Detailed contract: The quartile range (method `personal-quartiles-v1`) SHALL be described only as a comparison with the athlete's own earlier values and SHALL not be described as a normal, healthy, abnormal or clinical range, and a position below or above it SHALL not be described as an alarm or deficiency. The 14/28-night thresholds, the 42-day window and the status `ok` are product rules and SHALL not be presented as validity, confirmation or a health standard. The sleep goal shortfall SHALL require an explicit valid sleep target, sum only known-night shortfalls against that target, and never offset them with excess sleep on another night; it SHALL not be called sleep debt or presented as a recovery need.

Evidence: `backend/performance/personal_recovery.py:personal_recovery`, `public/analysis.js:recoveryReferenceLabel`; `tests/test_personal_recovery.py:test_coverage_and_excluding_current_value_from_baseline`, `tests/test_personal_recovery.py:test_future_stale_and_separate_hrv_methods_are_not_classified`, `tests/test_personal_recovery.py:test_deficit_uses_known_nights_and_never_offsets_with_long_sleep`; wording and Coach cases in `tests/test_performance_claim_wording.py` and `tests/test_personal_recovery_coach_cases.py`; `e2e/analysis-info.spec.js` recovery scenarios. Claim lists: `docs/performance-methods/m2-hrv-resting-hr.md`, `m3-sleep-duration-timing.md`.

### Requirement: Sleep timing and tagged-day associations
The system SHALL derive sleep timing variability (method `sleep-timing-variability-v1`) from validated dated onset/wake intervals with timezone/DST-aware duration and separate source/method series, and SHALL keep insufficient coverage explicit. Tagged-day analysis SHALL use only explicit boolean answers paired with the following provider-dated night, require ten measured days per comparison group, and label results as observed associations rather than causal effects or inferred answers.

#### Scenario: Sleep across midnight or DST
- **WHEN** valid sleep intervals cross midnight or a clock change
- **THEN** local timing comparisons use circular timing logic and actual interval duration while source/method series remain separate.

#### Scenario: Unanswered tag
- **WHEN** a day has no explicit tag answer or no measured following night
- **THEN** it is excluded from both groups rather than treated as a negative answer; insufficient groups expose no confident association statistic.

#### Scenario: Sleep timing input before canonical sleep periods
- **WHEN** sleep timing variability is computed before canonical sleep periods exist (#1419)
- **THEN** onset and wake times are still read from the stored provider sleep and wellness records, as the only recovery input not yet read from canonical observations.

#### Scenario: Timing variability is not the Sleep Regularity Index
- **WHEN** the timing variability result, its Coach report section or any description of it is produced
- **THEN** the method id and section name are `sleep-timing-variability-v1` and `sleep_timing_variability`, the Sleep Regularity Index or SRI appears only in a sentence that denies the equivalence, and the unchanged fields `regularity` and `*_deviation_minutes` carry the same values as before the rename.

Detailed contract: Sleep timing variability compares each night's clock times circularly with the athlete's own earlier nights; it is not the Sleep Regularity Index and SHALL NOT be named, labelled or described as such, and no output SHALL share that name.

Evidence: `backend/performance/personal_recovery.py:sleep_timing_variability`, `backend/performance/tag_impact.py:tag_impact`; `tests/test_personal_recovery.py:test_sleep_timing_variability_circular_midnight_median_and_sources`, `tests/test_personal_recovery.py:test_sleep_intervals_reject_future_missing_and_reversed_and_keep_dst_duration`, `tests/test_training_record_features.py:test_tag_impact_requires_ten_measured_days_in_each_explicit_group`, `tests/test_performance_claim_wording.py`.

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

#### Scenario: Body history reads canonical inputs only
- **WHEN** the body history is composed for the performance view or the state bootstrap
- **THEN** Intervals weight and body fat come from the canonical wellness days, Garmin weight, body fat and FTP from the canonical Garmin observations read with the performance inputs, and eFTP from the canonical activity rows; Garmin values present only in the stored view are not shown.

#### Scenario: Daily totals come from canonical observations only
- **WHEN** the 7-day steps, floors and energy averages are composed
- **THEN** they average the canonical daily observations only; Garmin daily stats in the stored view supply freshness, never values.

Evidence: `backend/performance/body.py:body_history`, `backend/performance/canonical_body.py:read_body_inputs`, `backend/performance/daily_health.py:read_daily_health_by_date`; `tests/test_performance_canonical_body_history.py:test_snapshot_garmin_values_are_ignored_without_canonical_values`, `tests/test_performance_body.py:test_ftp_sources_and_weight_age_limit`, `tests/test_performance_body.py:test_manual_profile_values_are_not_historical_and_invalid_garmin_values_drop`, `tests/test_performance_daily_health.py:CanonicalDailyHealthParityTests.test_metrics_window_ignores_the_snapshot_daily_stats`.

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

#### Scenario: Recovery wording is enforced at runtime
- **WHEN** the runtime sources and outputs of the personal recovery comparison, sleep goal shortfall and sleep timing variability are scanned
- **THEN** none contains a term the M2 or M3 card forbids (sleep debt, normal range, abnormal or clinical quartile positions, the Sleep Regularity Index as a name), and the scan fails with the file, line and term otherwise.

Evidence: claim lists in `docs/performance-methods/m1-session-rpe-load.md`, `m2-hrv-resting-hr.md`, `m3-sleep-duration-timing.md`, `m4-critical-power-speed.md`. Runtime enforcement for M2 and M3 wording: `tests/test_performance_claim_wording.py`; the remaining methods are enforced by their work packages (#1427–#1431).

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

### Requirement: Canonical sleep timing variability parity
Sleep timing variability SHALL read canonical periods without traversing raw provider payloads. Equivalent synthetic periods SHALL preserve the existing sleep-timing-variability-v1 results, source separation and coverage before any intentional method change. Nightly bounds SHALL not be labelled as a complete sleep/wake series or the Sleep Regularity Index.

#### Scenario: Equivalent stored nights
- **WHEN** equivalent synthetic nights are supplied through canonical periods rather than the previous provider aliases
- **THEN** timing variability values, method identity and coverage match the existing method.

#### Scenario: Sparse coverage
- **WHEN** missing nights or overlapping provider periods exist
- **THEN** those distinctions remain explicit and the result does not claim the Sleep Regularity Index or fabricate full-day coverage.

### Requirement: Canonical retained provider performance reads
Affected history, recovery, nutrition and Coach reads SHALL obtain retained provider status, load balance, tolerance, score details, performance history, Body Battery, stress, resting energy and subjective wellness from canonical data. Provider labels, dates and missing-value semantics SHALL survive without a snapshot dependency in these paths.

#### Scenario: Canonical data without snapshot
- **WHEN** retained canonical provider data is available and provider views/snapshots are absent
- **THEN** affected read surfaces remain available with their supported values, dates and source labels.

#### Scenario: Proprietary score absent
- **WHEN** a proprietary provider score is not recorded
- **THEN** it remains unknown and no local recreation is substituted.

Evidence baseline: `backend/performance/personal_recovery.py`, `backend/performance/canonical_personal_recovery.py`, `backend/performance/chart_history.py`, `backend/performance/garmin_projection.py`; `tests/test_personal_recovery.py`, `tests/test_performance_chart_history.py`. Canonical-only reads and parity require new regression evidence.

### Requirement: Garmin current performance metrics are read from canonical data only
The current Garmin performance metrics (weight, thresholds, VO2max, maximum heart rate and race predictions) SHALL be read from canonical Garmin data only. The stored Garmin view SHALL supply only source freshness on these read paths. Only the sync's performance-history merge SHALL parse a fetched Garmin payload, before it is stored.

#### Scenario: Activity maximum heart rate
- **WHEN** a sport has neither its own nor a generic canonical Garmin profile maximum heart rate
- **THEN** its maximum heart rate is the highest 80–260 bpm maximum heart rate of that sport's active canonical Garmin activity records outside deleted sessions, read from the same source as the observations and dated on the athlete-local start day of the newest activity with that value; its note names the activities, while a sport with a profile value keeps the heart rate zone note.

#### Scenario: Equivalent stored payload and canonical data
- **WHEN** a Garmin payload is stored and projected into canonical observations and activity records
- **THEN** the Garmin performance metrics read from the canonical data equal the metrics the payload parser gives for that payload, including the activity maximum heart rate and its date.

#### Scenario: No canonical Garmin data
- **WHEN** the stored Garmin view has performance sections but no canonical Garmin observation or activity record exists
- **THEN** the Garmin performance metrics are absent and no value is read from the view.

#### Scenario: Profile maximum heart rate present
- **WHEN** a canonical Garmin profile maximum heart rate exists for both sports or as a generic value
- **THEN** it is shown and the activity records are not read.

Detailed contract: activity records exist only from the first canonical ingest or backfill onward, so a maximum the stored view retained from activities older than that is not kept (accepted by #1415's decision to derive the value from canonical records). The current maximum heart rate fallback has no day history; no comparison or chart reads one.

Evidence: `backend/performance/garmin_metrics.py:garmin_performance_metrics`, `backend/performance/garmin_metrics.py:garmin_payload_performance_metrics`, `backend/performance/garmin_canonical.py:read_garmin_state`, `backend/db/canonical_store.py:activity_max_hr_rows`; `tests/test_garmin_canonical_reads.py:GarminStateEqualityTests.test_state_has_the_flags_and_values_of_the_snapshot_sections`, `tests/test_garmin_canonical_reads.py:GarminStateEqualityTests.test_table_observations_give_the_payload_state`, `tests/test_garmin_canonical_reads.py:GarminStateEqualityTests.test_activity_max_hr_skips_deleted_sessions`, `tests/test_garmin_canonical_reads.py:GarminCanonicalReaderUnitTests.test_activity_max_hr_is_read_from_the_same_source`, `tests/test_garmin_canonical_reads.py:GarminCanonicalReaderUnitTests.test_profile_max_hr_skips_the_activity_read`, `tests/test_garmin_canonical_reads.py:GarminCanonicalReaderUnitTests.test_only_the_sport_without_a_profile_value_is_labelled_activities`, `tests/test_performance_canonical_current_metrics.py:CanonicalCurrentFromTablesTests.test_populated_tables_serve_the_current_metrics`.

### Requirement: Ramp rate is a labelled local derivation
The system SHALL derive the ramp rate of the current load block as the latest wellness day's CTL minus the CTL of exactly seven days earlier, rounded to two decimals, from canonical Intervals.icu wellness-day CTL observations, and SHALL label it as derived through `current_load.ramp_rate_source`. Intervals.icu's own `rampRate` is not read and can differ from the derived number.

#### Scenario: Both days present
- **WHEN** CTL observations exist for the latest wellness day (58.4) and for seven days earlier (54.1)
- **THEN** `current_load.ramp_rate` is 4.3 and `current_load.ramp_rate_source` is `Intervals.icu CTL (berechnet)`.

#### Scenario: A day is missing
- **WHEN** either CTL day is absent, even though a neighbouring day exists
- **THEN** `ramp_rate` and `ramp_rate_source` are unknown; exact days only, no neighbouring day is substituted and nothing is interpolated.

#### Scenario: Snapshot ramp rate present
- **WHEN** the snapshot wellness row carries its own `rampRate` while the derivation inputs are present or absent
- **THEN** the snapshot value is ignored and only the derived value, or unknown, is shown.

#### Scenario: No wellness day or no canonical inputs
- **WHEN** there is no wellness day or no canonical performance inputs exist
- **THEN** `ramp_rate` and `ramp_rate_source` are unknown and the other load keys keep their behaviour.

Evidence: none for existing behavior (the legacy path passes the snapshot `rampRate` through: `backend/performance/load_context.py:performance_load_context`). Verified by `tests/test_performance_canonical_load_metrics.py:RampRateTests`, `tests/test_performance_load_context.py` and `tests/test_performance_canonical_parity.py`.

### Requirement: Cycling eFTP and form are read from canonical observations only
The system SHALL read cycling eFTP and form only from canonical Intervals.icu observations: the ride-scoped eFTP of the athlete record and of wellness days, and wellness-day form. Activity rows supply only the activity eFTP step. Without canonical inputs these values SHALL be absent rather than read from snapshot wellness rows or sport settings. Values and source labels stay unchanged. Output keys follow the provider-neutral output key requirement.

#### Scenario: No snapshot rows
- **WHEN** the snapshot has no wellness rows and no athlete sport settings but canonical observations exist
- **THEN** `metrics.cycling_eftp_watts`, `comparisons.cycling_eftp_30d`, `current_load.tsb` and `comparisons.form_tsb` equal the values computed from equivalent snapshot rows, apart from the known limits below.

#### Scenario: Carrier fields are ignored
- **WHEN** snapshot wellness rows still carry `tsb`, `rampRate` and `sportInfo`
- **THEN** none of them influences these values.

#### Scenario: Stale and multi-sport data
- **WHEN** the newest wellness day has no eFTP observation, or Run settings coexist with Ride settings
- **THEN** the current eFTP falls to the next step of its chain and the history keeps the older dated values; Run values never feed cycling eFTP.

Detailed contract: since wellness mapper version 8 the eFTP classification follows the legacy readers. The first of two ride sport settings wins, and each `types` text, or `type`, `sport` and `sport_type` of a `sportInfo` entry without a `types` list, classifies a sport, so one setting can serve several sports. Known limits, not requirements: the canonical sport terms also match `velo`, `bicycle` and `jog`, which the legacy readers did not; a reported form value that is not a number yields no form for that day.

Evidence: `backend/providers/intervals_wellness_mapping.py:map_intervals_wellness`, `backend/providers/intervals_wellness_mapping.py:map_intervals_athlete_thresholds`; `tests/test_intervals_wellness_mapping.py` (EFTP and FORM mapping), `tests/test_performance_canonical_parity.py`. The strict-read scenarios are verified by `tests/test_performance_canonical_load_metrics.py` (carrier rows are stripped or contradicting), `tests/test_performance_canonical_parity.py:_assert_load_metric_split` and `tests/test_server_performance.py`.

### Requirement: Report-family reads use canonical activity rows only
The system SHALL read the activities of period reports, the training-record observation list, tag impact, training focus, load rollups, eFTP and season preparation from the canonical activity summary port only, and SHALL NOT fall back to the stored snapshot's `raw_provider_data.activities` or `recent_activities`.

#### Scenario: Canonical rows with an empty snapshot
- **WHEN** any of these reads runs with canonical activity summaries and a snapshot without activity sections
- **THEN** it computes from the summaries exactly as it would with the rows in the snapshot.

#### Scenario: No activity rows
- **WHEN** the canonical summary port returns no summaries
- **THEN** the read returns its existing empty-data result (no sessions, insufficient data) instead of an error or snapshot data.

#### Scenario: Copies stored by the first backfill
- **WHEN** the first canonical backfill stores an Intervals.icu and a Garmin Connect copy of one activity
- **THEN** it links them into one session, so these reads count the activity once.

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

Evidence: observed defect from athlete diagnostics 2026-10-24 (`garmin.source_freshness.endurance_score.observed_at` = 2026-10-23 while the chart's latest point stayed at 2026-10-18); `backend/providers/garmin.py:_collect_historic_metrics`, `backend/providers/garmin.py:targeted_analysis_sources`, `backend/performance/garmin_metric_history.py:_records`, `backend/performance/chart_history.py:_provider_metrics`, `backend/performance/history.py:_provider_metrics`, `public/analysis.js:analysisWeeklyPerformancePoints`; `tests/test_provider_garmin_metric_history.py:test_known_sdk_methods_get_bounded_dates_and_explicit_aggregation`, `tests/test_performance_chart_history.py:test_saved_endurance_group_map_repairs_previously_empty_projection`, `tests/test_performance_chart_history.py:test_daily_weekly_view_metrics_reach_the_newest_measurement`, `tests/test_garmin_analysis_refresh.py:test_targeted_weekly_view_metrics_request_daily_readings`; running tolerance shares the weekly grouping in `public/analysis.js`. Gap: the exact daily `groupMap` key shape is inferred from the SDK docstring and existing weekly handling, not from a captured live payload.

### Requirement: Profile body fat is shown in the Body overview
The Body overview SHALL show a valid saved body-fat profile value labelled as profile data, without projecting it into dated measurement history.

#### Scenario: Profile value exists
- **WHEN** the saved profile contains valid body fat
- **THEN** the overview shows that value and labels it as profile data.

#### Scenario: No profile value exists
- **WHEN** the profile has no valid body-fat value
- **THEN** the overview shows the latest eligible Garmin body-fat reading when available.

Evidence: `public/analysis.js`; `tests/analysis-presentation.test.cjs::body overview uses profile body fat without creating a dated measurement`, `tests/analysis-presentation.test.cjs::body overview falls back to Garmin when the profile fat is absent`.

### Requirement: Daily wellness values are read through a provider-neutral day view
The system SHALL read every daily wellness value of the performance projection from canonical Intervals.icu wellness-day observations, identified by metric kind and keeping each observation's provenance. Performance readers SHALL NOT read snapshot wellness rows or Intervals.icu wellness field names for these values. Without canonical inputs these values SHALL be absent.

#### Scenario: Canonical days without snapshot rows
- **WHEN** canonical wellness-day observations exist and the snapshot holds no wellness rows
- **THEN** `current_load.ctl`, `current_load.atl`, `actual_load`, `comparisons.fitness_ctl`, `comparisons.fatigue_atl`, `metrics.weight_kg`, `metrics.body_fat_pct`, the subjective ratings in `recovery`, `comparisons.weight_kg_30d` and the body history weight and body-fat series equal the values computed before this change from equivalent snapshot rows.

#### Scenario: Snapshot rows contradict the observations
- **WHEN** snapshot wellness rows carry different CTL, ATL, weight, body fat, readiness, subjective or `sportInfo` values than the observations, or carry days without observations
- **THEN** only the observations decide the values and the latest wellness day; snapshot-only days and fields have no effect.

#### Scenario: No canonical inputs
- **WHEN** the performance context is composed without canonical inputs
- **THEN** the context is unavailable: CTL, ATL, weight and body fat from wellness, subjective ratings, wellness-based trend averages and wellness body history are unknown instead of read from the snapshot.

#### Scenario: Availability follows canonical data, not the snapshot
- **WHEN** canonical observations or activities exist without a stored Intervals.icu snapshot, for example a Garmin-only setup after the backfill completed
- **THEN** the context is available with its full metrics, `as_of` is the canonical Intervals.icu sync instant (none without one) and the context source names the stored provider data.

#### Scenario: Canonical data is still being prepared
- **WHEN** the first canonical backfill has not completed
- **THEN** the context is unavailable with reason `canonical_pending` and the status "Daten werden vorbereitet", shows no values, and the Coach context carries the same reason and status.

#### Scenario: Sport-scoped and athlete-record observations
- **WHEN** athlete-record observations (thresholds, athlete weight) or sport-scoped wellness observations exist
- **THEN** they do not become daily wellness values; only the run-scoped wellness-day eFTP feeds the 30-day running threshold-power average.

Detailed contract: the daily wellness values are CTL, ATL, form, weight, body fat, readiness, the subjective fatigue, soreness, stress and mood ratings, and the run eFTP of the trend averages. The snapshot rows not read are `recent_wellness` and `raw_provider_data.wellness`. The current-day window is the 90 days ending on the latest wellness day. The history view covers every stored wellness day.

Evidence: `backend/performance/wellness_days.py:read_wellness_days`, `backend/performance/canonical_inputs.py:read_performance_inputs`; `tests/test_performance_wellness_days.py:WellnessDayTests`, `tests/test_performance_canonical_sections.py:SectionHelperTests` and `SectionReadTests`, `tests/test_performance_canonical_parity.py:CanonicalLoadEdgeTests`, `tests/test_performance_context.py:PerformanceContextTests`, `tests/test_performance_canonical_parity.py:CanonicalReadStatusEndToEndTests`, and `tests/test_performance_canonical_body_history.py:CanonicalBodyLedgerCaseTests`.

### Requirement: Wellness `sportInfo` threshold fallbacks are not read
The system SHALL NOT read cycling or running FTP, LTHR, maximum heart rate, VO2max, threshold pace or Zone-2 pace from Intervals.icu wellness `sportInfo` entries. These values SHALL come only from their remaining sources: Garmin, athlete sport settings, the athlete record, Wahoo and the manual profile. The 30-day `run_threshold_watts` average SHALL read the run-scoped wellness-day eFTP observations, bounded as before.

#### Scenario: `sportInfo` carries threshold keys
- **WHEN** a stored wellness row's `sportInfo` entry carries `ftp`, `lthr`, a maximum heart rate, `vo2max`, `threshold_pace` or a Zone-2 pace
- **THEN** none of them supplies a current metric or a 30-day average.

#### Scenario: Run eFTP average
- **WHEN** run eFTP wellness-day observations exist in the 30 days ending on the current day and the current `run_threshold_watts` has an Intervals.icu source
- **THEN** `comparisons.run_threshold_watts_30d` averages those observations as the snapshot `sportInfo` run eFTP average did; days without an observation are not filled.

Detailed contract: the Intervals.icu wellness `sportInfo` entry provides the sport type, CTL, ATL, eFTP, W′ and Pmax (`tests/fixtures/providers/intervals/wellness.json`); the removed keys are not part of it. No live payload was inspected (evidence gap).

Evidence: `backend/performance/current_metrics.py:current_performance_metrics`, `backend/performance/trends.py:intervals_performance_average`; `tests/test_characterization_current_metrics.py:CurrentThresholdTests.test_wellness_sport_info_ftp_does_not_supply_cycling_ftp`, `tests/test_characterization_current_metrics.py:CurrentMaxHrTests.test_out_of_range_setting_does_not_read_wellness_sport_info`, `tests/test_performance_trends.py:IntervalsPerformanceAverageTests.test_wellness_values_and_run_eftp_are_bounded_and_sport_info_thresholds_absent`, `tests/test_performance_wellness_days.py:WellnessDayTests.test_run_eftp_is_a_separate_sparse_series`.

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
- `current_load.ramp_rate` and `current_load.ramp_rate_source`;
- `thresholds.ftp_w` and `thresholds.w_prime_j`.

They replace `restingHR`, `hrv`, `sleepScore`, `rampRate`, `rampRate_source`, `icu_ftp` and `icu_w_prime`.

Evidence: `backend/performance/context.py:current_performance_context`, `backend/performance/comparisons.py:performance_comparisons`, `backend/performance/load_context.py:performance_load_context`; `tests/test_performance_context.py:PerformanceContextTests.test_composed_context_has_only_neutral_performance_keys`, `tests/test_characterization_coach_context.py`, `tests/test_server_performance.py`.

### Requirement: Personal recovery measurement labels name the method
Personal recovery baselines, sleep goal shortfalls and tag-impact reports SHALL label their measurement with a provider-neutral method name: `duration` for sleep duration, `resting` for resting heart rate, and `RMSSD` or `SDNN` for HRV. They SHALL NOT use a provider field name such as `lastNightAvg`, `sleepSecs`, `sleepTimeSeconds`, `restingHR` or `restingHeartRate`. Series SHALL remain separated by provider and method, and RMSSD and SDNN SHALL not be pooled.

#### Scenario: Garmin and Intervals.icu HRV
- **WHEN** Garmin nightly HRV and Intervals.icu RMSSD observations both exist
- **THEN** both baselines are labelled `RMSSD`, stay two series distinguished by their source label, and the HRV chart heading shows `RMSSD` after the source.

Evidence: `backend/performance/personal_recovery.py:personal_recovery`, `backend/performance/tag_impact.py:tag_impact`; `tests/test_personal_recovery.py:PersonalRecoveryTests`, `tests/test_characterization_recovery.py`, `tests/test_training_record_features.py`, `e2e/analysis-info.spec.js`.
